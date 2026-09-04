"""Paths below one application's predictable AppRC directory."""

from __future__ import annotations

# == Standard Library ===========================================
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class AppRCDirectoryError(ValueError):
    """An AppRC directory or managed file path is invalid."""


@dataclass(frozen=True, slots=True)
class AppRCDirectoryPaths:
    """Resolved AppRC-managed paths for one application.

    :param root: Application-owned AppRC directory.
    :param user_dotenv: Per-user dotenv override file.
    :param apprc_toml: Storage registry and AppRC metadata file.
    """

    root: Path
    user_dotenv: Path
    apprc_toml: Path


def default_apprc_dir(app_id: str) -> Path:
    """Return the same default AppRC directory on every operating system.

    :param app_id: Stable application identity used as the directory name.
    :return: ``~/.local/share/<app-id>`` below the current user's home.
    """
    return Path.home() / ".local" / "share" / app_id


def normalize_apprc_dir(path: str | Path) -> Path:
    """Return an absolute AppRC directory path without creating it.

    :param path: Declared or user-provided directory.
    :return: Absolute, user-expanded path.
    """
    return Path(path).expanduser().absolute()


def resolve_apprc_dir(
    *,
    app_id: str,
    declared_path: Path | None,
    env_key: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the environment, declaration, or default AppRC directory.

    :param app_id: Stable application identity.
    :param declared_path: Optional application-declared directory.
    :param env_key: Environment key that may override the directory.
    :param proc_env: Environment mapping used instead of ``os.environ``.
    :return: Absolute AppRC directory path without filesystem writes.
    """
    env = os.environ if proc_env is None else proc_env
    raw_path = env.get(env_key, "").strip()
    if raw_path:
        return normalize_apprc_dir(raw_path)
    if declared_path is not None:
        return normalize_apprc_dir(declared_path)
    return default_apprc_dir(app_id)


def apprc_file(apprc_dir: Path, filename: str) -> Path:
    """Return one fixed file below an AppRC directory.

    :param apprc_dir: Resolved AppRC directory.
    :param filename: Managed file basename.
    :return: File path without creating it.
    """
    return apprc_dir / require_filename(filename, field_name="filename")


def resolve_apprc_directory_paths(
    *,
    apprc_dir: Path,
    user_dotenv_path: Path,
    apprc_toml_path: Path,
) -> AppRCDirectoryPaths:
    """Return AppRC-managed paths without creating files.

    :param apprc_dir: Resolved application directory.
    :param user_dotenv_path: Per-user dotenv path.
    :param apprc_toml_path: Storage registry path.
    :return: Resolved AppRC directory paths.
    """
    return AppRCDirectoryPaths(
        root=apprc_dir,
        user_dotenv=user_dotenv_path,
        apprc_toml=apprc_toml_path,
    )


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


def ensure_text_file(path: Path) -> Path:
    """Create an empty text file when it is missing.

    :param path: File path that should exist.
    :return: Resolved file path.
    :raises AppRCDirectoryError: If the target or parent is incompatible.
    """
    resolved = Path(path).expanduser().resolve()
    _ensure_parent_dir(resolved)
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


def write_text_atomic(path: Path, text: str) -> Path:
    """Replace a text file with one same-directory atomic move.

    :param path: Destination file path.
    :param text: UTF-8 text to write.
    :return: Resolved destination path.
    :raises AppRCDirectoryError: If the target or parent is incompatible.
    """
    resolved = Path(path).expanduser().resolve()
    _ensure_parent_dir(resolved)
    if resolved.exists() and not resolved.is_file():
        raise AppRCDirectoryError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    temp_path = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8", newline="")
        temp_path.replace(resolved)
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file could not be written: {resolved}: {exc}"
        ) from exc
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
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file parent could not be created: {parent}: {exc}"
        ) from exc
