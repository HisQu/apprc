"""Cross-process coordination and revision checks for managed files."""

import os
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Iterator
from time import monotonic
from apprc.definition.installation import InstallationWriteAuthority

from filelock import FileLock, Timeout

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
    authority: InstallationWriteAuthority | None = None,
) -> Iterator[None]:
    """Hold stable locks for the directories changed by one operation.

    The lock files sit beside their directories so moving or deleting a resource
    root cannot remove a lock while another process waits for it.
    Nested operations reuse locks already held under the process-local RLock.

    :param roots: Configuration or workspace roots that may be changed.
    :param private_directories: Directories to create privately before locking.
        Existing directories are never changed.
    :param authority: Captured installation proof revalidated before creating lock parents and after locking.
    :return: Context that serializes local and cross-process writes.
    """
    if authority is not None:
        from apprc.user_files.installation.validation import validate_snapshot

        # > Reject stale writers before creating even the stable lock's parent.
        validate_snapshot(
            authority.snapshot,
            app_id=authority.app_id,
            context=authority.context,
        )
    lock_paths = sorted({managed_lock_path(root) for root in roots})
    for root in roots:
        assert_no_links(root)
    for path in lock_paths:
        assert_no_links(path)
    process_id = os.getpid()
    deadline = monotonic() + 10
    with ExitStack() as stack:
        if not MANAGED_WRITE_LOCK.acquire(
            timeout=max(0, deadline - monotonic())
        ):
            raise Timeout(
                str(lock_paths[0]) if lock_paths else "managed writes"
            )
        stack.callback(MANAGED_WRITE_LOCK.release)
        for path in lock_paths:
            lock_key = (process_id, path)
            if lock_key in _HELD_LOCK_PATHS:
                continue
            create_private_directory_if_missing(path.parent)
            assert_no_links(path)
            stack.enter_context(
                FileLock(
                    path,
                    timeout=max(0, deadline - monotonic()),
                    preserve_lock_file=True,
                    fallback_to_soft=False,
                )
            )
            _HELD_LOCK_PATHS.add(lock_key)
            stack.callback(_HELD_LOCK_PATHS.discard, lock_key)
        if authority is not None:
            validate_snapshot(
                authority.snapshot,
                app_id=authority.app_id,
                context=authority.context,
            )
        for directory in private_directories:
            assert_no_links(directory)
            create_private_directory_if_missing(
                directory.expanduser().absolute()
            )
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
