from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.storage import Storage
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    apprc_file,
    require_filename,
    write_text_atomic,
)


def test_apprc_file_rejects_path_like_filename(tmp_path: Path) -> None:
    invalid_names = ["", ".", "..", "../escape.toml", "nested/app.toml"]

    for filename in invalid_names:
        with pytest.raises(AppRCDirectoryError, match="filename"):
            apprc_file(tmp_path, filename)


def test_require_filename_rejects_windows_path_like_filename() -> None:
    for filename in ("nested\\app.toml", "C:app.toml", "C:\\app.toml"):
        with pytest.raises(AppRCDirectoryError, match="managed_name"):
            require_filename(filename, field_name="managed_name")


def test_app_config_spec_exposes_only_fixed_managed_filenames() -> None:
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        storage=Storage(),
    )

    assert spec.defaults_dotenv_filename == "apprc.defaults.env"
    assert spec.user_dotenv_filename == "apprc.user.env"
    assert spec.apprc_toml_filename == "apprc.toml"
    assert spec.storage_dotenv_filename == "apprc.storage.env"


def test_ensure_user_dotenv_rejects_apprc_directory_file(
    tmp_path: Path,
) -> None:
    apprc_dir = tmp_path / "demo"
    apprc_dir.write_text("not a directory", encoding="utf-8")
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        apprc_dir=apprc_dir,
    )

    with pytest.raises(AppRCDirectoryError, match="parent exists"):
        spec.ensure_user_dotenv()


def test_ensure_user_dotenv_rejects_directory_target(tmp_path: Path) -> None:
    apprc_dir = tmp_path / "demo"
    (apprc_dir / "apprc.user.env").mkdir(parents=True)
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        apprc_dir=apprc_dir,
    )

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        spec.ensure_user_dotenv()


def test_ensure_apprc_toml_rejects_directory(tmp_path: Path) -> None:
    apprc_dir = tmp_path / "demo"
    (apprc_dir / "apprc.toml").mkdir(parents=True)
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        storage=Storage(),
        apprc_dir=apprc_dir,
    )

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        spec.ensure_apprc_toml()


def test_write_text_atomic_rejects_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.mkdir()

    with pytest.raises(AppRCDirectoryError, match="not a file"):
        write_text_atomic(target, "VALUE=1\n")
