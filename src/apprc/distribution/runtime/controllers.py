"""Saved management entry contracts for inspection, repair and removal handoff."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Callable
from uuid import uuid4

from apprc.definition.config_filenames import (
    DEFAULT_APPRC_TOML_FILENAME,
    DEFAULT_USER_DOTENV_FILENAME,
)
from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstallationRecord,
    InstallationTarget,
    InstalledSnapshot,
    InventoryEntry,
    OperationContext,
    OperationStep,
    UninstallPlan,
)
from apprc.definition.paths import ResourceKind
from apprc.distribution.runtime.backend import (
    backend_environment,
    external_base_python,
)
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
    set_windows_private_acl,
    windows_acl_is_private,
)
from apprc.user_files.app_home.ownership import inspect_ownership
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    begin_operation,
    fail_operation,
    plan_uninstall,
    record_step,
)
from apprc.user_files.installation.planning import resource_roots
from apprc.user_files.purge import plan_config_file_purge


def _handoff_removal_roots(
    plan: UninstallPlan, record: InstallationRecord
) -> tuple[Path, ...]:
    """Return only paths the pending uninstall can actually delete."""
    target = record.current or record.last_successful
    if target is None:
        raise InstallationError(
            "No recorded backend is available for an independent controller."
        )
    roots = [
        Path(target.prefix).resolve(),
        *(
            Path(os.path.normpath(os.fspath(path))).absolute()
            for path in target.commands
        ),
    ]
    if plan.complete:
        roots.append(plan.directory.resolve())
        retained_roots = {
            item.path.resolve() for item in plan.inventory.retained
        }
        roots.extend(
            path.resolve()
            for kind, path in resource_roots(plan.placement)
            if (
                kind in plan.categories and path.resolve() not in retained_roots
            )
        )
        roots.extend(item.path.resolve() for item in plan.inventory.entries)
    return tuple(dict.fromkeys(roots))


def _assert_outside_removal(path: Path, roots: tuple[Path, ...]) -> None:
    """Reject a location equal to or nested in an actual delete target."""
    lexical = Path(os.path.normpath(os.fspath(path.expanduser().absolute())))
    resolved = lexical.resolve()
    if any(
        candidate == root or candidate.is_relative_to(root)
        for candidate in (lexical, resolved)
        for root in roots
    ):
        raise InstallationError(
            "Uninstall handoff location overlaps a removal target."
        )


def _assert_private_directory(directory: Path) -> None:
    """Verify the privacy boundary on a newly created handoff directory."""
    assert_no_links(directory)
    if os.name == "nt":
        if not windows_acl_is_private(directory):
            raise InstallationError(
                "Uninstall handoff directory does not have a private Windows ACL."
            )
    elif stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise InstallationError("Uninstall handoff directory must be private.")


def _assert_handoff_inputs_outside_removal(
    paths: tuple[Path, ...], roots: tuple[Path, ...]
) -> None:
    """Check exact staging, recovery and controller paths before mutation."""
    for path in paths:
        _assert_outside_removal(path, roots)
        assert_no_links(path)


def _private_handoff_staging(parent: Path, roots: tuple[Path, ...]) -> Path:
    """Create private staging below a canonical safe temp parent."""
    staging = Path(tempfile.mkdtemp(prefix="apprc-uninstall-", dir=parent))
    try:
        _assert_outside_removal(staging, roots)
        if os.name == "nt":
            set_windows_private_acl(staging)
        _assert_private_directory(staging)
        return staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


@dataclass(frozen=True, slots=True)
class UninstallPreparation:
    """Read-only exact removal preview and optional executable plan."""

    plan: UninstallPlan | None
    inspection: InstallationInspection
    entries: tuple[InventoryEntry, ...]
    diagnostics: tuple[InstallationDiagnostic, ...]
    can_execute: bool


@dataclass(slots=True)
class UninstallHandoff:
    """Independent controller process and explicit original-process exit channel."""

    process: subprocess.Popen[str]
    recovery_command: tuple[str, ...]
    plan_file: Path
    _stdout: IO[str]
    _stdin: IO[str]
    _ready_token: str

    def wait_ready(self) -> None:
        """Wait for this controller's nonce marker and relay other subprocess output."""
        marker = f"APPRC-UNINSTALL-READY:{self._ready_token}\n"
        while line := self._stdout.readline():
            if line == marker:
                return
            print(line, end="", file=sys.stderr, flush=True)
        raise InstallationError(
            "Uninstall controller exited before its readiness marker."
        )

    def signal_exit(self) -> None:
        """Signal the controller immediately before the caller exits its process."""
        self._stdin.write("EXIT\n")
        self._stdin.flush()
        self._stdin.close()


def inspect_saved(directory: Path) -> InstallationInspection:
    """Inspect the adjacent record by its own captured app identity only.

    :param directory: Explicit installation address; never searched or inferred.
    :return: Read-only authority inspection.
    """
    try:
        value = json.loads(
            (directory / "installation.json").read_text(encoding="utf-8")
        )
        app_id = value["app_id"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        app_id = directory.parent.name
    if not isinstance(app_id, str):
        app_id = directory.parent.name
    return inspect_installation(directory, app_id=app_id)


def _support_inventory(
    record,
    directory: Path,
) -> tuple[tuple[InventoryEntry, ...], tuple[str, ...]]:
    """Capture only exact saved support and reject unrecorded install contents."""
    outputs = (
        record.current.owned_outputs
        if record.current is not None
        else record.owned_outputs
    )
    files: dict[Path, str] = {}
    directories: set[Path] = set()
    diagnostics: list[str] = []
    for output in outputs:
        if output.kind != "support":
            continue
        relative = Path(output.path)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or output.digest is None
        ):
            diagnostics.append(
                f"Saved support ownership is malformed: {output.path}."
            )
            continue
        path = directory.joinpath(*relative.parts)
        files[path] = output.digest
        parent = path.parent
        while parent != directory:
            directories.add(parent)
            parent = parent.parent
    entries: list[InventoryEntry] = []
    for path, digest in files.items():
        if not path.exists() and not path.is_symlink():
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or file_revision(path) != digest
        ):
            diagnostics.append(
                f"Saved support output changed after installation: {path}."
            )
            continue
        entries.append(InventoryEntry(path, "file", digest))
    for path in directories:
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                diagnostics.append(
                    f"Saved support directory is unsafe: {path}."
                )
            else:
                entries.append(InventoryEntry(path, "directory", None))
    for root_text, names, filenames in os.walk(directory, followlinks=False):
        root = Path(root_text)
        if root == directory / "locks":
            names.clear()
            continue
        for name in tuple(names):
            path = root / name
            if path == directory / "locks":
                names.remove(name)
                continue
            if path.is_symlink() or path not in directories:
                diagnostics.append(
                    f"Unowned or linked installation directory: {path}."
                )
        for name in filenames:
            path = root / name
            if path != directory / "installation.json" and (
                path.is_symlink() or path not in files
            ):
                diagnostics.append(
                    f"Unowned or linked installation file: {path}."
                )
    return tuple(entries), tuple(dict.fromkeys(diagnostics))


def default_cleanup_inventory(
    inspection: InstallationInspection,
    *,
    categories: frozenset[ResourceKind],
    forget_retained: bool,
) -> CleanupInventory:
    """Capture owned markers and known config files without importing app code.

    Application providers compose this inventory with exact payload targets.
    Unknown payload is never recursively claimed; ``forget_retained`` allows
    its root to remain unmanaged instead of rejecting the default preview.

    :param inspection: Captured saved installation authority and placement.
    :param categories: Resource categories selected for complete removal.
    :param forget_retained: Whether unknown payload may remain in retained roots.
    :return: Exact default targets and roots that must be retained.
    """
    record = inspection.record
    if record is None:
        raise InstallationError("Default inventory requires saved authority.")
    entries: list[InventoryEntry] = []
    retained: list[InventoryEntry] = []
    for category, root in resource_roots(record.placement):
        ownership = inspect_ownership(root, record.app_id, category)
        if ownership == "missing":
            if category not in categories:
                retained.append(
                    InventoryEntry(root, "directory", None, category)
                )
            continue
        if ownership != "owned":
            raise InstallationError(
                f"Refusing default removal of unowned {category} root: {root}"
            )
        if category not in categories:
            retained.append(InventoryEntry(root, "directory", None, category))
            continue
        if category == "config":
            config_plan = plan_config_file_purge(
                record.app_id,
                root,
                user_dotenv_filename=DEFAULT_USER_DOTENV_FILENAME,
                apprc_toml_filename=DEFAULT_APPRC_TOML_FILENAME,
            )
            for target in config_plan.targets:
                if target == root:
                    entries.append(
                        InventoryEntry(root, "directory", None, category)
                    )
                else:
                    entries.append(
                        InventoryEntry(
                            target, "file", file_revision(target), category
                        )
                    )
            if root.exists() and root not in config_plan.targets:
                retained.append(
                    InventoryEntry(root, "directory", None, category)
                )
            continue
        marker = root / ".apprc-owner.json"
        entries.append(
            InventoryEntry(marker, "file", file_revision(marker), category)
        )
        if any(path != marker for path in root.iterdir()):
            if not forget_retained:
                raise InstallationError(
                    f"Unknown {category} contents require explicit inventory: {root}"
                )
            retained.append(InventoryEntry(root, "directory", None, category))
        else:
            entries.append(InventoryEntry(root, "directory", None, category))
    return CleanupInventory(tuple(entries), tuple(retained))


def _resume_uninstall(
    inspection: InstallationInspection,
    *,
    categories: frozenset[ResourceKind],
    complete: bool,
    forget_retained: bool,
    inventory: CleanupInventory | None,
) -> UninstallPlan | None:
    """Rebuild only the matching persisted uninstall at the current revision."""
    record = inspection.record
    operation = record.operation if record is not None else None
    if (
        record is None
        or inspection.status != "incomplete"
        or operation is None
        or operation.kind != "uninstall"
    ):
        return None
    if (
        operation.categories != categories
        or operation.complete != complete
        or operation.forget_retained != forget_retained
        or (inventory is not None and operation.inventory != inventory)
    ):
        raise InstallationError(
            "Retry options or inventory differ from the pending uninstall."
        )
    if inspection.revision is None:
        raise InstallationError("Pending uninstall authority has no revision.")
    return UninstallPlan(
        inspection.directory,
        inspection.revision,
        record.generation_id,
        record.app_id,
        operation.operation_id,
        record.placement,
        operation.inventory,
        operation.categories,
        operation.complete,
        operation.forget_retained,
    )


def prepare_uninstall(
    directory: Path,
    *,
    categories: frozenset[ResourceKind] = frozenset(),
    complete: bool = False,
    forget_retained: bool = False,
    inventory: CleanupInventory | None = None,
) -> UninstallPreparation:
    """Build a read-only uninstall plan from saved or caller-enumerated ownership.

    :param directory: Explicit installation address.
    :param categories: Resource categories selected for complete removal.
    :param complete: Whether support and installation authority are retired.
    :param forget_retained: Whether named unselected roots may remain unmanaged.
    :param inventory: Exact provider enumeration; defaults cover owned markers only.
    :return: Exact preview or diagnostics explaining why planning is unsafe.
    """
    inspection = inspect_saved(directory)
    record = inspection.record
    if record is None:
        return UninstallPreparation(
            None, inspection, (), inspection.diagnostics, False
        )
    try:
        resumed = _resume_uninstall(
            inspection,
            categories=categories,
            complete=complete,
            forget_retained=forget_retained,
            inventory=inventory,
        )
    except InstallationError as error:
        diagnostic = InstallationDiagnostic(
            "uninstall-retry-conflict",
            str(error),
            "Use the persisted options and generation.",
        )
        return UninstallPreparation(
            None, inspection, (), (*inspection.diagnostics, diagnostic), False
        )
    if resumed is not None:
        return UninstallPreparation(
            resumed,
            inspection,
            (*resumed.inventory.entries, *resumed.inventory.retained),
            inspection.diagnostics,
            True,
        )
    if inspection.status not in {"ready", "removed-retained"}:
        return UninstallPreparation(
            None, inspection, (), inspection.diagnostics, False
        )
    try:
        selected_inventory = inventory
        if selected_inventory is None:
            selected_inventory = (
                default_cleanup_inventory(
                    inspection,
                    categories=categories,
                    forget_retained=forget_retained,
                )
                if complete
                else CleanupInventory()
            )
    except (InstallationError, OSError, ValueError) as error:
        diagnostic = InstallationDiagnostic(
            "uninstall-owned-inventory",
            str(error),
            "Provide exact provider inventory for data not represented by owned markers.",
        )
        return UninstallPreparation(
            None, inspection, (), (*inspection.diagnostics, diagnostic), False
        )
    if complete:
        support_entries, support_errors = _support_inventory(record, directory)
        if support_errors:
            diagnostics = tuple(
                InstallationDiagnostic(
                    "uninstall-support-inventory",
                    message,
                    "Repair or inspect unowned/changed support before complete removal.",
                )
                for message in support_errors
            )
            return UninstallPreparation(
                None,
                inspection,
                support_entries,
                (*inspection.diagnostics, *diagnostics),
                False,
            )
    else:
        support_entries = ()
    accepted_inventory_has_support = False
    if inventory is not None and complete:
        accepted_support = tuple(
            entry for entry in inventory.entries if entry.resource is None
        )
        if accepted_support and set(accepted_support) != set(support_entries):
            return UninstallPreparation(
                None,
                inspection,
                (*inventory.entries, *inventory.retained),
                (
                    *inspection.diagnostics,
                    InstallationDiagnostic(
                        "uninstall-support-inventory",
                        "Accepted saved-support inventory changed.",
                        "Repeat preview before removing saved support.",
                    ),
                ),
                False,
            )
        accepted_inventory_has_support = bool(accepted_support)
        if accepted_inventory_has_support:
            selected_inventory = inventory
    all_entries = (
        selected_inventory.entries
        if accepted_inventory_has_support
        else (*selected_inventory.entries, *support_entries)
    )
    for entry in all_entries:
        if entry.kind == "file" and file_revision(entry.path) != entry.revision:
            raise InstallationError(
                f"Cleanup target changed after inventory preview: {entry.path}"
            )
    combined = {entry.path: entry for entry in all_entries}
    if len(combined) != len(all_entries):
        diagnostic = InstallationDiagnostic(
            "uninstall-inventory-overlap",
            "Provider and saved-support inventories overlap.",
            "Pass resource entries only; saved support uses recorded output digests.",
        )
        return UninstallPreparation(
            None,
            inspection,
            tuple(combined.values()),
            (*inspection.diagnostics, diagnostic),
            False,
        )
    if not accepted_inventory_has_support:
        selected_inventory = CleanupInventory(
            tuple(combined.values()), selected_inventory.retained
        )
    entries = (*selected_inventory.entries, *selected_inventory.retained)
    try:
        plan = plan_uninstall(
            record,
            directory=directory,
            revision=inspection.revision or "",
            categories=categories,
            complete=complete,
            forget_retained=forget_retained,
            inventory=selected_inventory,
        )
    except (InstallationError, ValueError) as error:
        diagnostic = InstallationDiagnostic(
            "uninstall-preview-unavailable",
            str(error),
            "Supply exact provider inventory and resolve the named safety issue.",
        )
        return UninstallPreparation(
            None,
            inspection,
            tuple(entries),
            (*inspection.diagnostics, diagnostic),
            False,
        )
    return UninstallPreparation(
        plan, inspection, tuple(entries), inspection.diagnostics, True
    )


def repair_saved(
    directory: Path, *, installer: Path | None = None
) -> tuple[str, ...]:
    """Return exact argv for the recorded matching installer without downloading.

    :param directory: Explicit saved installation address.
    :param installer: Optional selected installer, which must match owned support.
    :return: Absolute interpreter, saved installer and repair arguments.
    """
    inspection = inspect_saved(directory)
    record = inspection.record
    if record is None:
        raise InstallationError(
            "Repair requires a valid saved installation identity."
        )
    if record.operation is not None:
        if (
            record.operation.kind not in {"install", "replace", "repair"}
            or record.operation.intended is None
        ):
            raise InstallationError(
                "Only a matching pending install/replace/repair can be resumed."
            )
        target = record.operation.intended
    else:
        target = record.current or record.last_successful
        if target is None:
            raise InstallationError(
                "Repair requires recorded source and backend inputs."
            )
    selected = installer or directory / "repair-installer.py"
    if (
        not selected.is_absolute()
        or not selected.is_file()
        or selected.is_symlink()
    ):
        raise InstallationError(
            "Matching saved installer is unavailable; no newer installer is downloaded."
        )
    outputs = (
        record.current.owned_outputs
        if record.current is not None
        else record.owned_outputs
    )
    owned = {
        directory / item.path: item.digest
        for item in outputs
        if item.kind == "support"
    }
    digest = owned.get(selected)
    if digest is None or not isinstance(digest, str):
        raise InstallationError(
            "Selected installer is not recorded support for this generation."
        )
    if hashlib.sha256(selected.read_bytes()).hexdigest() != digest:
        raise InstallationError(
            "Saved installer differs from its recorded generation digest."
        )
    return _saved_management_argv(directory, target, selected, ("--repair",))


def _saved_management_argv(
    directory: Path,
    target: InstallationTarget | InstalledSnapshot,
    selected: Path,
    arguments: tuple[str, ...],
) -> tuple[str, ...]:
    """Run saved authored support with the recorded backend and an external Python."""
    # > Pending targets have no observed prefix; exclude their entire backend tool root.
    excluded_root = (
        target.prefix
        if isinstance(target, InstalledSnapshot)
        else target.backend.tool_dir
    )
    python = external_base_python(excluded_root)
    trampoline = (
        "import os,sys; "
        "os.environ['UV_TOOL_DIR']=sys.argv[1]; "
        "os.environ['UV_TOOL_BIN_DIR']=sys.argv[2]; "
        "os.execv(sys.argv[3],sys.argv[3:])"
    )
    return (
        str(python),
        "-I",
        "-c",
        trampoline,
        str(target.backend.tool_dir),
        str(target.backend.bin_dir),
        str(target.backend.executable),
        "run",
        "--no-config",
        "--no-project",
        "--python",
        str(python),
        "--script",
        str(selected),
        *arguments,
        "--directory",
        str(directory),
    )


def uninstall_saved(
    directory: Path,
    *,
    original_pid: int,
    expected_revision: str,
    categories: frozenset[ResourceKind] = frozenset(),
    complete: bool = False,
    forget_retained: bool = False,
    inventory_file: Path | None = None,
) -> tuple[str, ...]:
    """Return verified adjacent authored uninstall argv, preserving the real caller.

    The authored entry must use :func:`parse_uninstall_handoff_args`, forward
    its PID to :func:`start_uninstall_handoff`, and return successfully only
    after receiver readiness and the EXIT channel have been committed.

    :param directory: Explicit saved installation address.
    :param original_pid: Initiating process, which stays alive through saved readiness.
    :param expected_revision: Revision shown in the accepted read-only preview.
    :param categories: Exact user-selected resource categories.
    :param complete: Whether to remove selected data and saved support.
    :param forget_retained: Explicit consent to forget retained ownership.
    :param inventory_file: Private exact inventory accepted during preview.
    :return: External management argv; the caller must propagate failure and exit on success.
    """
    if original_pid <= 0 or not expected_revision:
        raise InstallationError(
            "Original uninstall PID and accepted preview revision are required."
        )
    if categories - {"config", "appdata", "cache", "state"}:
        raise InstallationError("Unknown uninstall resource category.")
    if forget_retained and not complete:
        raise InstallationError("--forget-retained requires --complete.")
    if not directory.is_absolute():
        raise InstallationError("Saved uninstall address must be absolute.")
    assert_no_links(directory)
    inspection = inspect_saved(directory)
    if inspection.revision != expected_revision:
        raise InstallationError("Installation changed after uninstall preview.")
    record = inspection.record
    target = (record.current or record.last_successful) if record else None
    if record is None or target is None:
        raise InstallationError(
            "Saved uninstall requires a recorded backend identity."
        )
    selected = directory / "app-uninstall.py"
    outputs = (
        record.current.owned_outputs if record.current else record.owned_outputs
    )
    digest = next(
        (
            item.digest
            for item in outputs
            if item.kind == "support" and item.path == "app-uninstall.py"
        ),
        None,
    )
    if (
        selected.is_symlink()
        or not selected.is_file()
        or not isinstance(digest, str)
        or hashlib.sha256(selected.read_bytes()).hexdigest() != digest
    ):
        raise InstallationError(
            "Saved application uninstaller is missing or differs from recorded support."
        )
    arguments = [
        "--apprc-original-pid",
        str(original_pid),
        "--apprc-expected-revision",
        expected_revision,
    ]
    if complete:
        arguments.append("--complete")
    for category in sorted(categories):
        arguments.extend(("--category", category))
    if inventory_file is not None:
        if (
            not inventory_file.is_absolute()
            or inventory_file.is_symlink()
            or not inventory_file.is_file()
        ):
            raise InstallationError(
                "Accepted cleanup inventory file is unavailable or unsafe."
            )
        arguments.extend(("--inventory", str(inventory_file)))
    if forget_retained:
        arguments.append("--forget-retained")
    return _saved_management_argv(directory, target, selected, tuple(arguments))


def parse_uninstall_handoff_args(
    argv: Sequence[str] | None = None,
) -> tuple[int | None, str | None, list[str]]:
    """Extract reserved routing metadata before the authored entry parses its flags.

    :param argv: Explicit arguments, or the process arguments when omitted.
    :return: Original PID, accepted preview revision, and authored arguments.
    """
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--apprc-original-pid", type=int)
    parser.add_argument("--apprc-expected-revision")
    args, remaining = parser.parse_known_args(argv)
    if args.apprc_original_pid is not None and args.apprc_original_pid <= 0:
        parser.error("--apprc-original-pid must be positive")
    return args.apprc_original_pid, args.apprc_expected_revision, remaining


def stage_uninstall(
    plan: UninstallPlan,
    *,
    provider_cleanup: Callable[[OperationContext], None],
) -> UninstallPlan:
    """Persist removal intent, run app cleanup while installed, then checkpoint it.

    :param plan: Exact read-only preview accepted by the user.
    :param provider_cleanup: App-owned ordinary cleanup, run before resource locks.
    :return: Plan carrying the exact post-checkpoint revision for handoff.
    """
    with installation_lock(plan.directory):
        current = inspect_saved(plan.directory)
        record = current.record
        operation = record.operation if record is not None else None
        if record is not None and operation is not None:
            if (
                operation.kind != "uninstall"
                or operation.operation_id != plan.operation_id
                or record.generation_id != plan.expected_generation
                or operation.inventory != plan.inventory
                or operation.categories != plan.categories
                or operation.complete != plan.complete
                or operation.forget_retained != plan.forget_retained
            ):
                raise InstallationError(
                    "A different installation operation is pending."
                )
            if OperationStep.PROVIDER_CLEANUP in operation.steps:
                if current.revision is None:
                    raise InstallationError(
                        "Pending removal authority has no revision."
                    )
                return replace(plan, expected_revision=current.revision)
        else:
            if current.revision != plan.expected_revision:
                raise InstallationError(
                    "Installation changed after uninstall preview."
                )
            for entry in plan.inventory.entries:
                if (
                    entry.kind == "file"
                    and file_revision(entry.path) != entry.revision
                ):
                    raise InstallationError(
                        f"Accepted cleanup target changed: {entry.path}"
                    )
            current = begin_operation(plan)
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Pending uninstall authority has no revision."
            )
        context = OperationContext(
            plan.directory,
            plan.operation_id,
            plan.expected_generation,
            plan.placement,
        )
        try:
            provider_cleanup(context)
            current = record_step(
                plan.directory,
                operation_id=plan.operation_id,
                expected_revision=revision,
                step=OperationStep.PROVIDER_CLEANUP,
            )
        except BaseException as error:
            latest = inspect_saved(plan.directory)
            if latest.revision is not None:
                fail_operation(
                    plan.directory,
                    operation_id=plan.operation_id,
                    expected_revision=latest.revision,
                    diagnostic=InstallationDiagnostic(
                        "provider-cleanup-incomplete",
                        str(error),
                        "Retry the same saved uninstall after reviewing provider cleanup effects.",
                    ),
                )
            raise
        if current.revision is None:
            raise InstallationError(
                "Provider-cleanup checkpoint has no revision."
            )
        return replace(plan, expected_revision=current.revision)


def _launch_uninstall_handoff(
    plan: UninstallPlan,
    target: InstalledSnapshot,
    controller_bytes: bytes,
    python: Path,
    environment: dict[str, str],
    staging: Path,
    removal_roots: tuple[Path, ...],
    original_pid: int | None,
) -> UninstallHandoff:
    """Build and launch a checkpointed handoff, preserving its wire protocol."""
    from apprc.distribution.runtime.removal import process_start_token

    directory = plan.directory
    recovery_directory = staging / "recovery"
    recovery_controller = recovery_directory / "controller.py"
    plan_file = staging / "handoff.json"
    reserved_inputs = (
        staging,
        recovery_directory,
        recovery_controller,
        plan_file,
    )
    observed = inspect_saved(directory)
    record = observed.record
    if (
        observed.revision != plan.expected_revision
        or record is None
        or record.operation is None
        or record.operation.kind != "uninstall"
        or record.operation.operation_id != plan.operation_id
        or record.generation_id != plan.expected_generation
        or OperationStep.PROVIDER_CLEANUP not in record.operation.steps
    ):
        raise InstallationError(
            "Persisted provider-cleanup authority is missing or changed."
        )
    pid = original_pid or os.getpid()
    original_start = process_start_token(pid)
    ready_token = uuid4().hex
    payload = {
        "directory": str(directory),
        "app_id": plan.app_id,
        "generation_id": str(plan.expected_generation),
        "operation_id": str(plan.operation_id),
        "expected_revision": plan.expected_revision,
        "original_pid": pid,
        "target_prefix": str(target.prefix),
        "original_start": original_start,
        "recovery_directory": str(recovery_directory),
        "readiness_token": ready_token,
        "complete": plan.complete,
        "categories": sorted(plan.categories),
        "forget_retained": plan.forget_retained,
        "inventory": [
            {
                "path": str(item.path),
                "kind": item.kind,
                "revision": item.revision,
                "resource": item.resource,
            }
            for item in plan.inventory.entries
        ],
        "retained": [
            {
                "path": str(item.path),
                "kind": item.kind,
                "revision": item.revision,
                "resource": item.resource,
            }
            for item in plan.inventory.retained
        ],
    }
    _assert_handoff_inputs_outside_removal(reserved_inputs, removal_roots)
    _assert_private_directory(staging)
    _assert_private_directory(recovery_directory)
    if plan_file.read_bytes() != b"":
        raise InstallationError(
            "Reserved uninstall handoff input changed during provider cleanup."
        )
    if (
        file_revision(recovery_controller)
        != hashlib.sha256(controller_bytes).hexdigest()
    ):
        raise InstallationError(
            "Reserved uninstall recovery controller changed during provider cleanup."
        )
    command = (
        str(target.backend.executable),
        "run",
        "--no-config",
        "--no-project",
        "--python",
        str(python),
        "--script",
        str(recovery_controller),
        "--handoff-plan",
        str(plan_file),
    )
    write_bytes_atomic(
        plan_file,
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        private=True,
    )
    _assert_handoff_inputs_outside_removal(reserved_inputs, removal_roots)
    process: subprocess.Popen[str] = subprocess.Popen(
        command,
        cwd=staging,
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None
    return UninstallHandoff(
        process,
        command,
        plan_file,
        process.stdout,
        process.stdin,
        ready_token,
    )


def start_uninstall_handoff(
    plan: UninstallPlan,
    *,
    original_pid: int | None = None,
    provider_cleanup: Callable[[OperationContext], None] | None = None,
) -> UninstallHandoff:
    """Start the saved controller only after durable provider-cleanup checkpointing.

    :param plan: Exact preview; an unstaged plan is staged here before handoff.
    :param original_pid: Actual caller PID; defaults to this process.
    :param provider_cleanup: App-owned cleanup; only an empty-capability no-op is implicit.
    """

    directory = plan.directory
    observed = inspect_saved(directory)
    record = observed.record
    if record is None:
        raise InstallationError(
            "Saved controller requires valid installation authority."
        )
    outputs = (
        record.current.owned_outputs
        if record.current is not None
        else record.owned_outputs
    )
    owned_support = {
        directory / output.path: output.digest
        for output in outputs
        if output.kind == "support"
    }
    controller = directory / "controller.py"
    controller_digest = owned_support.get(controller)
    controller_bytes = controller.read_bytes() if controller.is_file() else b""
    if (
        controller.is_symlink()
        or not isinstance(controller_digest, str)
        or hashlib.sha256(controller_bytes).hexdigest() != controller_digest
    ):
        raise InstallationError(
            "Saved independent controller is missing or differs from recorded support."
        )
    target = record.current or record.last_successful
    if target is None:
        raise InstallationError(
            "No recorded backend is available for an independent controller."
        )
    removal_roots = _handoff_removal_roots(plan, record)
    temp_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    _assert_outside_removal(temp_parent, removal_roots)
    assert_no_links(temp_parent)
    command_roots = {
        Path(os.path.normpath(os.fspath(path))).absolute()
        for path in target.commands
    }
    base_roots = tuple(
        root for root in removal_roots if root not in command_roots
    )
    base_candidate = Path(sys.base_prefix) / (
        "python.exe" if os.name == "nt" else "bin/python"
    )
    _assert_outside_removal(base_candidate, removal_roots)
    python = external_base_python(
        target.prefix,
        executable=base_candidate,
        forbidden_roots=base_roots,
    )
    environment = backend_environment(target.backend, dict(os.environ))
    invocation_cwd = Path.cwd()
    for key in (
        "UV_CACHE_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "UV_PYTHON_BIN_DIR",
        "TMPDIR",
        "TMP",
        "TEMP",
    ):
        value = environment.get(key)
        if value:
            path = Path(value).expanduser()
            selected_path = (
                path if path.is_absolute() else invocation_cwd / path
            ).resolve()
            _assert_outside_removal(selected_path, removal_roots)
            environment[key] = str(selected_path)
    current_operation = (
        observed.record.operation if observed.record is not None else None
    )
    needs_cleanup = (
        current_operation is None
        or OperationStep.PROVIDER_CLEANUP not in current_operation.steps
    )
    if needs_cleanup and provider_cleanup is None:
        needs_provider = any(
            item.resource not in {None, "config"}
            and item.path.name != ".apprc-owner.json"
            for item in plan.inventory.entries
        )
        if plan.complete and needs_provider:
            raise InstallationError(
                "Selected provider-owned payload requires app-owned cleanup."
            )

        def no_provider_cleanup(_context: OperationContext) -> None:
            return None

        provider_cleanup = no_provider_cleanup
    staging = _private_handoff_staging(temp_parent, removal_roots)
    recovery_directory = staging / "recovery"
    recovery_controller = recovery_directory / "controller.py"
    plan_file = staging / "handoff.json"
    reserved_inputs = (
        staging,
        recovery_directory,
        recovery_controller,
        plan_file,
    )
    try:
        create_private_directory_if_missing(recovery_directory)
        _assert_private_directory(recovery_directory)
        _assert_handoff_inputs_outside_removal(reserved_inputs, removal_roots)
        write_bytes_atomic(recovery_controller, controller_bytes, private=True)
        write_bytes_atomic(plan_file, b"", private=True)
        _assert_handoff_inputs_outside_removal(reserved_inputs, removal_roots)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        if needs_cleanup and provider_cleanup is not None:
            plan = stage_uninstall(plan, provider_cleanup=provider_cleanup)
        return _launch_uninstall_handoff(
            plan,
            target,
            controller_bytes,
            python,
            environment,
            staging,
            removal_roots,
            original_pid,
        )
    except BaseException:
        # > No package removal has begun; saved support lets callers retry the checkpoint.
        shutil.rmtree(staging, ignore_errors=True)
        raise
