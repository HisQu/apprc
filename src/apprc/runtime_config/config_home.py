"""Platform-native AppRC config-home path helpers."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path

# == 3rd Party ===============================
from platformdirs import user_config_path


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
    return app_config_home(app_name) / filename


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
    return AppConfigHome(
        root=root,
        global_env=root / global_env_filename,
        apprc_toml=(
            apprc_toml_path
            if apprc_toml_path is not None
            else root / apprc_toml_filename
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
    paths.root.mkdir(parents=True, exist_ok=True)
    ensure_text_file(paths.global_env)
    ensure_text_file(paths.apprc_toml)
    return paths


def ensure_text_file(path: Path) -> Path:
    """Create an empty text file when it is missing.

    :param path: File path that should exist.
    :return: Resolved file path.
    """
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved.open("x", encoding="utf-8").close()
    except FileExistsError:
        pass
    return resolved


def write_text_atomic(path: Path, text: str) -> Path:
    """Replace a text file with one same-directory atomic move.

    :param path: Destination file path.
    :param text: UTF-8 text to write.
    :return: Resolved destination path.
    """
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temp_path = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(resolved)
    return resolved
