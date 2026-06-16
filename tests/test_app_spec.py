from __future__ import annotations

from pathlib import Path

import pytest

from apprc.config.app_spec import AppConfigSpec
from apprc.config.registry_env import RegistryEnvError


def _app_spec(app_name: str) -> AppConfigSpec:
    """Return the smallest spec needed for literal AppRC TOML naming tests."""
    return AppConfigSpec(
        app_name=app_name,
        display_name="Demo",
        config_package="apprc.config",
        owners=(),
        storage_env_key="DEMO_STORAGE",
        apprc_toml_filename="demo.apprc.toml",
    )


def test_app_config_spec_derives_apprc_toml_filename_text() -> None:
    derive = AppConfigSpec.derive_apprc_toml_filename

    assert derive("demo") == "demo.apprc.toml"
    assert derive("my-app.rc") == "my-app_rc.apprc.toml"
    assert derive("") == "app.apprc.toml"
    assert derive("???") == "app.apprc.toml"


def test_app_config_spec_derives_apprc_toml_env_key() -> None:
    assert _app_spec("demo").apprc_toml_env_key == "DEMO_APPRC_TOML"
    assert _app_spec("my-app.rc").apprc_toml_env_key == "MY_APP_RC_APPRC_TOML"


def test_app_config_spec_required_apprc_toml_path_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_registry = tmp_path / "custom" / "demo.apprc.toml"
    spec = _app_spec("demo")

    with pytest.raises(RegistryEnvError, match="DEMO_APPRC_TOML"):
        spec.required_apprc_toml_path()

    monkeypatch.setenv("DEMO_APPRC_TOML", str(custom_registry))

    assert spec.required_apprc_toml_path() == custom_registry
