"""Cross-process coordination and revision checks for managed files."""

import os
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Iterator

from filelock import FileLock

from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)

MANAGED_WRITE_LOCK = RLock()
_HELD_LOCK_PATHS: set[tuple[int, Path]] = set()


def managed_lock_path(root: Path) -> Path:
    """Keep the lock outside its managed directory across moves and removal."""
    absolute = root.expanduser().absolute()
    return absolute.with_name(f".{absolute.name}.apprc.lock")


@contextmanager
def managed_write_lock(
    *roots: Path,
    private_directories: tuple[Path, ...] = (),
) -> Iterator[None]:
    """Hold stable locks for the directories changed by one operation.

    The lock files sit beside their directories so moving or deleting a resource
    root cannot remove a lock while another process waits for it.
    Nested operations reuse locks already held under the process-local RLock.

    :param roots: Configuration or workspace roots that may be changed.
    :param private_directories: Directories to create privately before locking.
        Existing directories are never changed.
    :return: Context that serializes local and cross-process writes.
    """
    lock_paths = sorted({managed_lock_path(root) for root in roots})
    for root in roots:
        assert_no_links(root)
    for path in lock_paths:
        assert_no_links(path)
    for directory in private_directories:
        assert_no_links(directory)
        create_private_directory_if_missing(directory.expanduser().absolute())
    process_id = os.getpid()
    with MANAGED_WRITE_LOCK, ExitStack() as stack:
        for path in lock_paths:
            lock_key = (process_id, path)
            if lock_key in _HELD_LOCK_PATHS:
                continue
            create_private_directory_if_missing(path.parent)
            assert_no_links(path)
            stack.enter_context(
                FileLock(path, timeout=10, preserve_lock_file=True)
            )
            _HELD_LOCK_PATHS.add(lock_key)
            stack.callback(_HELD_LOCK_PATHS.discard, lock_key)
        yield


class StaleEditError(ValueError):
    """A planned edit no longer matches the file that was inspected.

    :param path: File changed since planning.
    :param expected_revision: Planned content digest, or absence.
    :param actual_revision: Current content digest, or absence.
    """

    def __init__(
        self,
        path: Path,
        expected_revision: str | None,
        actual_revision: str | None,
    ) -> None:
        """Retain conflict details without including file contents."""
        super().__init__(
            f"The file changed after planning: {path}. Inspect it and plan again."
        )
        self.path = path
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


def file_revision(path: Path) -> str | None:
    """Read a content digest without creating a missing file.

    :param path: Managed file to inspect.
    :return: SHA-256 revision, or ``None`` when absent.
    """
    try:
        return sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
