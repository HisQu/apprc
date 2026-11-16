"""Generation-safe installation namespace locking and atomic authority writes."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID
from apprc.definition.installation import InstallationRetirement

from apprc.user_files.installation._namespace_lock import (
    namespace_lock,
    retire_held_lock,
)

from apprc.definition.installation import InstallationError, InstallationRecord
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_text_atomic,
)
from apprc.user_files.app_home.permissions import (
    _path_permissions_are_private,
    create_private_directory_if_missing,
)

from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.codec import encode_record


class StaleLockNamespace(InstallationError):
    """An acquired descriptor no longer names the active installation lock."""


def _private_directory(directory: Path) -> None:
    assert_no_links(directory)
    create_private_directory_if_missing(directory)
    info = directory.stat()
    private = _path_permissions_are_private(directory, metadata=info)
    if os.name != "nt":
        private = private and info.st_uid == os.getuid()
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
    """Acquire the generation-safe physical installation namespace.

    :param directory: Fixed installation namespace.
    :param timeout: Bounded lock acquisition deadline in seconds.
    :param cancelled: Optional cancellation predicate.
    """
    with namespace_lock(
        directory,
        prepare_directory=_private_directory,
        guard_path=assert_no_links,
        error_type=InstallationError,
        stale_error_type=StaleLockNamespace,
        timeout=timeout,
        cancelled=cancelled,
    ):
        yield


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
    retire_held_lock(
        directory, guard_path=assert_no_links, error_type=InstallationError
    )


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
