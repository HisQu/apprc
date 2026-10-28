from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import ResolveOptions
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.layouts import resolve_app_paths
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    apprc_file,
    ensure_text_file,
    require_filename,
    write_text_atomic,
)


def _files(spec: AppConfigSpec, root: Path) -> AppFiles:
    """Bind file helpers to an explicit, isolated path snapshot."""
    paths = resolve_app_paths(
        spec,
        ResolveOptions(layout=Layout.single_root(root)),
        {},
    )
    return AppFiles(spec, paths)


def test_apprc_file_rejects_path_like_filename(tmp_path: Path) -> None:
    invalid_names = ["", ".", "..", "../escape.toml", "nested/app.toml"]

    for filename in invalid_names:
        with pytest.raises(AppRCDirectoryError, match="filename"):
            apprc_file(tmp_path, filename)


def test_require_filename_rejects_windows_path_like_filename() -> None:
    for filename in ("nested\\app.toml", "C:app.toml", "C:\\app.toml"):
        with pytest.raises(AppRCDirectoryError, match="managed_name"):
            require_filename(filename, field_name="managed_name")


def test_app_config_spec_exposes_fixed_configuration_filenames() -> None:
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        paths=Paths(config=True),
        workspaces=Workspaces(),
    )

    assert spec.defaults_dotenv_filename == "apprc.defaults.env"
    assert spec.user_dotenv_filename == "apprc.user.env"
    assert spec.workspace_dotenv_filename == "apprc.workspace.env"
    assert spec.apprc_toml_filename == "apprc.toml"


def test_ensure_user_dotenv_rejects_configuration_root_file(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "demo"
    config_root.write_text("not a directory", encoding="utf-8")
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        paths=Paths(config=True),
        user_dotenv=UserDotenv(),
    )

    with pytest.raises(AppRCDirectoryError, match="parent exists"):
        _files(spec, config_root).ensure_user_dotenv()


def test_ensure_user_dotenv_rejects_directory_target(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    (root / "config" / "apprc.user.env").mkdir(parents=True)
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        paths=Paths(config=True),
        user_dotenv=UserDotenv(),
    )

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        _files(spec, root).ensure_user_dotenv()


def test_ensure_config_file_rejects_directory_target(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    (root / "config" / "apprc.toml").mkdir(parents=True)
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        paths=Paths(config=True),
        workspaces=Workspaces(),
    )

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        ensure_text_file(_files(spec, root).config_file())


def test_write_text_atomic_rejects_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.mkdir()

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        write_text_atomic(target, "VALUE=1\n")
