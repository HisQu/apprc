"""Saved management entry contracts for inspection, repair and removal handoff."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO
from uuid import UUID, uuid4

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
    InventoryEntry,
    RuntimeSlot,
    UninstallPlan,
)
from apprc.definition.paths import ResourceKind
from apprc.distribution.runtime import _handoff
from apprc.distribution.runtime.probe import application_bridge
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.ownership import inspect_ownership
from apprc.user_files.app_home.permissions import (
    _path_permissions_are_private,
    create_private_directory_if_missing,
    set_windows_private_acl,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.codec import decode_cleanup_inventory
from apprc.user_files.installation.operations import (
    begin_operation,
    plan_uninstall,
)
from apprc.user_files.installation.planning import resource_roots
from apprc.user_files.purge import plan_config_file_purge


def _assert_private_directory(directory: Path) -> None:
    """Verify the privacy boundary on a newly created handoff directory."""
    assert_no_links(directory)
    if not _path_permissions_are_private(directory):
        if os.name == "nt":
            raise InstallationError(
                "Uninstall handoff directory does not have a private Windows ACL."
            )
        raise InstallationError("Uninstall handoff directory must be private.")


def _assert_handoff_inputs_outside_removal(
    paths: tuple[Path, ...], roots: tuple[Path, ...]
) -> None:
    """Check exact staging, recovery and controller paths before mutation."""
    for path in paths:
        _handoff.assert_outside_removal(path, roots)
        assert_no_links(path)


def _private_handoff_staging(parent: Path, roots: tuple[Path, ...]) -> Path:
    """Create private staging below a canonical safe temp parent."""
    staging = Path(tempfile.mkdtemp(prefix="apprc-uninstall-", dir=parent))
    try:
        _handoff.assert_outside_removal(staging, roots)
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
        identity = value.get("identity") if isinstance(value, dict) else None
        app_id = identity.get("app_id") if isinstance(identity, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        app_id = None
    if not isinstance(app_id, str):
        app_id = directory.parent.name
    return inspect_installation(directory, app_id=app_id)


def _support_inventory(
    record: InstallationRecord,
    directory: Path,
) -> tuple[tuple[InventoryEntry, ...], tuple[str, ...]]:
    """Capture only exact saved support and reject unrecorded install contents."""
    outputs = record.owned_outputs
    files: dict[Path, str] = {}
    directories: set[Path] = set()
    diagnostics: list[str] = []
    runtime_root = directory / "runtimes"
    known_slots = set(record.retiring_runtime_ids)
    if isinstance(record.active_runtime, RuntimeSlot):
        known_slots.add(record.active_runtime.slot_id)
    if runtime_root.exists() or runtime_root.is_symlink():
        if runtime_root.is_symlink() or not runtime_root.is_dir():
            diagnostics.append(
                f"Saved runtime root is unsafe: {runtime_root}."
            )
        else:
            directories.add(runtime_root)
    for output in outputs:
        if output.digest is None:
            if output.kind == "command":
                diagnostics.append(
                    f"Saved command ownership is malformed: {output.path}."
                )
            continue
        if output.kind == "support":
            relative = Path(output.path)
            if (
                relative.is_absolute()
                or not relative.parts
                or ".." in relative.parts
            ):
                diagnostics.append(
                    f"Saved support ownership is malformed: {output.path}."
                )
                continue
            path = directory.joinpath(*relative.parts)
        elif output.kind == "command":
            path = Path(output.path)
            if (
                not path.is_absolute()
                or ".." in path.parts
                or not path.is_relative_to(directory)
            ):
                continue
        else:
            continue
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
        if root == runtime_root:
            for name in tuple(names):
                path = root / name
                try:
                    slot_id = UUID(name)
                except ValueError:
                    slot_id = None
                if slot_id not in known_slots or path.is_symlink():
                    diagnostics.append(
                        f"Unowned or linked managed runtime slot: {path}."
                    )
                names.remove(name)
            for name in filenames:
                diagnostics.append(
                    f"Unowned file in managed runtime root: {root / name}."
                )
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


def _recorded_manager_executable(
    record: InstallationRecord, directory: Path
) -> Path | None:
    """Return the stable manager only while its recorded bytes still match."""
    stable = directory / (
        record.command_name + (".exe" if os.name == "nt" else "")
    )
    output = next(
        (
            item
            for item in record.owned_outputs
            if item.kind == "command" and item.path == str(stable)
        ),
        None,
    )
    if output is None:
        return None
    if not stable.exists() and not stable.is_symlink():
        return None
    assert_no_links(stable)
    if (
        not stable.is_file()
        or output.digest is None
        or file_revision(stable) != output.digest
    ):
        raise InstallationError(
            "Recorded stable manager is missing or changed."
        )
    return stable


def _manager_executable(
    record: InstallationRecord,
    directory: Path,
    selected: Path | None,
) -> Path | None:
    """Prefer an explicitly authenticated manager; otherwise use owned stable bytes."""
    executable = (
        selected
        if selected is not None
        else _recorded_manager_executable(record, directory)
    )
    if executable is None:
        return None
    if not executable.is_absolute():
        raise InstallationError("Manager executable path must be absolute.")
    assert_no_links(executable)
    if not executable.is_file():
        raise InstallationError("Manager executable is unavailable.")
    return executable


def _inventory_from_application(
    inspection: InstallationInspection,
    *,
    categories: frozenset[ResourceKind],
    forget_retained: bool,
    manager_executable: Path | None,
) -> CleanupInventory | None:
    """Request exact app-owned cleanup targets when the active runtime declares a hook."""
    record = inspection.record
    runtime = record.active_runtime if record is not None else None
    if runtime is None or runtime.hooks.inventory is None:
        return None
    if inspection.revision is None:
        raise InstallationError("Inventory provider requires an authority revision.")
    result = application_bridge(
        inspection.directory,
        record.identity,
        runtime,
        command_name=record.command_name,
        action="inventory",
        environment=dict(os.environ),
        manager_executable=manager_executable,
        expected_revision=inspection.revision,
        categories=frozenset(categories),
        forget_retained=forget_retained,
    )
    try:
        return decode_cleanup_inventory(
            json.dumps(result, sort_keys=True).encode("utf-8")
        )
    except (TypeError, ValueError) as error:
        raise InstallationError(
            "Application inventory hook returned malformed cleanup targets."
        ) from error


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
        ownership = inspect_ownership(root, record.identity.app_id, category)
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
                record.identity.app_id,
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
        record.identity.app_id,
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
    manager_executable: Path | None = None,
) -> UninstallPreparation:
    """Build a read-only uninstall plan from saved or caller-enumerated ownership.

    :param directory: Explicit installation address.
    :param categories: Resource categories selected for complete removal.
    :param complete: Whether support and installation authority are retired.
    :param forget_retained: Whether named unselected roots may remain unmanaged.
    :param inventory: Optional exact provider enumeration supplied by the caller.
    :param manager_executable: Authenticated native manager for bridge dispatch.
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
    data_categories = categories - {"config"}
    runtime = record.active_runtime
    if complete and data_categories:
        if (
            runtime is None
            or runtime.hooks.cleanup is None
        ):
            diagnostic = InstallationDiagnostic(
                "uninstall-provider-unavailable",
                "Selected data purge has no recorded runtime cleanup hook.",
                "Restore the recorded runtime or remove the program without purging data.",
            )
            return UninstallPreparation(
                None, inspection, (), (*inspection.diagnostics, diagnostic), False
            )
    try:
        validated_manager = _manager_executable(
            record, directory, manager_executable
        )
        provider_inventory = (
            _inventory_from_application(
                inspection,
                categories=categories,
                forget_retained=forget_retained,
                manager_executable=validated_manager,
            )
            if complete and data_categories
            else None
        )
        if inventory is not None and provider_inventory is not None:
            if inventory != provider_inventory:
                raise InstallationError(
                    "Caller inventory differs from the recorded application provider."
                )
        selected_inventory = inventory or provider_inventory
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



def stage_uninstall(
    plan: UninstallPlan,
    *,
    manager_executable: Path | None = None,
) -> UninstallPlan:
    """Persist exact uninstall intent before the independent handoff starts.

    :param plan: Exact read-only preview accepted by the user.
    :param manager_executable: Authenticated native manager, when setup initiated it.
    :return: Plan carrying the exact pending-authority revision.
    """
    current = inspect_saved(plan.directory)
    record = current.record
    if record is None:
        raise InstallationError("Saved uninstall requires valid authority.")
    _manager_executable(record, plan.directory, manager_executable)
    operation = record.operation
    if operation is not None:
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
    if current.revision is None:
        raise InstallationError("Pending uninstall has no authority revision.")
    return replace(plan, expected_revision=current.revision)



def _handoff_python(removal_roots: tuple[Path, ...]) -> Path:
    """Find a Python executable that will survive the requested removal."""
    candidates = (
        Path(sys.executable),
        Path(sys.base_prefix)
        / ("python.exe" if os.name == "nt" else "bin/python"),
    )
    for candidate in candidates:
        if not candidate.is_absolute() or not candidate.is_file():
            continue
        try:
            _handoff.assert_outside_removal(candidate, removal_roots)
        except InstallationError:
            continue
        return candidate
    raise InstallationError(
        "No external Python executable is available for the removal handoff."
    )


def _copy_handoff_manager(source: Path, destination: Path) -> None:
    """Copy authenticated native-manager bytes outside every removal root."""
    source_revision = file_revision(source)
    shutil.copyfile(source, destination)
    if os.name != "nt":
        os.chmod(destination, 0o700)
    if file_revision(destination) != source_revision:
        raise InstallationError("Native manager changed while it was copied.")


def start_uninstall_handoff(
    plan: UninstallPlan,
    *,
    original_pid: int | None = None,
    manager_executable: Path | None = None,
) -> UninstallHandoff:
    """Launch an independent native or Python controller for the staged plan."""
    directory = plan.directory
    observed = inspect_saved(directory)
    record = observed.record
    if record is None:
        raise InstallationError("Uninstall requires valid installation authority.")
    manager = _manager_executable(record, directory, manager_executable)
    removal_roots = _handoff.handoff_removal_roots(plan, record)
    python_executable = (
        _handoff_python(removal_roots) if manager is None else None
    )
    temp_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    _handoff.assert_outside_removal(temp_parent, removal_roots)
    assert_no_links(temp_parent)
    environment = dict(os.environ)
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
            _handoff.assert_outside_removal(selected_path, removal_roots)
            environment[key] = str(selected_path)
    staging = _private_handoff_staging(temp_parent, removal_roots)
    recovery_directory = staging / "recovery"
    plan_file = staging / "handoff.json"
    manager_copy = (
        staging / ("manager.exe" if os.name == "nt" else "manager")
        if manager is not None
        else None
    )
    pid = original_pid if original_pid is not None else os.getpid()
    try:
        create_private_directory_if_missing(recovery_directory)
        _assert_private_directory(recovery_directory)
        write_bytes_atomic(plan_file, b"", private=True)
        if manager is not None and manager_copy is not None:
            _copy_handoff_manager(manager, manager_copy)
        handoff_inputs = (
            staging,
            recovery_directory,
            plan_file,
            *((manager_copy,) if manager_copy is not None else ()),
        )
        _assert_handoff_inputs_outside_removal(handoff_inputs, removal_roots)
        staged = stage_uninstall(
            plan,
            manager_executable=manager_executable,
        )
        current = inspect_saved(directory)
        pending = current.record
        if (
            current.revision != staged.expected_revision
            or pending is None
            or pending.operation is None
            or pending.operation.operation_id != staged.operation_id
            or pending.operation.kind != "uninstall"
        ):
            raise InstallationError(
                "Persisted pending uninstall changed before handoff launch."
            )
        ready_token = uuid4().hex
        payload = {
            "directory": str(directory),
            "app_id": pending.identity.app_id,
            "generation_id": str(staged.expected_generation),
            "operation_id": str(staged.operation_id),
            "expected_revision": staged.expected_revision,
            "original_pid": pid,
            "original_start": _handoff.process_start_token(pid),
            "recovery_directory": str(recovery_directory),
            "readiness_token": ready_token,
            "complete": staged.complete,
            "categories": sorted(staged.categories),
            "forget_retained": staged.forget_retained,
            "inventory": [
                {
                    "path": str(item.path),
                    "kind": item.kind,
                    "revision": item.revision,
                    "resource": item.resource,
                }
                for item in staged.inventory.entries
            ],
            "retained": [
                {
                    "path": str(item.path),
                    "kind": item.kind,
                    "revision": item.revision,
                    "resource": item.resource,
                }
                for item in staged.inventory.retained
            ],
            "manager_executable": (
                str(manager_copy) if manager_copy is not None else None
            ),
            "manager_executable_revision": (
                file_revision(manager_copy) if manager_copy is not None else None
            ),
        }
        write_bytes_atomic(
            plan_file,
            (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
            private=True,
        )
        if manager_copy is not None:
            command = (str(manager_copy), "--apprc-execute-handoff", str(plan_file))
        else:
            assert python_executable is not None
            python = python_executable
            command = (
                str(python),
                "-m",
                "apprc.distribution.runtime.removal",
                "--handoff-plan",
                str(plan_file),
            )
        environment.pop("PYAPP", None)
        environment.pop("_APPRC_NATIVE_EXECUTABLE", None)
        if manager_copy is not None:
            environment["PYAPP"] = str(manager_copy)
            environment["_APPRC_NATIVE_EXECUTABLE"] = str(manager_copy)
        _assert_handoff_inputs_outside_removal(handoff_inputs, removal_roots)
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
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
