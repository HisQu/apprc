"""Shared physical namespace lock used by SDK and staged finalization.

This module imports only stdlib and the existing filelock dependency so the
same lock protocol can survive removal of an editable application environment.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local
from time import monotonic

from filelock import FileLock, Timeout


class NamespaceChangedError(ValueError):
    """The acquired descriptor no longer names the physical namespace."""


class _ThreadLocks(local):
    def __init__(self) -> None:
        self.held: dict[tuple[int, Path], tuple[int, tuple[int, int]]] = {}


_THREAD_LOCKS = _ThreadLocks()


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


@contextmanager
def namespace_lock(
    directory: Path,
    *,
    prepare_directory: Callable[[Path], None],
    guard_path: Callable[[Path], None],
    error_type: type[Exception] = ValueError,
    stale_error_type: type[Exception] = NamespaceChangedError,
    timeout: float = 30,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Acquire the active physical namespace against one bounded deadline.

    :param directory: Explicit fixed installation address.
    :param timeout: Total acquisition/retry deadline in seconds.
    :param cancelled: Optional cancellation predicate checked while acquiring.
    :return: Exclusive lifecycle/support mutation context.
    """
    deadline = monotonic() + timeout
    path = directory / "locks" / "operation.lock"
    key = (os.getpid(), directory)
    held = _THREAD_LOCKS.held.get(key)
    if held is not None:
        fd, expected_identity = held
        if _identity(directory.stat()) != expected_identity or _identity(
            path.lstat()
        ) != _identity(os.fstat(fd)):
            raise stale_error_type(
                "Nested operation addresses a retired namespace."
            )
        yield
        return
    acquired_fd: int | None = None
    while True:
        if cancelled is not None and cancelled():
            raise error_type("Installation lock acquisition cancelled.")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Timeout(str(path))
        try:
            prepare_directory(directory)
            prepare_directory(path.parent)
            directory_identity = _identity(directory.stat())

            def acquired(fd: int) -> None:
                nonlocal acquired_fd
                try:
                    guard_path(path)
                    if _identity(os.fstat(fd)) != _identity(
                        path.lstat()
                    ) or directory_identity != _identity(directory.stat()):
                        raise stale_error_type(
                            "Installation lock namespace was retired."
                        )
                    acquired_fd = fd
                except FileNotFoundError as error:
                    raise stale_error_type(
                        "Installation lock namespace disappeared."
                    ) from error

            lock = FileLock(
                path,
                timeout=min(remaining, 0.1),
                preserve_lock_file=True,
                fallback_to_soft=False,
                on_acquired=acquired,
            )
            try:
                lock.acquire()
            except PermissionError as error:
                if getattr(error, "winerror", None) == 5:
                    error.filename = error.filename or str(path)
                    error.add_note(
                        "AppRC could not open the installation lock."
                    )
                raise
        except (stale_error_type, FileNotFoundError, Timeout):
            continue
        break
    assert acquired_fd is not None
    _THREAD_LOCKS.held[key] = (acquired_fd, directory_identity)
    try:
        yield
    finally:
        _THREAD_LOCKS.held.pop(key, None)
        lock.release()


def retire_held_lock(
    directory: Path,
    *,
    guard_path: Callable[[Path], None],
    error_type: type[Exception] = ValueError,
) -> None:
    """Retire the verified held physical lock after the authority is absent.

    :param directory: Locked installation namespace.
    :param guard_path: Shared path traversal guard.
    :param error_type: Owning layer's error type.
    """
    if os.name == "nt":
        return
    held = _THREAD_LOCKS.held.get((os.getpid(), directory))
    if held is None:
        raise error_type("Retirement requires the held installation lock.")
    if (directory / "installation.json").exists():
        raise error_type("Cannot retire a lock while authority exists.")
    descriptor, directory_identity = held
    path = directory / "locks" / "operation.lock"
    guard_path(path)
    if _identity(directory.stat()) != directory_identity or _identity(
        path.lstat()
    ) != _identity(os.fstat(descriptor)):
        raise error_type("Retirement no longer owns the named lock.")
    path.unlink()
