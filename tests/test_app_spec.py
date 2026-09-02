from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import (
    AppConfigSpec,
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.storage import Storage
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import env_field, env_owner


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


def _spec(
    *,
    storage: Storage | None = None,
) -> AppConfigSpec:
    return AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc",
        storage=storage,
    )


def test_app_config_spec_derives_legacy_apprc_toml_filename() -> None:
    derive = AppConfigSpec.derive_legacy_apprc_toml_filename

    assert derive("demo") == "demo.apprc.toml"
    assert derive("my-app.rc") == "my-app_rc.apprc.toml"
    assert derive("") == "app.apprc.toml"
    assert derive("???") == "app.apprc.toml"


def test_app_config_spec_derives_apprc_toml_env_key() -> None:
    assert _spec().apprc_toml_env_key == "DEMO_APPRC_TOML"


def test_app_config_spec_defaults_to_config_without_storage() -> None:
    spec = _spec()

    assert spec.uses_storage() is False
    assert spec.app_env_enabled() is True
    assert spec.named_storage_enabled() is False
    assert spec.storage_selector_env_key is None
    assert spec.app_env_filename == "apprc.app.env"
    assert spec.apprc_toml_filename == "apprc.toml"
    assert spec.storage is None


def test_app_config_spec_storage_derives_selector_env_key() -> None:
    spec = _spec(storage=Storage())

    assert spec.uses_storage() is True
    assert spec.storage_selector_env_key == "DEMO_STORAGE"
    assert spec.named_storage_enabled() is True
    assert spec.require_storage().env_filename == "apprc.storage.env"


def test_app_config_spec_retains_019_read_aliases() -> None:
    """Deprecated readers remain available for the 0.20 migration window."""
    spec = _spec(storage=Storage())

    assert AppConfigSpec.derive_index_filename("demo") == "demo.apprc.toml"
    assert spec.storage_layer == StorageLayerState.REQUIRED
    assert spec.app_wide_layer == CapabilityState.OPTIONAL
    assert spec.named_storage_layer == CapabilityState.OPTIONAL
    assert spec.storage_env_key == spec.storage_selector_env_key
    assert spec.index_env_key == spec.apprc_toml_env_key
    assert spec.storage_required() == spec.uses_storage()
    assert spec.app_wide_allowed() == spec.app_env_enabled()
    assert spec.named_storage_allowed() == spec.named_storage_enabled()


def test_app_config_spec_rejects_storage_key_without_storage() -> None:
    with pytest.raises(ValueError, match="require storage"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            storage_env_key="DEMO_STORAGE",
        )


@pytest.mark.parametrize(
    "legacy_filename",
    ("shared_env_filename", "app_wide_env_filename", "index_filename"),
)
def test_app_config_spec_rejects_empty_legacy_filename_alias(
    legacy_filename: str,
) -> None:
    """Compatibility names preserve the current basename validation."""
    with pytest.raises(ValueError, match="must not be empty"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            **{legacy_filename: ""},  # pyright: ignore[reportArgumentType]
        )


def test_app_config_spec_rejects_named_storage_without_storage() -> None:
    with pytest.raises(ValueError, match="named_storage_layer"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            named_storage_layer=CapabilityState.OPTIONAL,
        )


def test_app_config_spec_apprc_toml_path_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_apprc_toml = tmp_path / "custom" / "demo.apprc.toml"
    spec = _spec()

    monkeypatch.setenv("DEMO_APPRC_TOML", str(custom_apprc_toml))

    assert spec.apprc_toml_path() == custom_apprc_toml


def test_app_config_spec_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            owners=(),  # pyright: ignore[reportCallIssue]
            apprc_toml_filename="demo.apprc.toml",
        )


def test_app_config_spec_rejects_duplicate_owner_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate owner key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            apprc_toml_filename="demo.apprc.toml",
            envs=(_DuplicateOwnerA, _DuplicateOwnerB),
        )


def test_app_config_spec_rejects_duplicate_env_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate env key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc",
            apprc_toml_filename="demo.apprc.toml",
            envs=(_DuplicateEnvA, _DuplicateEnvB),
        )
