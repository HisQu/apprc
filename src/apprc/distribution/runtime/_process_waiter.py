"""Stdlib-only process identity and actual-exit waiting shared by finalizers."""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import errno
import os
from pathlib import Path
import select
import subprocess
import sys

InstallationError = ValueError


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


def update_process_identities(
    executables: tuple[Path, ...], environment: Path | None = None
) -> tuple[tuple[int, str], ...]:
    """Identify the caller and Windows launchers whose files may be replaced."""
    from apprc.distribution.runtime._setup_terminal import _process_details

    kernel, _ = _windows_api()
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    query.restype = wintypes.BOOL
    identities = [(os.getpid(), process_start_token(os.getpid()))]
    selected = {path.resolve() for path in (*executables, Path(sys.executable))}
    parent = os.getppid()
    while parent > 0:
        details = _process_details({parent}).get(parent)
        if details is None:
            break
        handle = kernel.OpenProcess(0x1000, False, parent)
        if not handle:
            if any(
                path.name.casefold() == details[1].casefold()
                for path in selected
            ):
                raise OSError(
                    ctypes.get_last_error(),
                    "Could not verify the update launcher.",
                )
            break
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not query(handle, 0, buffer, ctypes.byref(length)):
                raise OSError(
                    ctypes.get_last_error(),
                    "Could not identify the update launcher.",
                )
            image = Path(buffer.value).resolve()
            if image not in selected and (
                environment is None or not image.is_relative_to(environment)
            ):
                break
            identities.append((parent, _windows_process_token(handle, parent)))
        finally:
            kernel.CloseHandle(handle)
        parent = details[0]
    return tuple(identities)
