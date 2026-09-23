"""Cross-process coordination and revision checks for managed files."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Iterator

from filelock import FileLock

MANAGED_WRITE_LOCK = RLock()


def managed_lock_path(root: Path) -> Path:
    """Keep the lock outside its managed directory across moves and removal."""
    absolute = root.expanduser().absolute()
    return absolute.with_name(f".{absolute.name}.apprc.lock")


@contextmanager
def managed_write_lock(*roots: Path) -> Iterator[None]:
    """Hold stable locks for the directories changed by one operation.

    The lock files sit beside their directories so moving or deleting a storage
    root cannot remove a lock while another process waits for it.

    :param roots: AppRC directory or storage roots that may be changed.
    :return: Context that serializes local and cross-process writes.
    """
    lock_paths = sorted({managed_lock_path(root) for root in roots})
    with MANAGED_WRITE_LOCK, ExitStack() as stack:
        for path in lock_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            stack.enter_context(
                FileLock(path, timeout=10, preserve_lock_file=True)
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
