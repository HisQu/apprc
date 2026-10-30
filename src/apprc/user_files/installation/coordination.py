"""Generation-safe installation namespace locking and atomic authority writes."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local
from time import monotonic
from uuid import UUID
from apprc.definition.installation import InstallationRetirement

from filelock import FileLock, Timeout

from apprc.definition.installation import InstallationError, InstallationRecord
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_text_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
    windows_acl_is_private,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.codec import encode_record


class _ThreadLocks(local):
    def __init__(self) -> None:
        self.held: dict[tuple[int, Path], tuple[int, tuple[int, int]]] = {}


_THREAD_LOCKS = _ThreadLocks()


class StaleLockNamespace(InstallationError):
    """An acquired descriptor no longer names the active installation lock."""


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _private_directory(directory: Path) -> None:
    assert_no_links(directory)
    create_private_directory_if_missing(directory)
    info = directory.stat()
    if os.name == "nt":
        private = windows_acl_is_private(directory)
    else:
        private = (
            not (stat.S_IMODE(info.st_mode) & 0o077)
            and info.st_uid == os.getuid()
        )
    if not private:
        raise InstallationError(
            f"Installation directory is not private: {directory}."
        )


@contextmanager
def installation_lock(
    directory: Path,
    *,
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
            raise StaleLockNamespace(
                "Nested operation addresses a retired namespace."
            )
        yield
        return
    acquired_fd: int | None = None
    while True:
        if cancelled is not None and cancelled():
            raise InstallationError("Installation lock acquisition cancelled.")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Timeout(str(path))
        try:
            _private_directory(directory)
            _private_directory(path.parent)
            directory_identity = _identity(directory.stat())

            def acquired(fd: int) -> None:
                nonlocal acquired_fd
                try:
                    assert_no_links(path)
                    if _identity(os.fstat(fd)) != _identity(
                        path.lstat()
                    ) or directory_identity != _identity(directory.stat()):
                        raise StaleLockNamespace(
                            "Installation lock namespace was retired."
                        )
                    acquired_fd = fd
                except FileNotFoundError as error:
                    raise StaleLockNamespace(
                        "Installation lock namespace disappeared."
                    ) from error

            lock = FileLock(
                path,
                timeout=min(remaining, 0.1),
                preserve_lock_file=True,
                fallback_to_soft=False,
                on_acquired=acquired,
            )
            lock.acquire()
        except (StaleLockNamespace, FileNotFoundError, Timeout):
            continue
        break
    assert acquired_fd is not None
    _THREAD_LOCKS.held[key] = (acquired_fd, directory_identity)
    try:
        yield
    finally:
        _THREAD_LOCKS.held.pop(key, None)
        lock.release()


def write_record(
    directory: Path,
    record: InstallationRecord,
    *,
    expected_revision: str | None,
) -> str:
    """Compare and atomically replace authority while the caller holds its lock.

    :param directory: Locked namespace.
    :param record: Complete next authority.
    :param expected_revision: Exact observed bytes digest, or expected absence.
    :return: New exact bytes revision.
    """
    path = directory / "installation.json"
    assert_no_links(path)
    if file_revision(path) != expected_revision:
        raise InstallationError(
            "Installation changed after planning; inspect and plan again."
        )
    content = encode_record(record)
    write_text_atomic(path, content.decode("utf-8"), private=True)
    from hashlib import sha256

    return sha256(content).hexdigest()


def retire_held_operation_lock(directory: Path) -> None:
    """Unlink the verified held POSIX lock only after authority retirement.

    Windows defers its single unlink attempt until every native handle is
    released. No payload deletion is permitted after calling this function.

    :param directory: Retired authority namespace, still locked by this thread.
    """
    if os.name == "nt":
        return
    held = _THREAD_LOCKS.held.get((os.getpid(), directory))
    if held is None:
        raise InstallationError(
            "Retirement requires the held installation lock."
        )
    if (directory / "installation.json").exists():
        raise InstallationError("Cannot retire a lock while authority exists.")
    descriptor, directory_identity = held
    path = directory / "locks" / "operation.lock"
    assert_no_links(path)
    if _identity(directory.stat()) != directory_identity or _identity(
        path.lstat()
    ) != _identity(os.fstat(descriptor)):
        raise StaleLockNamespace("Retirement no longer owns the named lock.")
    path.unlink()


def finish_namespace_retirement(
    directory: Path, *, generation_id: "UUID"
) -> "InstallationRetirement":
    """Attempt only lock unlink/empty rmdir after irreversible record deletion.

    :param directory: Old installation container; never recursively removed.
    :param generation_id: Retired generation, not a claim about a new install.
    :return: Removed, occupied or cleanup residue, without recreating authority.
    """
    from apprc.definition.installation import InstallationRetirement

    try:
        if (directory / "installation.json").exists():
            return InstallationRetirement(
                generation_id,
                directory,
                "occupied",
                "A new authority occupies the installation container.",
            )
        path = directory / "locks" / "operation.lock"
        if os.name == "nt":
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                return InstallationRetirement(
                    generation_id,
                    directory,
                    "occupied",
                    "Installation lock remains in use; old authority is removed.",
                )
        for candidate in (directory / "locks", directory):
            try:
                candidate.rmdir()
            except FileNotFoundError:
                continue
        return InstallationRetirement(generation_id, directory, "removed")
    except OSError as error:
        return InstallationRetirement(
            generation_id, directory, "residue", str(error)
        )
