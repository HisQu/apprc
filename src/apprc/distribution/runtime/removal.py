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
from ctypes import wintypes
from contextlib import nullcontext
from pathlib import Path
from typing import Literal, TypeGuard, TypedDict
from uuid import UUID

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationSnapshot,
    InstallationWriteAuthority,
    InventoryEntry,
    OperationContext,
    OperationStep,
    ResourceKind,
    UninstallPlan,
)
from apprc.distribution.models import relative_destination
from apprc.distribution.runtime.backend import (
    external_base_python,
    remove_uv_tool,
)
from apprc.distribution.runtime.controllers import (
    _assert_outside_removal,
    _handoff_removal_roots,
)
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
    target_prefix: str
    original_start: str
    readiness_token: str
    recovery_directory: str
    complete: bool
    categories: list[ResourceKind]
    forget_retained: bool
    inventory: list[object]
    retained: list[object]


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


def _windows_api():
    """Configure pointer-sized Win32 handle signatures before process operations."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32, FileTime


def _windows_process_token(handle, pid: int) -> str:
    """Return the creation time tied to an already-open process handle."""
    kernel32, FileTime = _windows_api()
    created, exited, kernel, user = (
        FileTime(),
        FileTime(),
        FileTime(),
        FileTime(),
    )
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise OSError(
            ctypes.get_last_error(), "Could not read process creation time."
        )
    return f"windows:{pid}:{created.high:08x}{created.low:08x}"


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


def _linux_process_token(pid: int) -> str:
    """Read Linux process identity, distinguishing exit races from unsafe reads."""
    try:
        fields = (
            Path(f"/proc/{pid}/stat")
            .read_text(encoding="ascii")
            .rsplit(")", 1)[1]
            .split()
        )
        start_time = fields[19]
    except FileNotFoundError:
        raise
    except (IndexError, UnicodeError) as error:
        raise InstallationError(
            "Could not validate the original Linux process identity."
        ) from error
    return f"linux:{pid}:{start_time}"


def process_start_token(pid: int) -> str:
    """Capture a process identity token while the caller is still alive."""
    if sys.platform.startswith("linux"):
        return _linux_process_token(pid)
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            text=True,
            capture_output=True,
            check=True,
        )
        return f"darwin:{pid}:{result.stdout.strip()}"
    if os.name == "nt":
        kernel32, _ = _windows_api()
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError(
                ctypes.get_last_error(), "Could not open original process."
            )
        try:
            return _windows_process_token(handle, pid)
        finally:
            kernel32.CloseHandle(handle)
    raise InstallationError(
        "This platform has no supported actual-process exit handshake."
    )


def _open_process_waiter(pid: int, expected: str):
    """Create and verify the OS-bound waiter before advertising readiness."""
    if os.name == "nt":
        kernel32, _ = _windows_api()
        handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return "already-exited", None
            raise OSError(
                ctypes.get_last_error(),
                "Could not open original process handle.",
            )
        if _windows_process_token(handle, pid) != expected:
            kernel32.CloseHandle(handle)
            return "already-exited", None
        return "windows", handle
    if sys.platform.startswith("linux"):
        try:
            handle = _linux_pidfd_open(pid)
        except ProcessLookupError:
            return "already-exited", None
        try:
            token = _linux_process_token(pid)
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
            if process_start_token(pid) != expected:
                watcher.close()
                return "already-exited", None
            return "kqueue", watcher
        except OSError:
            watcher.close()
            if process_start_token(pid) != expected:
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
        kernel32, _ = _windows_api()
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


def _parse_plan(path: Path) -> HandoffPlan:
    """Read the private exact handoff envelope without ambient discovery."""
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "directory",
        "app_id",
        "generation_id",
        "operation_id",
        "expected_revision",
        "original_pid",
        "target_prefix",
        "original_start",
        "readiness_token",
        "recovery_directory",
        "complete",
        "categories",
        "forget_retained",
        "inventory",
        "retained",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise InstallationError(
            "Uninstall handoff plan has an incompatible schema."
        )
    token = value["readiness_token"]
    if (
        not isinstance(token, str)
        or re.fullmatch(r"[0-9a-f]{32}", token) is None
    ):
        raise InstallationError("Uninstall readiness token is malformed.")
    directory = value["directory"]
    app_id = value["app_id"]
    generation_id = value["generation_id"]
    operation_id = value["operation_id"]
    target_prefix = value["target_prefix"]
    original_start = value["original_start"]
    expected_revision = value["expected_revision"]
    recovery_directory = value["recovery_directory"]
    original_pid = value["original_pid"]
    complete = value["complete"]
    categories = value["categories"]
    forget_retained = value["forget_retained"]
    inventory = value["inventory"]
    retained = value["retained"]
    if (
        not isinstance(directory, str)
        or not Path(directory).is_absolute()
        or not isinstance(app_id, str)
        or not app_id
        or not _is_uuid(generation_id)
        or not _is_uuid(operation_id)
        or not isinstance(target_prefix, str)
        or not Path(target_prefix).is_absolute()
        or not isinstance(original_start, str)
        or not isinstance(expected_revision, str)
        or not isinstance(recovery_directory, str)
        or Path(recovery_directory) != path.parent / "recovery"
        or type(original_pid) is not int
        or original_pid <= 0
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
            raise InstallationError(
                "Uninstall handoff plan has an unknown resource category."
            )
        category_values.append(category)
    return {
        "directory": directory,
        "app_id": app_id,
        "generation_id": generation_id,
        "operation_id": operation_id,
        "expected_revision": expected_revision,
        "original_pid": original_pid,
        "target_prefix": target_prefix,
        "original_start": original_start,
        "readiness_token": token,
        "recovery_directory": recovery_directory,
        "complete": complete,
        "categories": category_values,
        "forget_retained": forget_retained,
        "inventory": inventory,
        "retained": retained,
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


def _recovery_support_digest(recovery: Path, relative_path: str) -> str:
    """Return one exact support digest from the durable external recovery manifest."""
    manifest = recovery / "support-backup.json"
    assert_no_links(manifest)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise InstallationError(
            "External support recovery manifest is malformed."
        )
    matches = [
        item
        for item in value
        if isinstance(item, dict) and item.get("path") == relative_path
    ]
    if len(matches) != 1:
        raise InstallationError(
            f"External recovery does not own {relative_path}."
        )
    entry = matches[0]
    digest = entry.get("digest")
    if (
        set(entry) != {"path", "digest", "mode"}
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise InstallationError(
            "External final-worker recovery digest is malformed."
        )
    return digest


def execute_handoff(plan_file: Path) -> None:
    """Wait for caller exit, then remove exact package, data, support and authority.

    :param plan_file: Private absolute plan staged outside every removal target.
    """
    value = _parse_plan(plan_file)
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
    finalizer = recovery / "final-worker.py"
    finalization_plan = recovery / "finalization.json"
    app_id = value["app_id"]
    operation_id = UUID(value["operation_id"])
    generation_id = UUID(value["generation_id"])
    inspection = inspect_installation(directory, app_id=app_id)
    record = inspection.record
    if record is None:
        if (
            not value["complete"]
            or finalizer.is_symlink()
            or not finalizer.is_file()
            or finalization_plan.is_symlink()
            or not finalization_plan.is_file()
        ):
            raise InstallationError(
                "Uninstall authority is missing before safe finalization."
            )
        assert_no_links(finalizer)
        assert_no_links(finalization_plan)
        expected_plan = {"directory": str(directory), "support": []}
        if (
            json.loads(finalization_plan.read_text(encoding="utf-8"))
            != expected_plan
        ):
            raise InstallationError(
                "External finalization plan changed after uninstall commit."
            )
        expected_digest = _recovery_support_digest(recovery, "final-worker.py")
        if file_revision(finalizer) != expected_digest:
            raise InstallationError(
                "External final worker differs from the committed support backup."
            )
        roots = (directory.resolve(),)
        receiver_paths = (
            Path(sys.prefix),
            Path(sys.base_prefix),
            Path(sys.executable),
            Path.cwd(),
            plan_file.parent,
            plan_file,
            recovery,
            recovery / "controller.py",
            finalizer,
            finalization_plan,
        )
        for path in receiver_paths:
            _assert_outside_removal(path, roots)
        for path in (
            plan_file.parent,
            plan_file,
            recovery,
            recovery / "controller.py",
            finalizer,
            finalization_plan,
        ):
            assert_no_links(path)
        python = external_base_python(
            Path(value["target_prefix"]), forbidden_roots=roots
        )
        waiter = _open_process_waiter(
            value["original_pid"], value["original_start"]
        )
        if waiter[0] != "already-exited":
            print(
                f"APPRC-UNINSTALL-READY:{value['readiness_token']}", flush=True
            )
            if sys.stdin.readline() != "EXIT\n":
                raise InstallationError(
                    "Original process did not acknowledge its exit handoff."
                )
            _wait_open_process(waiter)
        subprocess.run(
            [
                str(python),
                str(finalizer),
                "--plan",
                str(finalization_plan),
                "--directory",
                str(directory),
            ],
            check=True,
        )
        shutil.rmtree(plan_file.parent)
        return
    if (
        record.generation_id != generation_id
        or record.operation is None
        or record.operation.operation_id != operation_id
        or record.operation.kind != "uninstall"
        or OperationStep.PROVIDER_CLEANUP not in record.operation.steps
    ):
        raise InstallationError(
            "Uninstall authority changed before handoff readiness."
        )
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
    latest_revision = inspection.revision
    if latest_revision is None:
        raise InstallationError("Pending uninstall authority has no revision.")
    if latest_revision != value["expected_revision"]:
        raise InstallationError(
            "Pending uninstall authority changed before handoff readiness."
        )
    complete = value["complete"]
    registry_backup: list[tuple[str, dict[str, str]]] = []
    committed = False
    succeeded = False
    target = record.current or record.last_successful
    if target is None:
        raise InstallationError(
            "Saved backend identity is unavailable for removal."
        )
    persisted_plan = UninstallPlan(
        directory,
        latest_revision,
        generation_id,
        app_id,
        operation_id,
        record.placement,
        inventory,
        operation.categories,
        operation.complete,
        operation.forget_retained,
    )
    removal_roots = _handoff_removal_roots(persisted_plan, record)
    command_roots = {
        Path(os.path.normpath(os.fspath(command))).absolute()
        for command in target.commands
    }
    management_roots = tuple(
        root for root in removal_roots if root not in command_roots
    )
    base_candidate = Path(sys.base_prefix) / (
        "python.exe" if os.name == "nt" else "bin/python"
    )
    receiver_paths = (
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable),
        Path.cwd(),
        base_candidate,
        plan_file.parent,
        plan_file,
        recovery,
        recovery / "controller.py",
        finalizer,
        finalization_plan,
    )
    for path in receiver_paths:
        _assert_outside_removal(path, removal_roots)
    for path in (
        plan_file.parent,
        plan_file,
        recovery,
        recovery / "controller.py",
        finalizer,
        finalization_plan,
    ):
        assert_no_links(path)
    python = external_base_python(
        target.prefix,
        executable=base_candidate,
        forbidden_roots=management_roots,
    )
    waiter = _open_process_waiter(
        value["original_pid"], value["original_start"]
    )
    if waiter[0] != "already-exited":
        print(f"APPRC-UNINSTALL-READY:{value['readiness_token']}", flush=True)
        if sys.stdin.readline() != "EXIT\n":
            raise InstallationError(
                "Original process did not acknowledge its exit handoff."
            )
        _wait_open_process(waiter)
    try:
        with installation_lock(directory):
            current = inspect_installation(directory, app_id=app_id)
            current_record = current.record
            if (
                current_record is None
                or current_record.generation_id != generation_id
                or current_record.operation is None
                or current_record.operation.operation_id != operation_id
                or current_record.operation.kind != "uninstall"
                or current_record.operation.inventory != inventory
                or current_record.operation.categories
                != frozenset(value["categories"])
                or current_record.operation.complete != complete
                or current_record.operation.forget_retained
                != value["forget_retained"]
                or current.revision != value["expected_revision"]
            ):
                raise InstallationError(
                    "Pending uninstall authority changed before backend removal."
                )
            latest_revision = current.revision
            if latest_revision is None:
                raise InstallationError(
                    "Pending uninstall authority has no current revision."
                )

            if complete:
                roots = tuple(
                    root for _, root in resource_roots(current_record.placement)
                )
                snapshot = InstallationSnapshot(
                    directory, latest_revision, generation_id
                )
                context = OperationContext(
                    directory,
                    operation_id,
                    generation_id,
                    current_record.placement,
                )
                authority = InstallationWriteAuthority(
                    app_id, snapshot, context
                )
                resource_lock = managed_write_lock(*roots, authority=authority)
            else:
                resource_lock = nullcontext()

            with resource_lock:
                if complete:
                    _restore_support(recovery, directory)
                    _backup_support(inventory.entries, directory, recovery)
                    expected_digest = _recovery_support_digest(
                        recovery, "final-worker.py"
                    )
                    support_source = directory / "final-worker.py"
                    assert_no_links(support_source)
                    if file_revision(support_source) != expected_digest:
                        raise InstallationError(
                            "Saved final worker is missing or differs from recorded support."
                        )
                    if finalizer.exists() or finalizer.is_symlink():
                        assert_no_links(finalizer)
                        if file_revision(finalizer) != expected_digest:
                            raise InstallationError(
                                "External final worker differs from the committed support backup."
                            )
                    else:
                        finalizer.write_bytes(support_source.read_bytes())
                        os.chmod(finalizer, 0o600)
                    assert_no_links(finalization_plan)
                    if finalization_plan.exists():
                        expected_plan = {
                            "directory": str(directory),
                            "support": [],
                        }
                        if (
                            json.loads(
                                finalization_plan.read_text(encoding="utf-8")
                            )
                            != expected_plan
                        ):
                            raise InstallationError(
                                "External finalization plan changed."
                            )
                    else:
                        finalization_plan.write_text(
                            json.dumps(
                                {"directory": str(directory), "support": []},
                                sort_keys=True,
                            )
                            + "\n",
                            encoding="utf-8",
                        )

                remove_uv_tool(
                    target.backend,
                    target.identity.distribution,
                    environment=dict(os.environ),
                )
                current = record_step(
                    directory,
                    operation_id=operation_id,
                    expected_revision=latest_revision,
                    step=OperationStep.PACKAGE_REMOVED,
                )
                latest_revision = current.revision
                if latest_revision is None:
                    raise InstallationError(
                        "Package removal checkpoint lacks a revision."
                    )

                if complete:
                    _remove_inventory(inventory.entries)
                    current = record_step(
                        directory,
                        operation_id=operation_id,
                        expected_revision=latest_revision,
                        step=OperationStep.DATA_REMOVED,
                    )
                    latest_revision = current.revision
                    if latest_revision is None:
                        raise InstallationError(
                            "Complete cleanup checkpoint lacks a revision."
                        )
                    _remove_registry_outputs(
                        current_record, directory, registry_backup
                    )
                    result = commit_uninstall(
                        directory,
                        operation_id=operation_id,
                        expected_revision=latest_revision,
                    )
                    if result.kind != "retired":
                        raise InstallationError(
                            "Complete uninstall unexpectedly retained authority."
                        )
                    committed = True
                    retire_held_operation_lock(directory)
                else:
                    _label_retained_registration(
                        current_record, directory, registry_backup
                    )
                    commit_uninstall(
                        directory,
                        operation_id=operation_id,
                        expected_revision=latest_revision,
                    )
                    succeeded = True

        if complete:
            retirement = finish_namespace_retirement(
                directory, generation_id=generation_id
            )
            if retirement.container not in {"removed", "occupied"}:
                raise InstallationError(
                    retirement.diagnostic
                    or "Installation namespace cleanup left residue."
                )
            subprocess.run(
                [
                    str(python),
                    str(finalizer),
                    "--plan",
                    str(finalization_plan),
                    "--directory",
                    str(directory),
                ],
                check=True,
            )
            succeeded = True
    except BaseException as error:
        if not committed:
            try:
                _recover_pending_uninstall(
                    directory,
                    app_id=app_id,
                    generation_id=generation_id,
                    operation_id=operation_id,
                    inventory=inventory,
                    complete=complete,
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
        if complete:
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
    record,
    directory: Path,
    removed: list[tuple[str, dict[str, str]]],
) -> None:
    """Delete only exact, fully owned current-user registration values."""
    if os.name != "nt":
        return
    import winreg

    owned_outputs = (
        record.current.owned_outputs
        if record.current is not None
        else record.owned_outputs
    )
    for output in owned_outputs:
        if output.kind != "hkcu":
            continue
        prefix = "HKCU\\"
        if not output.path.startswith(prefix):
            raise InstallationError(
                "Recorded HKCU registration path is malformed."
            )
        subkey = output.path[len(prefix) :]
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
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
            target = record.current or record.last_successful
            if target is None:
                raise InstallationError(
                    "Owned registration lacks its saved target identity."
                )
            uninstall = str(directory / "uninstall.cmd")
            expected = {
                "DisplayName": values.get("DisplayName"),
                "UninstallString": f'"{uninstall}"',
                "InstallLocation": str(target.prefix),
            }
            if (
                expected["DisplayName"]
                not in {
                    record.app_id,
                    f"{record.app_id} (data retained)",
                }
                or values != expected
            ):
                raise InstallationError(
                    "HKCU uninstall registration changed or contains unknown values."
                )
            removed.append((subkey, values))
            for name in expected:
                winreg.DeleteValue(key, name)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass


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
                allowed = {None, value}
                if name == "DisplayName" and isinstance(value, str):
                    if value.endswith(" (data retained)"):
                        allowed.add(value.removesuffix(" (data retained)"))
                    else:
                        allowed.add(f"{value} (data retained)")
                if actual not in allowed:
                    raise InstallationError(
                        "Cannot restore registration over values changed by another owner."
                    )
            for name, value in previous.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _label_retained_registration(
    record,
    directory: Path,
    backup: list[tuple[str, dict[str, str]]],
) -> None:
    """Keep a reconnectable uninstall entry after package-only removal."""
    if os.name != "nt":
        return
    import winreg

    target = record.current or record.last_successful
    if target is None:
        return
    uninstall = str(directory / "uninstall.cmd")
    owned_outputs = (
        record.current.owned_outputs
        if record.current is not None
        else record.owned_outputs
    )
    for output in owned_outputs:
        if output.kind != "hkcu" or not output.path.startswith("HKCU\\"):
            continue
        subkey = output.path[len("HKCU\\") :]
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            count = winreg.QueryInfoKey(key)[1]
            values = {
                name: value
                for name, value, _kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
            expected = {
                "DisplayName": values.get("DisplayName"),
                "UninstallString": f'"{uninstall}"',
                "InstallLocation": str(target.prefix),
            }
            if (
                expected["DisplayName"]
                not in {
                    record.app_id,
                    f"{record.app_id} (data retained)",
                }
                or values != expected
            ):
                raise InstallationError(
                    "Retained uninstall registration changed ownership."
                )
            backup.append((subkey, values))
            winreg.SetValueEx(
                key,
                "DisplayName",
                0,
                winreg.REG_SZ,
                f"{record.app_id} (data retained)",
            )


def main() -> int:
    """Run the independently staged controller command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-plan", type=Path, required=True)
    arguments = parser.parse_args()
    execute_handoff(arguments.handoff_plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
