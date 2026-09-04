from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
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
        app_id="demo",
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


def test_app_config_spec_derives_apprc_dir_env_key() -> None:
    assert _spec().apprc_dir_env_key == "DEMO_APPRC_DIR"


def test_app_config_spec_defaults_to_config_without_storage() -> None:
    spec = _spec()

    assert spec.uses_storage() is False
    assert spec.storage_selector_env_key is None
    assert spec.user_dotenv_filename == "apprc.user.env"
    assert spec.apprc_toml_filename == "apprc.toml"
    assert spec.storage is None


def test_app_config_spec_storage_derives_selector_env_key() -> None:
    spec = _spec(storage=Storage())

    assert spec.uses_storage() is True
    assert spec.storage_selector_env_key == "DEMO_STORAGE"
    assert spec.storage_dotenv_filename == "apprc.storage.env"


def test_app_config_spec_uses_fixed_filenames() -> None:
    spec = _spec(storage=Storage())

    assert spec.defaults_dotenv_filename == "apprc.defaults.env"
    assert spec.user_dotenv_filename == "apprc.user.env"
    assert spec.storage_dotenv_filename == "apprc.storage.env"
    assert spec.apprc_toml_filename == "apprc.toml"


def test_app_config_spec_rejects_legacy_storage_key_argument() -> None:
    with pytest.raises(TypeError, match="storage_env_key"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            storage_env_key="DEMO_STORAGE",  # pyright: ignore[reportCallIssue]
        )


def test_app_config_spec_apprc_dir_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_apprc_dir = tmp_path / "custom"
    spec = _spec()

    monkeypatch.setenv("DEMO_APPRC_DIR", str(custom_apprc_dir))

    assert spec.apprc_dir() == custom_apprc_dir
    assert spec.preferred_apprc_toml_path() == custom_apprc_dir / "apprc.toml"


def test_app_config_spec_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            owners=(),  # pyright: ignore[reportCallIssue]
        )


def test_app_config_spec_rejects_duplicate_owner_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate owner key"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            envs=(_DuplicateOwnerA, _DuplicateOwnerB),
        )


def test_app_config_spec_rejects_duplicate_env_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate env key"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            envs=(_DuplicateEnvA, _DuplicateEnvB),
        )
