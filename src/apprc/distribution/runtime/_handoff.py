"""Shared uninstall handoff identity and containment primitives."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from apprc.definition.installation import (
    InstallationError,
    InstallationRecord,
    RuntimeSlot,
    UninstallPlan,
)
from apprc.user_files.installation.planning import resource_roots


def handoff_removal_roots(
    plan: UninstallPlan, record: InstallationRecord
) -> tuple[Path, ...]:
    """Return only paths the pending uninstall can actually delete.

    Editable checkouts and their environments are never removal roots. Managed
    slots enter only by their active or explicitly retiring record IDs.
    """
    slot_ids = set(record.retiring_runtime_ids)
    if isinstance(record.active_runtime, RuntimeSlot):
        slot_ids.add(record.active_runtime.slot_id)
    roots = [plan.directory / "runtimes" / str(slot_id) for slot_id in slot_ids]
    for output in record.owned_outputs:
        if output.kind in {"shortcut", "command"}:
            path = Path(output.path)
            if path.is_absolute():
                roots.append(Path(os.path.normpath(os.fspath(path))))
    roots.extend(
        entry.path
        for entry in plan.inventory.entries
        if plan.complete or entry.resource is None
    )
    if plan.complete:
        roots.append(plan.directory)
        retained_roots = {
            item.path.resolve() for item in plan.inventory.retained
        }
        roots.extend(
            path
            for kind, path in resource_roots(plan.placement)
            if kind in plan.categories and path.resolve() not in retained_roots
        )
    return tuple(dict.fromkeys(roots))


def assert_outside_removal(path: Path, roots: tuple[Path, ...]) -> None:
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


def _windows_api():
    """Configure pointer-sized Win32 signatures for process identity lookup."""
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


def _linux_process_token(pid: int) -> str:
    """Read Linux process identity while distinguishing exit races."""
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
