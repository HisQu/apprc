"""Fixed managed-file derivation and private atomic filesystem I/O."""

from __future__ import annotations

# == Standard Library ===========================================
import os
import stat
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile


class AppRCDirectoryError(ValueError):
    """An AppRC directory or managed file path is invalid."""


def apprc_file(apprc_dir: Path, filename: str) -> Path:
    """Return one fixed file below an AppRC directory.

    :param apprc_dir: Resolved AppRC directory.
    :param filename: Managed file basename.
    :return: File path without creating it.
    """
    return apprc_dir / require_filename(filename, field_name="filename")


def require_filename(filename: str, *, field_name: str) -> str:
    """Return a basename or raise for path-like input.

    :param filename: Candidate managed-file basename.
    :param field_name: Human-facing attribute name for error messages.
    :return: The original filename when it is safe to join below AppRC.
    :raises AppRCDirectoryError: If the value is empty or path-like.
    """
    if not filename:
        raise AppRCDirectoryError(f"{field_name} must not be empty.")
    if (
        filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or Path(filename).is_absolute()
        or PureWindowsPath(filename).drive
    ):
        raise AppRCDirectoryError(
            f"{field_name} must be a single filename, not a path: {filename!r}"
        )
    return filename


def assert_no_links(path: Path) -> None:
    """Reject parent traversal, symlinks and reparse points before mutations.

    :param path: Target path, including ancestors that may not yet exist.
    :raises AppRCDirectoryError: If traversal escapes or redirects the path.
    """
    if ".." in path.parts:
        raise AppRCDirectoryError(
            f"AppRC-managed paths must not contain parent traversal: {path}"
        )
    absolute = path.expanduser().absolute()
    for candidate in (absolute, *absolute.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            os.name == "nt"
            and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise AppRCDirectoryError(
                f"AppRC-managed paths must not traverse links: {candidate}"
            )


def ensure_text_file(path: Path) -> Path:
    """Create an empty text file when it is missing.

    :param path: File path that should exist.
    :return: Resolved file path.
    :raises AppRCDirectoryError: If the target or parent is incompatible.
    """
    resolved = Path(path).expanduser().absolute()
    assert_no_links(resolved)
    _ensure_parent_dir(resolved)
    assert_no_links(resolved)
    if resolved.exists() and not resolved.is_file():
        raise AppRCDirectoryError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    try:
        resolved.open("x", encoding="utf-8").close()
    except FileExistsError:
        if not resolved.is_file():
            raise AppRCDirectoryError(
                f"AppRC-managed file path exists but is not a file: {resolved}"
            )
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file could not be created: {resolved}: {exc}"
        ) from exc
    return resolved


def require_readable_text_file(path: Path) -> Path:
    """Return a managed text file path after proving it can be opened.

    :param path: File path that should be readable by the current process.
    :return: Resolved file path.
    :raises AppRCDirectoryError: If the target is not a readable file.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise AppRCDirectoryError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    try:
        resolved.open("r", encoding="utf-8").close()
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file could not be read: {resolved}: {exc}"
        ) from exc
    return resolved


def write_text_atomic(path: Path, text: str, *, private: bool = False) -> Path:
    """Replace a text file with one same-directory atomic move.

    :param path: Destination file path.
    :param text: UTF-8 text to write.
    :return: Resolved destination path.
    :raises AppRCDirectoryError: If the target or parent is incompatible.
    """
    return write_bytes_atomic(path, text.encode("utf-8"), private=private)


def write_bytes_atomic(
    path: Path, content: bytes, *, private: bool = False
) -> Path:
    """Replace bytes using the same managed-file safety and atomic move.

    :param path: Destination file path.
    :param content: Exact bytes, including generated archives.
    :param private: Require an already private destination boundary.
    :return: Absolute destination path.
    """
    resolved = Path(path).expanduser().absolute()
    assert_no_links(resolved)
    _ensure_parent_dir(resolved)
    assert_no_links(resolved)
    if private:
        from apprc.user_files.env_files.secrets import inspect_secret_file

        status = inspect_secret_file(resolved)
        if not status.available:
            raise AppRCDirectoryError(status.issue or "Unsafe secret file.")
    if resolved.exists() and not resolved.is_file():
        raise AppRCDirectoryError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(content)
        temp_path.replace(resolved)
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file could not be written: {resolved}: {exc}"
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return resolved


def _ensure_parent_dir(path: Path) -> None:
    """Create a path parent or raise when a non-directory blocks it.

    :param path: File path whose parent should be writable.
    :raises AppRCDirectoryError: If an existing parent is not a directory.
    """
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise AppRCDirectoryError(
            f"AppRC-managed file parent exists but is not a directory: {parent}"
        )
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file parent could not be created: {parent}: {exc}"
        ) from exc
