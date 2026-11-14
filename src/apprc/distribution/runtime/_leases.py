"""Inherited handles that keep selected managed runtime slots alive."""

from __future__ import annotations

import contextvars
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from apprc.definition.installation import InstallationError
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation.coordination import installation_lock

_LEASE_NAME = ".apprc-runtime-lease"
_INHERITED_HANDLE = "_APPRC_RUNTIME_LEASE_HANDLE"
_AUTHORIZED_QUIESCENCE: contextvars.ContextVar["RuntimeLease | None"] = (
    contextvars.ContextVar("apprc_runtime_quiescence", default=None)
)


@dataclass(slots=True)
class RuntimeLease:
    """One open shared lease inherited by commands spawned for a runtime."""

    directory: Path
    handle: int
    exclusive: bool = False

    def subprocess_options(self) -> dict[str, Any]:
        """Return child-spawn options that preserve this lease across exec."""
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [self.handle]}
            return {"startupinfo": startup, "close_fds": True}
        return {"pass_fds": (self.handle,), "close_fds": True}

    def environment(self, environment: dict[str, str]) -> dict[str, str]:
        """Return a detached child environment carrying this lease handle."""
        result = dict(environment)
        result[_INHERITED_HANDLE] = str(self.handle)
        return result

    def close(self) -> None:
        """Release this process's reference; inherited children remain protected."""
        if self.handle < 0:
            return
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            close_handle = ctypes.WinDLL(
                "kernel32", use_last_error=True
            ).CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            if not close_handle(wintypes.HANDLE(self.handle)):
                raise OSError(
                    ctypes.get_last_error(), "Unable to close runtime lease"
                )
        else:
            os.close(self.handle)
        self.handle = -1

    def __enter__(self) -> RuntimeLease:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def authorize_bridge(self) -> Iterator[None]:
        """Allow a bridge to inherit this nonblocking exclusive slot claim."""
        if not self.exclusive or self.handle < 0:
            raise InstallationError(
                "A valid exclusive runtime claim is required."
            )
        token = _AUTHORIZED_QUIESCENCE.set(self)
        try:
            yield
        finally:
            _AUTHORIZED_QUIESCENCE.reset(token)


def authorized_runtime_quiescence(directory: Path) -> RuntimeLease | None:
    """Return this operation's exclusive claim for the exact slot."""
    lease = _AUTHORIZED_QUIESCENCE.get()
    return lease if lease is not None and lease.directory == directory else None


def _open_shared_lease(path: Path) -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", wintypes.LPVOID),
                ("bInheritHandle", wintypes.BOOL),
            ]

        security = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), None, True
        )
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(
            str(path),
            0x80000000,
            0x00000001 | 0x00000002,
            ctypes.byref(security),
            4,
            0x80,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(
                ctypes.get_last_error(), "Unable to open runtime lease"
            )
        return int(handle)

    import fcntl

    descriptor = os.open(
        path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0:
            raise InstallationError(
                "Runtime lease must be a zero-data regular file."
            )
        os.set_inheritable(descriptor, True)
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def acquire_runtime_lease(directory: Path) -> RuntimeLease:
    """Acquire a managed slot lease under its installation namespace lock."""
    if directory.parent.name != "runtimes":
        raise InstallationError(
            "Runtime slot is outside its installation runtime area."
        )
    with installation_lock(directory.parent.parent):
        return _acquire_runtime_lease_locked(directory)


def _acquire_runtime_lease_locked(directory: Path) -> RuntimeLease:
    """Open the slot lease while the caller owns the installation lock."""
    assert_no_links(directory)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstallationError("Managed runtime slot is not a real directory.")
    lease = directory / _LEASE_NAME
    assert_no_links(lease)
    try:
        handle = _open_shared_lease(lease)
    except OSError as error:
        raise InstallationError(
            "Unable to acquire managed runtime lease."
        ) from error
    return RuntimeLease(directory, handle)


def acquire_runtime_lease_locked(directory: Path) -> RuntimeLease:
    """Acquire a shared lease while the caller owns installation_lock."""
    if directory.parent.name != "runtimes":
        raise InstallationError(
            "Runtime slot is outside its installation runtime area."
        )
    return _acquire_runtime_lease_locked(directory)


def try_acquire_runtime_quiescence(directory: Path) -> RuntimeLease | None:
    """Claim a managed runtime exclusively without waiting or deleting it."""
    if directory.parent.name != "runtimes":
        raise InstallationError(
            "Runtime slot is outside its installation runtime area."
        )
    with installation_lock(directory.parent.parent):
        assert_no_links(directory)
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise InstallationError(
                "Managed runtime slot is not a real directory."
            )
        lease_path = directory / _LEASE_NAME
        assert_no_links(lease_path)
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateFileW.argtypes = [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.HANDLE,
                ]
                kernel.CreateFileW.restype = wintypes.HANDLE
                handle = kernel.CreateFileW(
                    str(lease_path), 0x80000000, 0, None, 4, 0x80, None
                )
                if handle == wintypes.HANDLE(-1).value:
                    if ctypes.get_last_error() in {5, 32, 33}:
                        return None
                    raise OSError(
                        ctypes.get_last_error(), "Unable to claim runtime slot"
                    )
                descriptor = int(handle)
                os.set_handle_inheritable(descriptor, True)
            else:
                import fcntl

                descriptor = os.open(
                    lease_path,
                    os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0:
                    os.close(descriptor)
                    raise InstallationError(
                        "Runtime lease must be a zero-data regular file."
                    )
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                    return None
                os.set_inheritable(descriptor, True)
            return RuntimeLease(directory, descriptor, exclusive=True)
        except OSError as error:
            if error.errno in {13, 16, 26}:
                return None
            raise InstallationError(
                "Unable to claim runtime slot quiescence."
            ) from error


def _remove_slot_contents(directory: Path, lease_path: Path) -> None:
    for child in directory.iterdir():
        if child == lease_path:
            continue
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def try_retire_runtime_slot(directory: Path) -> bool:
    """Claim a slot under its installation lock and remove it without waiting."""
    if directory.parent.name != "runtimes":
        raise InstallationError(
            "Runtime slot is outside its installation runtime area."
        )
    with installation_lock(directory.parent.parent):
        return _try_retire_runtime_slot_locked(directory)


def _try_retire_runtime_slot_locked(directory: Path) -> bool:
    assert_no_links(directory)
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return True
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstallationError("Managed runtime slot is not a real directory.")
    lease = directory / _LEASE_NAME
    assert_no_links(lease)
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL

            kernel.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel.CreateFileW.restype = wintypes.HANDLE
            handle = kernel.CreateFileW(
                str(lease), 0x00010000, 0, None, 4, 0x04000000, None
            )
            if handle == wintypes.HANDLE(-1).value:
                error = ctypes.get_last_error()
                if error in {32, 33, 5}:
                    return False
                raise OSError(error, "Unable to claim runtime slot lease")
            try:
                _remove_slot_contents(directory, lease)
                if not kernel.CloseHandle(handle):
                    raise OSError(
                        ctypes.get_last_error(), "Unable to close runtime lease"
                    )
                handle = None
                directory.rmdir()
            finally:
                if handle is not None:
                    kernel.CloseHandle(handle)
            return True

        import fcntl

        descriptor = os.open(lease, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            _remove_slot_contents(directory, lease)
            os.close(descriptor)
            descriptor = -1
            lease.unlink()
            directory.rmdir()
            return True
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileNotFoundError:
        return not directory.exists()
    except OSError as error:
        if error.errno in {13, 16, 26}:
            return False
        raise


def inherited_runtime_lease_options(
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate and propagate the managed slot lease adjacent to sys.prefix."""
    captured = os.environ if environment is None else environment
    value = captured.get(_INHERITED_HANDLE)
    if value is None:
        return {}
    if not value.isdecimal():
        raise InstallationError("Inherited runtime lease handle is malformed.")
    handle = int(value)
    prefix = Path(sys.prefix).absolute()
    slot = prefix.parent
    if prefix.name != ".venv" or slot.parent.name != "runtimes":
        raise InstallationError(
            "Inherited lease is not for a managed runtime slot."
        )
    try:
        UUID(slot.name)
    except ValueError as error:
        raise InstallationError(
            "Managed runtime slot identifier is invalid."
        ) from error
    expected = slot / _LEASE_NAME
    assert_no_links(expected)
    try:
        metadata = expected.lstat()
    except OSError as error:
        raise InstallationError(
            "Inherited runtime lease file is unavailable."
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0:
        raise InstallationError(
            "Inherited runtime lease is not a zero-data regular file."
        )
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        open_handle = wintypes.HANDLE(handle)
        if not kernel.GetFinalPathNameByHandleW(
            open_handle, buffer, len(buffer), 0
        ):
            raise InstallationError(
                "Inherited runtime lease handle is unavailable."
            )
        path = Path(buffer.value.removeprefix("\\\\?\\"))
        if os.path.normcase(str(path)) != os.path.normcase(str(expected)):
            raise InstallationError(
                "Inherited runtime lease does not match sys.prefix."
            )
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [handle]}
        return {"startupinfo": startup, "close_fds": True}
    try:
        opened = os.fstat(handle)
    except OSError as error:
        raise InstallationError(
            "Inherited runtime lease handle is unavailable."
        ) from error
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_size != 0
        or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        raise InstallationError(
            "Inherited runtime lease does not match its slot file."
        )
    return {"pass_fds": (handle,), "close_fds": True}
