from __future__ import annotations

from pathlib import Path

import pytest

from apprc.runtime_config.app_spec import AppConfigSpec, StorageMode
from apprc.runtime_config import EnvConfig, env_field, env_owner


@env_owner(
    key="dup.owner",
    title="Duplicate Owner A",
    env_prefix="DUP_A_",
    rc_path=("dup", "owner_a"),
    log_lifecycle=False,
)
class _DuplicateOwnerA(EnvConfig):
    value: str = env_field("VALUE", default="a")


@env_owner(
    key="dup.owner",
    title="Duplicate Owner B",
    env_prefix="DUP_B_",
    rc_path=("dup", "owner_b"),
    log_lifecycle=False,
)
class _DuplicateOwnerB(EnvConfig):
    value: str = env_field("VALUE", default="b")


@env_owner(
    key="dup.env_a",
    title="Duplicate Env A",
    env_prefix="DUP_ENV_",
    rc_path=("dup", "env_a"),
    log_lifecycle=False,
)
class _DuplicateEnvA(EnvConfig):
    value: str = env_field("VALUE", default="a")


@env_owner(
    key="dup.env_b",
    title="Duplicate Env B",
    env_prefix="DUP_ENV_",
    rc_path=("dup", "env_b"),
    log_lifecycle=False,
)
class _DuplicateEnvB(EnvConfig):
    value: str = env_field("VALUE", default="b")


@env_owner(
    key="dup.path_a",
    title="Duplicate Path A",
    env_prefix="DUP_PATH_A_",
    rc_path=("dup", "path"),
    log_lifecycle=False,
)
class _DuplicatePathA(EnvConfig):
    value: str = env_field("VALUE_A", default="a")


@env_owner(
    key="dup.path_b",
    title="Duplicate Path B",
    env_prefix="DUP_PATH_B_",
    rc_path=("dup", "path"),
    log_lifecycle=False,
)
class _DuplicatePathB(EnvConfig):
    value: str = env_field("VALUE_B", default="b")


def _app_spec(app_name: str) -> AppConfigSpec:
    """Return the smallest spec needed for literal AppRC TOML naming tests."""
    return AppConfigSpec(
        app_name=app_name,
        display_name="Demo",
        config_package="apprc.runtime_config",
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


def test_app_config_spec_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            owners=(),  # pyright: ignore[reportCallIssue]
            storage_env_key="DEMO_STORAGE",
            apprc_toml_filename="demo.apprc.toml",
        )


def test_app_config_spec_rejects_duplicate_owner_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate owner key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            storage_env_key="DEMO_STORAGE",
            apprc_toml_filename="demo.apprc.toml",
            envs=(_DuplicateOwnerA, _DuplicateOwnerB),
        )


def test_app_config_spec_rejects_duplicate_env_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate env key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            storage_env_key="DEMO_STORAGE",
            apprc_toml_filename="demo.apprc.toml",
            envs=(_DuplicateEnvA, _DuplicateEnvB),
        )


def test_app_config_spec_rejects_duplicate_config_paths() -> None:
    with pytest.raises(ValueError, match="Duplicate config path"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            storage_env_key="DEMO_STORAGE",
            apprc_toml_filename="demo.apprc.toml",
            envs=(_DuplicatePathA, _DuplicatePathB),
        )


def test_app_config_spec_required_apprc_toml_path_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_registry = tmp_path / "custom" / "demo.apprc.toml"
    spec = _app_spec("demo")

    assert spec.required_apprc_toml_path() == (
        tmp_path / "config-home" / "demo" / "demo.apprc.toml"
    )

    monkeypatch.setenv("DEMO_APPRC_TOML", str(custom_registry))

    assert spec.required_apprc_toml_path() == custom_registry


def test_app_config_spec_defaults_to_storage_disabled() -> None:
    spec = AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc.runtime_config",
        apprc_toml_filename="demo.apprc.toml",
    )

    assert spec.storage_mode == StorageMode.DISABLED
    assert spec.storage_env_key is None


def test_app_config_spec_inferrs_required_storage_from_legacy_key() -> None:
    spec = _app_spec("demo")

    assert spec.storage_mode == StorageMode.REQUIRED
    assert spec.storage_env_key == "DEMO_STORAGE"
