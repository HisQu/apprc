from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.storage import Storage
from apprc.user_files.app_home.locations import (
    ConfigHomeError,
    app_config_file,
    write_text_atomic,
)


def test_app_config_file_rejects_path_like_filename() -> None:
    invalid_names = ["", ".", "..", "../escape.toml", "nested/app.toml"]

    for filename in invalid_names:
        with pytest.raises(ConfigHomeError, match="filename"):
            app_config_file("demo", filename)


def test_app_config_file_rejects_windows_path_like_filename() -> None:
    for filename in ("nested\\app.toml", "C:app.toml", "C:\\app.toml"):
        with pytest.raises(ConfigHomeError, match="filename"):
            app_config_file("demo", filename)


@pytest.mark.parametrize(
    ("field_name", "error_name"),
    [
        ("apprc_toml_filename", "apprc_toml_filename"),
        ("defaults_env_filename", "defaults_env_filename"),
        ("app_env_filename", "app_env_filename"),
        ("storage_env_filename", "storage.env_filename"),
    ],
)
def test_app_config_spec_rejects_path_like_filenames(
    field_name: str,
    error_name: str,
) -> None:
    kwargs: dict[str, object] = {
        "apprc_toml_filename": "apprc.toml",
        "defaults_env_filename": "apprc.defaults.env",
        "app_env_filename": "apprc.app.env",
    }
    if field_name == "storage_env_filename":
        kwargs["storage"] = Storage(env_filename="../escape")
    else:
        kwargs[field_name] = "../escape"

    with pytest.raises(ConfigHomeError, match=error_name):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            **kwargs,  # type: ignore[arg-type]
        )


def test_ensure_app_env_rejects_config_home_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_home = tmp_path / "config" / "demo"
    config_home.parent.mkdir(parents=True)
    config_home.write_text("not a directory", encoding="utf-8")

    spec = AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc",
        apprc_toml_filename="demo.apprc.toml",
    )

    with pytest.raises(ConfigHomeError, match="parent exists"):
        spec.ensure_app_env()


def test_ensure_app_env_rejects_app_env_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_home = tmp_path / "config" / "demo"
    (config_home / "apprc.app.env").mkdir(parents=True)
    spec = AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc",
        apprc_toml_filename="demo.apprc.toml",
    )

    with pytest.raises(ConfigHomeError, match="not a file"):
        spec.ensure_app_env()


def test_ensure_apprc_toml_rejects_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_home = tmp_path / "config" / "demo"
    (config_home / "apprc.toml").mkdir(parents=True)
    spec = AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc",
    )

    with pytest.raises(ConfigHomeError, match="not a file"):
        spec.ensure_apprc_toml()


def test_write_text_atomic_rejects_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.mkdir()

    with pytest.raises(ConfigHomeError, match="not a file"):
        write_text_atomic(target, "VALUE=1\n")
