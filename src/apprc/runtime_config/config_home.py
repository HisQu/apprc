"""Platform-native AppRC config-home path helpers."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

# == 3rd Party ===============================
from platformdirs import user_config_path


class ConfigHomeError(ValueError):
    """Invalid AppRC-managed config-home path or filename."""


@dataclass(frozen=True, slots=True)
class AppConfigHome:
    """Resolved AppRC-managed paths for one application.

    :param root: Platform-native per-user config directory.
    :param global_env: App-global dotenv override file.
    :param apprc_toml: AppRC TOML metadata file.
    """

    root: Path
    global_env: Path
    apprc_toml: Path


def app_config_home(app_name: str) -> Path:
    """Return the platform-native per-user config directory for an app.

    :param app_name: Application name from the AppRC integration spec.
    :return: User config directory such as ``~/.config/<app>`` on Linux.
    """
    return user_config_path(
        appname=app_name,
        appauthor=False,
        roaming=True,
    )


def app_config_file(app_name: str, filename: str) -> Path:
    """Return an app-owned config file path without creating it.

    :param app_name: Application name from the AppRC integration spec.
    :param filename: File basename owned by the host application.
    :return: Path below the platform-native config directory.
    """
    return app_config_home(app_name) / require_config_filename(
        filename,
        field_name="filename",
    )


def resolve_app_config_home(
    *,
    app_name: str,
    global_env_filename: str,
    apprc_toml_filename: str,
    apprc_toml_path: Path | None = None,
) -> AppConfigHome:
    """Return AppRC-managed config paths without creating files.

    :param app_name: Application name from the AppRC integration spec.
    :param global_env_filename: Dotenv filename for app-global overrides.
    :param apprc_toml_filename: Default AppRC TOML basename.
    :param apprc_toml_path: Optional override AppRC TOML path.
    :return: Resolved config-home paths.
    """
    root = app_config_home(app_name)
    global_name = require_config_filename(
        global_env_filename,
        field_name="global_env_filename",
    )
    apprc_name = require_config_filename(
        apprc_toml_filename,
        field_name="apprc_toml_filename",
    )
    return AppConfigHome(
        root=root,
        global_env=root / global_name,
        apprc_toml=(
            apprc_toml_path
            if apprc_toml_path is not None
            else root / apprc_name
        ),
    )


def ensure_app_config_home(
    *,
    app_name: str,
    global_env_filename: str,
    apprc_toml_filename: str,
    apprc_toml_path: Path | None = None,
) -> AppConfigHome:
    """Create AppRC-managed config files without overwriting user content.

    :param app_name: Application name from the AppRC integration spec.
    :param global_env_filename: Dotenv filename for app-global overrides.
    :param apprc_toml_filename: Default AppRC TOML basename.
    :param apprc_toml_path: Optional override AppRC TOML path.
    :return: Resolved config-home paths.
    """
    paths = resolve_app_config_home(
        app_name=app_name,
        global_env_filename=global_env_filename,
        apprc_toml_filename=apprc_toml_filename,
        apprc_toml_path=apprc_toml_path,
    )
    if paths.root.exists() and not paths.root.is_dir():
        raise ConfigHomeError(
            f"AppRC config home exists but is not a directory: {paths.root}"
        )
    try:
        paths.root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigHomeError(
            f"AppRC config home could not be created: {paths.root}: {exc}"
        ) from exc
    ensure_text_file(paths.global_env)
    ensure_text_file(paths.apprc_toml)
    return paths


def require_config_filename(filename: str, *, field_name: str) -> str:
    """Return a config-home basename or raise for path-like input.

    :param filename: Candidate file basename from an integration spec.
    :param field_name: Human-facing attribute name for error messages.
    :return: The original filename when it is safe to join under config home.
    :raises ConfigHomeError: If the value is empty or path-like.
    """
    if not filename:
        raise ConfigHomeError(f"{field_name} must not be empty.")
    if (
        filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or Path(filename).is_absolute()
        or PureWindowsPath(filename).drive
    ):
        raise ConfigHomeError(
            f"{field_name} must be a single filename, not a path: {filename!r}"
        )
    return filename


def ensure_text_file(path: Path) -> Path:
    """Create an empty text file when it is missing.

    :param path: File path that should exist.
    :return: Resolved file path.
    :raises ConfigHomeError: If the target or parent is not file-compatible.
    """
    resolved = Path(path).expanduser().resolve()
    _ensure_parent_dir(resolved)
    if resolved.exists() and not resolved.is_file():
        raise ConfigHomeError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    try:
        resolved.open("x", encoding="utf-8").close()
    except FileExistsError:
        if not resolved.is_file():
            raise ConfigHomeError(
                f"AppRC-managed file path exists but is not a file: {resolved}"
            )
    except OSError as exc:
        raise ConfigHomeError(
            f"AppRC-managed file could not be created: {resolved}: {exc}"
        ) from exc
    return resolved


def require_readable_text_file(path: Path) -> Path:
    """Return a managed text file path after proving it can be opened.

    :param path: File path that should be readable by the current process.
    :return: Resolved file path.
    :raises ConfigHomeError: If the target is not a readable file.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ConfigHomeError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    try:
        resolved.open("r", encoding="utf-8").close()
    except OSError as exc:
        raise ConfigHomeError(
            f"AppRC-managed file could not be read: {resolved}: {exc}"
        ) from exc
    return resolved


def write_text_atomic(path: Path, text: str) -> Path:
    """Replace a text file with one same-directory atomic move.

    :param path: Destination file path.
    :param text: UTF-8 text to write.
    :return: Resolved destination path.
    :raises ConfigHomeError: If the target or parent is not file-compatible.
    """
    resolved = Path(path).expanduser().resolve()
    _ensure_parent_dir(resolved)
    if resolved.exists() and not resolved.is_file():
        raise ConfigHomeError(
            f"AppRC-managed file path exists but is not a file: {resolved}"
        )
    temp_path = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(resolved)
    except OSError as exc:
        raise ConfigHomeError(
            f"AppRC-managed file could not be written: {resolved}: {exc}"
        ) from exc
    return resolved


def _ensure_parent_dir(path: Path) -> None:
    """Create a path parent or raise when a non-directory blocks it.

    :param path: File path whose parent should be writable.
    :raises ConfigHomeError: If an existing parent is not a directory.
    """
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise ConfigHomeError(
            f"AppRC-managed file parent exists but is not a directory: {parent}"
        )
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigHomeError(
            f"AppRC-managed file parent could not be created: {parent}: {exc}"
        ) from exc
