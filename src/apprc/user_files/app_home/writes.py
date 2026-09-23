"""Process-local coordination and revision checks for managed text files."""

from hashlib import sha256
from pathlib import Path
from threading import RLock

MANAGED_WRITE_LOCK = RLock()


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
