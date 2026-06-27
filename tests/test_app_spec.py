from __future__ import annotations

from pathlib import Path

import pytest

from apprc.runtime_config import EnvConfig, env_field, env_owner
from apprc.runtime_config.app_spec import (
    AppConfigSpec,
    CapabilityState,
    StorageLayerState,
)


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
    storage_layer: StorageLayerState = StorageLayerState.DISABLED,
    app_wide_layer: CapabilityState = CapabilityState.OPTIONAL,
    named_storage_layer: CapabilityState = CapabilityState.DISABLED,
    storage_env_key: str | None = None,
) -> AppConfigSpec:
    return AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package="apprc.runtime_config",
        index_filename="demo.apprc.toml",
        storage_layer=storage_layer,
        app_wide_layer=app_wide_layer,
        named_storage_layer=named_storage_layer,
        storage_env_key=storage_env_key,
    )


def test_app_config_spec_derives_index_filename_text() -> None:
    derive = AppConfigSpec.derive_index_filename

    assert derive("demo") == "demo.apprc.toml"
    assert derive("my-app.rc") == "my-app_rc.apprc.toml"
    assert derive("") == "app.apprc.toml"
    assert derive("???") == "app.apprc.toml"


def test_app_config_spec_derives_index_env_key() -> None:
    assert _spec().index_env_key == "DEMO_APPRC_TOML"


def test_app_config_spec_defaults_to_env_only_capabilities() -> None:
    spec = _spec()

    assert spec.storage_layer == StorageLayerState.DISABLED
    assert spec.app_wide_layer == CapabilityState.OPTIONAL
    assert spec.named_storage_layer == CapabilityState.DISABLED
    assert spec.storage_env_key is None
    assert spec.app_wide_env_filename == ".env.apprc-app"
    assert spec.storage_env_filename == ".env.apprc-storage"


def test_app_config_spec_storage_required_derives_storage_env_key() -> None:
    spec = _spec(
        storage_layer=StorageLayerState.REQUIRED,
        named_storage_layer=CapabilityState.OPTIONAL,
    )

    assert spec.storage_required() is True
    assert spec.storage_env_key == "DEMO_STORAGE"
    assert spec.named_storage_allowed() is True


def test_app_config_spec_rejects_storage_key_without_storage() -> None:
    with pytest.raises(ValueError, match="storage-capable"):
        _spec(storage_env_key="DEMO_STORAGE")


def test_app_config_spec_rejects_named_storage_without_storage() -> None:
    with pytest.raises(ValueError, match="named_storage_layer"):
        _spec(named_storage_layer=CapabilityState.OPTIONAL)


def test_app_config_spec_index_path_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_index = tmp_path / "custom" / "demo.apprc.toml"
    spec = _spec()

    monkeypatch.setenv("DEMO_APPRC_TOML", str(custom_index))

    assert spec.required_index_path() == custom_index


def test_app_config_spec_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            owners=(),  # pyright: ignore[reportCallIssue]
            index_filename="demo.apprc.toml",
        )


def test_app_config_spec_rejects_duplicate_owner_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate owner key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            index_filename="demo.apprc.toml",
            envs=(_DuplicateOwnerA, _DuplicateOwnerB),
        )


def test_app_config_spec_rejects_duplicate_env_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate env key"):
        AppConfigSpec(
            app_name="demo",
            display_name="Demo",
            config_package="apprc.runtime_config",
            index_filename="demo.apprc.toml",
            envs=(_DuplicateEnvA, _DuplicateEnvB),
        )
