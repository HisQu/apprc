"""Independent saved uninstall controller and irreversible finalization path."""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import re
import select
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, TypeGuard
from uuid import UUID

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationRecord,
    InstallationSnapshot,
    InstallationWriteAuthority,
    InventoryEntry,
    OperationContext,
    OperationStep,
    OwnedOutput,
    ResourceKind,
    UninstallPlan,
)
from apprc.distribution.models import relative_destination
from apprc.distribution.runtime._leases import (
    try_acquire_runtime_quiescence,
    try_retire_runtime_slot,
)
from apprc.distribution.runtime.namespace_finalizer import finalize_namespace
from apprc.distribution.runtime.probe import application_bridge
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.writes import file_revision, managed_write_lock
from apprc.user_files.installation.coordination import (
    finish_namespace_retirement,
    installation_lock,
    retire_held_operation_lock,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    commit_uninstall,
    fail_operation,
    record_runtime_retired,
    record_step,
)
from apprc.user_files.installation.planning import resource_roots


class HandoffPlan(TypedDict):
    directory: str
    app_id: str
    generation_id: str
    operation_id: str
    expected_revision: str
    original_pid: int
    original_start: str
    readiness_token: str
    recovery_directory: str
    complete: bool
    categories: list[ResourceKind]
    forget_retained: bool
    inventory: list[object]
    retained: list[object]
    manager_executable: str | None
    manager_executable_revision: str | None


@dataclass(frozen=True, slots=True)
class _PendingHandoff:
    plan: UninstallPlan
    record: InstallationRecord
    manager_executable: Path | None


PathKind = Literal["file", "directory"]


def _is_resource_kind(value: object) -> TypeGuard[ResourceKind]:
    return isinstance(value, str) and value in {
        "config",
        "appdata",
        "cache",
        "state",
    }


def _is_path_kind(value: object) -> TypeGuard[PathKind]:
    return isinstance(value, str) and value in {"file", "directory"}


def _is_uuid(value: object) -> TypeGuard[str]:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _linux_pidfd_open(pid: int) -> int:
    """Open an OS-bound process handle even when Python omits its wrapper."""
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    if pid < 0 or pid > 2**31 - 1:
        raise ValueError("Process ID does not fit the Linux pid_t interface.")
    try:
        pidfd_open = ctypes.CDLL(None, use_errno=True).pidfd_open
    except AttributeError as error:
        raise InstallationError(
            "Linux safe uninstall handoff requires libc pidfd_open support."
        ) from error
    pidfd_open.argtypes = (ctypes.c_int, ctypes.c_uint)
    pidfd_open.restype = ctypes.c_int
    handle = pidfd_open(pid, 0)
    if handle == -1:
        error_number = ctypes.get_errno()
        if error_number == errno.ENOSYS:
            raise InstallationError(
                "Linux safe uninstall handoff requires kernel pidfd support."
            ) from OSError(error_number, os.strerror(error_number))
        raise OSError(error_number, os.strerror(error_number))
    return handle


def _open_process_waiter(pid: int, expected: str):
    """Validate the original process before advertising receiver readiness."""
    if os.name == "nt":
        kernel32, _ = _handoff._windows_api()
        handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return "already-exited", None
            raise OSError(
                ctypes.get_last_error(),
                "Could not open original process handle.",
            )
        if _handoff._windows_process_token(handle, pid) != expected:
            kernel32.CloseHandle(handle)
            return "already-exited", None
        return "windows", handle
    if sys.platform.startswith("linux"):
        try:
            handle = _linux_pidfd_open(pid)
        except ProcessLookupError:
            return "already-exited", None
        try:
            token = _handoff._linux_process_token(pid)
        except FileNotFoundError:
            os.close(handle)
            return "already-exited", None
        except BaseException:
            os.close(handle)
            raise
        if token != expected:
            os.close(handle)
            return "already-exited", None
        return "pidfd", handle
    if sys.platform == "darwin":
        watcher = select.kqueue()
        try:
            event = select.kevent(
                pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                fflags=select.KQ_NOTE_EXIT,
            )
            watcher.control([event], 0, 0)
            if _handoff.process_start_token(pid) != expected:
                watcher.close()
                return "already-exited", None
            return "kqueue", watcher
        except OSError:
            watcher.close()
            if _handoff.process_start_token(pid) != expected:
                return "already-exited", None
            raise
    raise InstallationError(
        "This platform has no supported actual-process exit handshake."
    )


def _wait_open_process(waiter) -> None:
    """Block until the already-validated process handle reports exit."""
    kind, handle = waiter
    if kind == "already-exited":
        return
    if kind == "windows":
        kernel32, _ = _handoff._windows_api()
        try:
            result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            if result != 0:
                raise OSError(
                    ctypes.get_last_error(),
                    "Waiting for original process failed.",
                )
        finally:
            kernel32.CloseHandle(handle)
    elif kind == "pidfd":
        try:
            select.select([handle], [], [])
        finally:
            os.close(handle)
    else:
        try:
            handle.control(None, 1, None)
        finally:
            handle.close()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InstallationError("Uninstall handoff plan has duplicate fields.")
        result[key] = value
    return result


def _parse_plan(path: Path) -> HandoffPlan:
    """Read the private exact handoff envelope without ambient discovery."""
    if not path.is_absolute():
        raise InstallationError("Uninstall handoff plan path must be absolute.")
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )
    required = {
        "directory",
        "app_id",
        "generation_id",
        "operation_id",
        "expected_revision",
        "original_pid",
        "original_start",
        "readiness_token",
        "recovery_directory",
        "complete",
        "categories",
        "forget_retained",
        "inventory",
        "retained",
        "manager_executable",
        "manager_executable_revision",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise InstallationError("Uninstall handoff plan has an incompatible schema.")
    directory = value["directory"]
    app_id = value["app_id"]
    generation_id = value["generation_id"]
    operation_id = value["operation_id"]
    expected_revision = value["expected_revision"]
    original_pid = value["original_pid"]
    original_start = value["original_start"]
    token = value["readiness_token"]
    recovery_directory = value["recovery_directory"]
    complete = value["complete"]
    categories = value["categories"]
    forget_retained = value["forget_retained"]
    inventory = value["inventory"]
    retained = value["retained"]
    manager_text = value["manager_executable"]
    manager_revision = value["manager_executable_revision"]
    if (
        not isinstance(directory, str)
        or not Path(directory).is_absolute()
        or not isinstance(app_id, str)
        or not app_id
        or not _is_uuid(generation_id)
        or not _is_uuid(operation_id)
        or not isinstance(expected_revision, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_revision) is None
        or type(original_pid) is not int
        or original_pid <= 0
        or not isinstance(original_start, str)
        or not isinstance(token, str)
        or re.fullmatch(r"[0-9a-f]{32}", token) is None
        or not isinstance(recovery_directory, str)
        or Path(recovery_directory) != path.parent / "recovery"
        or type(complete) is not bool
        or not isinstance(categories, list)
        or type(forget_retained) is not bool
        or not isinstance(inventory, list)
        or not isinstance(retained, list)
    ):
        raise InstallationError(
            "Uninstall handoff plan has invalid process, path or policy identity."
        )
    category_values: list[ResourceKind] = []
    for category in categories:
        if not _is_resource_kind(category):
            raise InstallationError("Uninstall handoff plan has an unknown category.")
        category_values.append(category)
    if len(category_values) != len(set(category_values)):
        raise InstallationError("Uninstall handoff plan repeats a category.")
    manager_path: Path | None = None
    if manager_text is None:
        if manager_revision is not None:
            raise InstallationError("Handoff manager revision has no executable.")
    else:
        if (
            not isinstance(manager_text, str)
            or not Path(manager_text).is_absolute()
            or Path(manager_text).parent != path.parent
            or Path(manager_text).name
            != ("manager.exe" if os.name == "nt" else "manager")
            or not isinstance(manager_revision, str)
            or re.fullmatch(r"[0-9a-f]{64}", manager_revision) is None
        ):
            raise InstallationError("Uninstall handoff manager binding is malformed.")
        manager_path = Path(manager_text)
        assert_no_links(manager_path)
        if (
            not manager_path.is_file()
            or file_revision(manager_path) != manager_revision
        ):
            raise InstallationError("Uninstall handoff manager copy changed.")
    return {
        "directory": directory,
        "app_id": app_id,
        "generation_id": generation_id,
        "operation_id": operation_id,
        "expected_revision": expected_revision,
        "original_pid": original_pid,
        "original_start": original_start,
        "readiness_token": token,
        "recovery_directory": recovery_directory,
        "complete": complete,
        "categories": category_values,
        "forget_retained": forget_retained,
        "inventory": inventory,
        "retained": retained,
        "manager_executable": str(manager_path) if manager_path is not None else None,
        "manager_executable_revision": manager_revision,
    }


def _inventory(
    value: HandoffPlan, key: Literal["inventory", "retained"]
) -> tuple[InventoryEntry, ...]:
    items = value[key]
    result: list[InventoryEntry] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "kind",
            "revision",
            "resource",
        }:
            raise InstallationError("Uninstall inventory entry is malformed.")
        path = item["path"]
        kind = item["kind"]
        revision = item["revision"]
        resource = item["resource"]
        if (
            not isinstance(path, str)
            or not _is_path_kind(kind)
            or (revision is not None and not isinstance(revision, str))
            or (resource is not None and not _is_resource_kind(resource))
        ):
            raise InstallationError(
                "Uninstall inventory path, kind, revision or resource is malformed."
            )
        result.append(InventoryEntry(Path(path), kind, revision, resource))
    return tuple(result)


def _remove_inventory(entries: tuple[InventoryEntry, ...]) -> None:
    """Remove only exact revision-checked files and empty directories."""
    ordered = sorted(
        entries,
        key=lambda item: (len(item.path.parts), item.path.parts),
        reverse=True,
    )
    for entry in ordered:
        path = entry.path
        assert_no_links(path)
        if not path.exists() and not path.is_symlink():
            continue
        metadata = path.lstat()
        if entry.kind == "file":
            if not path.is_file() or file_revision(path) != entry.revision:
                raise InstallationError(
                    f"Owned file changed after removal preview: {path}."
                )
            path.unlink()
        elif entry.kind == "directory":
            if not path.is_dir():
                raise InstallationError(
                    f"Owned directory changed after removal preview: {path}."
                )
            path.rmdir()
        else:
            raise InstallationError(
                f"Unsupported owned inventory type at {path}."
            )
        del metadata


def _remove_owned_outputs(
    outputs: tuple[OwnedOutput, ...], *, complete: bool
) -> None:
    """Remove only recorded command and shortcut outputs for this uninstall mode."""
    for output in outputs:
        if output.kind == "command":
            if complete:
                _integration.remove_owned_command(output)
            continue
        if output.kind != "shortcut":
            continue
        path = Path(output.path)
        if not path.is_absolute() or output.digest is None:
            raise InstallationError("Recorded shortcut ownership is malformed.")
        assert_no_links(path)
        if not path.exists():
            continue
        if not path.is_file() or file_revision(path) != output.digest:
            raise InstallationError(
                f"Recorded shortcut changed before removal: {path}."
            )
        path.unlink()

def _restore_support(recovery: Path, directory: Path) -> None:
    """Restore exact saved support after a precommit failure; never overwrite edits."""
    manifest = recovery / "support-backup.json"
    assert_no_links(manifest)
    if not manifest.is_file():
        return
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise InstallationError(
            "External support recovery manifest is malformed."
        )
    validated: list[tuple[Path, str, int]] = []
    destinations: set[Path] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "digest",
            "mode",
        }:
            raise InstallationError(
                "External support recovery entry is malformed."
            )
        if (
            not isinstance(item["path"], str)
            or not isinstance(item["digest"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["digest"]) is None
            or type(item["mode"]) is not int
            or not 0 <= item["mode"] <= 0o777
        ):
            raise InstallationError(
                "External support recovery entry is malformed."
            )
        try:
            relative = Path(relative_destination(item["path"]))
        except ValueError as error:
            raise InstallationError(
                "External support recovery path is unsafe."
            ) from error
        if any(
            existing == relative
            or existing in relative.parents
            or relative in existing.parents
            for existing in destinations
        ):
            raise InstallationError("External support recovery paths overlap.")
        destinations.add(relative)
        validated.append((relative, item["digest"], item["mode"]))

    # > Validate every entry before restoring even the first saved file.
    for relative, digest, _mode in validated:
        source = recovery / "support" / relative
        target = directory / relative
        assert_no_links(source)
        assert_no_links(target)
        if not source.is_file() or file_revision(source) != digest:
            raise InstallationError(
                "External support recovery bytes do not match their manifest."
            )
        if target.exists():
            if not target.is_file() or file_revision(target) != digest:
                raise InstallationError(
                    f"Cannot restore support over a changed path: {target}."
                )

    for relative, _digest, mode in validated:
        source = recovery / "support" / relative
        target = directory / relative
        assert_no_links(source)
        assert_no_links(target)
        if target.exists():
            continue
        write_bytes_atomic(target, source.read_bytes(), private=True)
        os.chmod(target, mode & 0o700)


def _backup_support(
    entries: tuple[InventoryEntry, ...], directory: Path, recovery: Path
) -> None:
    """Persist exact support bytes before the irreversible authority boundary."""
    recovery_support = recovery / "support"
    recovery_support.mkdir(mode=0o700, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for entry in entries:
        if entry.resource is not None or not entry.path.is_relative_to(
            directory
        ):
            continue
        if entry.kind != "file":
            continue
        relative = entry.path.relative_to(directory)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or entry.revision is None
            or file_revision(entry.path) != entry.revision
        ):
            raise InstallationError(
                f"Saved support changed before recovery staging: {entry.path}."
            )
        backup = recovery_support / relative
        assert_no_links(backup)
        backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        content = entry.path.read_bytes()
        if file_revision(backup) is not None:
            if file_revision(backup) != entry.revision:
                raise InstallationError(
                    "Existing external support backup differs from its authority."
                )
        else:
            backup.write_bytes(content)
            os.chmod(backup, 0o600)
        manifest.append(
            {
                "path": relative.as_posix(),
                "digest": entry.revision,
                "mode": entry.path.stat().st_mode & 0o777,
            }
        )
    manifest_path = recovery / "support-backup.json"
    content = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    if manifest_path.exists():
        if manifest_path.read_bytes() != content:
            raise InstallationError(
                "External support recovery manifest changed."
            )
    else:
        with manifest_path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())




def execute_handoff(
    plan_file: Path,
    *,
    expected_identity: InstallationIdentity | None = None,
) -> None:
    """Validate and resume the exact pending uninstall handoff."""
    assert_no_links(plan_file)
    value = _parse_plan(plan_file)
    if (
        expected_identity is not None
        and expected_identity.app_id != value["app_id"]
    ):
        raise InstallationError("Handoff plan differs from the native product identity.")
    directory = Path(value["directory"])
    recovery = Path(value["recovery_directory"])
    if (
        recovery.is_symlink()
        or not recovery.is_dir()
        or recovery != plan_file.parent / "recovery"
    ):
        raise InstallationError(
            "Uninstall recovery directory is not the exact private sibling."
        )
    assert_no_links(recovery)
    inspection = inspect_installation(directory, app_id=value["app_id"])
    if inspection.record is None:
        _finalize_committed_handoff(
            plan_file,
            value,
            recovery,
            expected_app_id=(
                expected_identity.app_id
                if expected_identity is not None
                else value["app_id"]
            ),
        )
        return
    pending = _prepare_pending_handoff(
        plan_file,
        value,
        recovery,
        inspection,
        expected_identity=expected_identity,
    )
    _execute_pending_handoff(plan_file, value, recovery, pending)


def _finalize_committed_handoff(
    plan_file: Path,
    value: HandoffPlan,
    recovery: Path,
    *,
    expected_app_id: str,
) -> None:
    """Finish exact namespace retirement after the authority commit."""
    directory = Path(value["directory"])
    finalization_plan = recovery / "finalization.json"
    if (
        not value["complete"]
        or value["app_id"] != expected_app_id
        or finalization_plan.is_symlink()
        or not finalization_plan.is_file()
    ):
        raise InstallationError(
            "Uninstall authority is missing before safe finalization."
        )
    assert_no_links(finalization_plan)
    expected_plan = {
        "directory": str(directory),
        "app_id": expected_app_id,
        "generation_id": value["generation_id"],
        "support": [],
    }
    if json.loads(finalization_plan.read_text(encoding="utf-8")) != expected_plan:
        raise InstallationError("External finalization plan changed after uninstall commit.")
    roots = (directory.resolve(),)
    for path in (
        plan_file.parent,
        plan_file,
        recovery,
        finalization_plan,
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable),
        Path.cwd(),
    ):
        _handoff.assert_outside_removal(path, roots)
    _wait_for_caller_exit(value)
    manager = (
        Path(value["manager_executable"])
        if value["manager_executable"] is not None
        else None
    )
    if manager is None:
        finalize_namespace(
            finalization_plan, directory, expected_app_id=expected_app_id
        )
    else:
        environment = dict(os.environ)
        environment["PYAPP"] = str(manager)
        environment["_APPRC_NATIVE_EXECUTABLE"] = str(manager)
        subprocess.run(
            [
                str(manager),
                "--apprc-finalize-namespace",
                str(finalization_plan),
                str(directory),
            ],
            cwd=plan_file.parent,
            env=environment,
            check=True,
        )
    shutil.rmtree(plan_file.parent)


def _prepare_pending_handoff(
    plan_file: Path,
    value: HandoffPlan,
    recovery: Path,
    inspection: InstallationInspection,
    *,
    expected_identity: InstallationIdentity | None,
) -> _PendingHandoff:
    """Validate pending authority and containment before the exit handshake."""
    directory = Path(value["directory"])
    app_id = value["app_id"]
    operation_id = UUID(value["operation_id"])
    generation_id = UUID(value["generation_id"])
    record = inspection.record
    if (
        record is None
        or record.identity.app_id != app_id
        or (
            expected_identity is not None
            and record.identity != expected_identity
        )
        or record.generation_id != generation_id
        or record.operation is None
        or record.operation.operation_id != operation_id
        or record.operation.kind != "uninstall"
    ):
        raise InstallationError("Uninstall authority changed before handoff readiness.")
    inventory = CleanupInventory(
        _inventory(value, "inventory"), _inventory(value, "retained")
    )
    operation = record.operation
    if (
        operation.inventory != inventory
        or operation.categories != frozenset(value["categories"])
        or operation.complete != value["complete"]
        or operation.forget_retained != value["forget_retained"]
    ):
        raise InstallationError(
            "Pending uninstall inventory differs from its persisted authority."
        )
    revision = inspection.revision
    if revision is None or revision != value["expected_revision"]:
        raise InstallationError("Pending uninstall authority revision changed.")
    plan = UninstallPlan(
        directory,
        revision,
        generation_id,
        app_id,
        operation_id,
        record.placement,
        inventory,
        operation.categories,
        operation.complete,
        operation.forget_retained,
    )
    removal_roots = _handoff.handoff_removal_roots(plan, record)
    manager = (
        Path(value["manager_executable"])
        if value["manager_executable"] is not None
        else None
    )
    receiver_paths = (
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable),
        Path.cwd(),
        plan_file.parent,
        plan_file,
        recovery,
        recovery / "finalization.json",
        *((manager,) if manager is not None else ()),
    )
    for path in receiver_paths:
        _handoff.assert_outside_removal(path, removal_roots)
    for path in (plan_file.parent, plan_file, recovery):
        assert_no_links(path)
    return _PendingHandoff(plan, record, manager)
def _execute_pending_handoff(
    plan_file: Path,
    value: HandoffPlan,
    recovery: Path,
    pending: _PendingHandoff,
) -> None:
    """Wait for the caller, then perform the pending operation through CAS steps."""
    plan = pending.plan
    directory = plan.directory
    app_id = plan.app_id
    operation_id = plan.operation_id
    inventory = plan.inventory
    registry_backup: list[tuple[str, dict[str, str]]] = []
    committed = False
    succeeded = False
    latest_revision = plan.expected_revision
    _wait_for_caller_exit(value)
    try:
        current = inspect_installation(directory, app_id=app_id)
        record = current.record
        if (
            record is None
            or record.identity != pending.record.identity
            or record.generation_id != plan.expected_generation
            or record.operation is None
            or record.operation.operation_id != operation_id
            or record.operation.kind != "uninstall"
            or record.operation.inventory != inventory
            or record.operation.categories != plan.categories
            or record.operation.complete != plan.complete
            or record.operation.forget_retained != plan.forget_retained
            or current.revision != latest_revision
        ):
            raise InstallationError(
                "Pending uninstall authority changed before removal."
            )
        if current.revision is None:
            raise InstallationError("Pending uninstall has no authority revision.")
        latest_revision = current.revision

        operation = record.operation
        data_categories = plan.categories - {"config"}
        needs_cleanup = plan.complete and bool(data_categories)
        if OperationStep.PROVIDER_CLEANUP not in operation.steps:
            runtime = record.active_runtime
            claims = []
            slot_ids = set(record.retiring_runtime_ids)
            if isinstance(runtime, RuntimeSlot):
                slot_ids.add(runtime.slot_id)
            try:
                for slot_id in sorted(slot_ids, key=str):
                    slot_directory = directory / "runtimes" / str(slot_id)
                    claim = try_acquire_runtime_quiescence(slot_directory)
                    if claim is None:
                        raise InstallationError(
                            "A managed runtime is busy; uninstall remains pending without deleting data or runtime files."
                        )
                    claims.append(claim)
                if needs_cleanup:
                    if runtime is None or runtime.hooks.cleanup is None:
                        raise InstallationError(
                            "Selected data purge has no recorded cleanup provider."
                        )
                    context = OperationContext(
                        directory,
                        operation_id,
                        plan.expected_generation,
                        record.placement,
                    )
                    if isinstance(runtime, RuntimeSlot):
                        claim = next(
                            item
                            for item in claims
                            if item.directory
                            == directory / "runtimes" / str(runtime.slot_id)
                        )
                        with claim.authorize_bridge():
                            result = application_bridge(
                                directory,
                                record.identity,
                                runtime,
                                command_name=record.command_name,
                                action="cleanup",
                                environment=dict(os.environ),
                                manager_executable=pending.manager_executable,
                                expected_revision=latest_revision,
                                operation_context=context,
                                categories=frozenset(plan.categories),
                                forget_retained=plan.forget_retained,
                            )
                    else:
                        result = application_bridge(
                            directory,
                            record.identity,
                            runtime,
                            command_name=record.command_name,
                            action="cleanup",
                            environment=dict(os.environ),
                            manager_executable=pending.manager_executable,
                            expected_revision=latest_revision,
                            operation_context=context,
                            categories=frozenset(plan.categories),
                            forget_retained=plan.forget_retained,
                        )
                    if result != {"completed": True}:
                        raise InstallationError(
                            "Application cleanup provider did not confirm completion."
                        )
            finally:
                for claim in reversed(claims):
                    claim.close()
            current = record_step(
                directory,
                operation_id=operation_id,
                expected_revision=latest_revision,
                step=OperationStep.PROVIDER_CLEANUP,
            )
            if current.revision is None:
                raise InstallationError("Cleanup checkpoint has no authority revision.")
            latest_revision = current.revision
            record = current.record
            assert record is not None

        operation = record.operation
        if operation is None:
            raise InstallationError("Pending uninstall checkpoint disappeared.")
        if OperationStep.RUNTIME_REMOVED not in operation.steps:
            retiring = set(record.retiring_runtime_ids)
            slot_ids = set(retiring)
            if isinstance(record.active_runtime, RuntimeSlot):
                slot_ids.add(record.active_runtime.slot_id)
            for slot_id in sorted(slot_ids, key=str):
                slot_directory = directory / "runtimes" / str(slot_id)
                if not try_retire_runtime_slot(slot_directory):
                    raise InstallationError(
                        f"Managed runtime slot is busy and remains intact: {slot_id}."
                    )
                if slot_id in retiring:
                    current = record_runtime_retired(
                        directory,
                        slot_id=slot_id,
                        expected_revision=latest_revision,
                        generation_id=plan.expected_generation,
                    )
                    if current.revision is None:
                        raise InstallationError(
                            "Runtime retirement checkpoint has no revision."
                        )
                    latest_revision = current.revision
                    record = current.record
                    assert record is not None
            current = record_step(
                directory,
                operation_id=operation_id,
                expected_revision=latest_revision,
                step=OperationStep.RUNTIME_REMOVED,
            )
            if current.revision is None:
                raise InstallationError("Runtime absence checkpoint has no revision.")
            latest_revision = current.revision
            record = current.record
            assert record is not None

        if plan.complete:
            if OperationStep.DATA_REMOVED not in record.operation.steps:
                _restore_support(recovery, directory)
                _backup_support(inventory.entries, directory, recovery)
                finalization_plan = recovery / "finalization.json"
                expected_finalization = {
                    "directory": str(directory),
                    "app_id": record.identity.app_id,
                    "generation_id": str(plan.expected_generation),
                    "support": [],
                }
                if finalization_plan.exists():
                    assert_no_links(finalization_plan)
                    if json.loads(
                        finalization_plan.read_text(encoding="utf-8")
                    ) != expected_finalization:
                        raise InstallationError("External finalization plan changed.")
                else:
                    write_bytes_atomic(
                        finalization_plan,
                        (
                            json.dumps(expected_finalization, sort_keys=True)
                            + "\n"
                        ).encode("utf-8"),
                        private=True,
                    )
                roots = tuple(
                    root for _, root in resource_roots(record.placement)
                )
                context = OperationContext(
                    directory,
                    operation_id,
                    plan.expected_generation,
                    record.placement,
                )
                authority = InstallationWriteAuthority(
                    app_id,
                    InstallationSnapshot(
                        directory, latest_revision, plan.expected_generation
                    ),
                    context,
                )
                with managed_write_lock(*roots, authority=authority):
                    _remove_inventory(inventory.entries)
                current = record_step(
                    directory,
                    operation_id=operation_id,
                    expected_revision=latest_revision,
                    step=OperationStep.DATA_REMOVED,
                )
                if current.revision is None:
                    raise InstallationError("Data cleanup checkpoint has no revision.")
                latest_revision = current.revision
                record = current.record
                assert record is not None
            _remove_registry_outputs(record, directory, registry_backup)
            _remove_owned_outputs(record.owned_outputs, complete=True)
            result = commit_uninstall(
                directory,
                operation_id=operation_id,
                expected_revision=latest_revision,
            )
            if result.kind != "retired":
                raise InstallationError("Complete uninstall unexpectedly retained authority.")
            committed = True
            retire_held_operation_lock(directory)
        else:
            _remove_owned_outputs(record.owned_outputs, complete=False)
            commit_uninstall(
                directory,
                operation_id=operation_id,
                expected_revision=latest_revision,
            )
            succeeded = True

        if plan.complete:
            retirement = finish_namespace_retirement(
                directory, generation_id=plan.expected_generation
            )
            if retirement.container not in {"removed", "occupied"}:
                raise InstallationError(
                    retirement.diagnostic
                    or "Installation namespace cleanup left residue."
                )
            _finalize_committed_handoff(plan_file, value, recovery)
            succeeded = True
    except BaseException as error:
        if not committed:
            try:
                _recover_pending_uninstall(
                    directory,
                    app_id=app_id,
                    generation_id=plan.expected_generation,
                    operation_id=operation_id,
                    inventory=inventory,
                    complete=plan.complete,
                    recovery=recovery,
                    registry_backup=tuple(registry_backup),
                    primary_error=error,
                )
            except BaseException as recovery_error:
                raise BaseExceptionGroup(
                    f"Uninstall failed; exact recovery data remains at {recovery}.",
                    [error, recovery_error],
                ) from error
        raise
    finally:
        if succeeded and plan_file.parent.exists():
            shutil.rmtree(plan_file.parent)
def _wait_for_caller_exit(value: HandoffPlan) -> None:
    """Advertise readiness only after validation and wait for the exact caller."""
    waiter = _open_process_waiter(
        value["original_pid"], value["original_start"]
    )
    print(f"APPRC-UNINSTALL-READY:{value['readiness_token']}", flush=True)
    if waiter[0] == "already-exited":
        return
    if sys.stdin.readline() != "EXIT\n":
        raise InstallationError(
            "Original process did not acknowledge its exit handoff."
        )
    _wait_open_process(waiter)


def _recover_pending_uninstall(
    directory: Path,
    *,
    app_id: str,
    generation_id: UUID,
    operation_id: UUID,
    inventory: CleanupInventory,
    complete: bool,
    recovery: Path,
    registry_backup: tuple[tuple[str, dict[str, str]], ...],
    primary_error: BaseException,
) -> None:
    """Restore exact precommit state only while the same pending authority exists."""
    observed = inspect_installation(directory, app_id=app_id)
    record = observed.record
    operation = record.operation if record is not None else None
    if (
        record is None
        or record.generation_id != generation_id
        or operation is None
        or operation.operation_id != operation_id
        or operation.kind != "uninstall"
        or operation.inventory != inventory
    ):
        return

    with installation_lock(directory):
        current = inspect_installation(directory, app_id=app_id)
        record = current.record
        operation = record.operation if record is not None else None
        if (
            record is None
            or record.generation_id != generation_id
            or operation is None
            or operation.operation_id != operation_id
            or operation.kind != "uninstall"
            or operation.inventory != inventory
        ):
            return
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Pending uninstall recovery has no authority revision."
            )
        if (
            complete
            and OperationStep.DATA_REMOVED not in operation.steps
        ):
            _restore_support(recovery, directory)
        _restore_registry_outputs(registry_backup)
        fail_operation(
            directory,
            operation_id=operation_id,
            expected_revision=revision,
            diagnostic=InstallationDiagnostic(
                "uninstall-incomplete",
                str(primary_error),
                "Retry the same saved uninstall after reviewing its recorded cleanup effects.",
            ),
        )


def _remove_registry_outputs(
    record: InstallationRecord,
    directory: Path,
    removed: list[tuple[str, dict[str, str]]],
) -> None:
    """Delete only the exact current-user registration owned by this record."""
    if os.name != "nt":
        return
    import winreg

    expected_subkey = (
        "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
        + record.identity.app_id
    )
    command = directory / (
        record.command_name + (".exe" if os.name == "nt" else "")
    )
    for output in record.owned_outputs:
        if output.kind != "hkcu":
            continue
        if output.path != "HKCU\\" + expected_subkey:
            raise InstallationError("Recorded HKCU registration path is malformed.")
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                expected_subkey,
                0,
                winreg.KEY_QUERY_VALUE,
            )
        except FileNotFoundError:
            continue
        with key:
            count = winreg.QueryInfoKey(key)[1]
            values = {
                name: value
                for name, value, _kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
        removed.append((expected_subkey, values))
        _integration.remove_windows_registration(
            directory, record.identity, command
        )


def _restore_registry_outputs(
    values: tuple[tuple[str, dict[str, str]], ...],
) -> None:
    """Restore only exact values captured from previously owned keys."""
    if os.name != "nt":
        return
    import winreg

    for subkey, previous in values:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            count = winreg.QueryInfoKey(key)[1]
            existing = {
                name: value
                for name, value, _kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
            for name, value in previous.items():
                actual = existing.get(name)
                if actual not in {None, value}:
                    raise InstallationError(
                        "Cannot restore registration over values changed by another owner."
                    )
            for name, value in previous.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

def main() -> int:
    """Run the independently staged controller command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-plan", type=Path, required=True)
    arguments = parser.parse_args()
    execute_handoff(arguments.handoff_plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
