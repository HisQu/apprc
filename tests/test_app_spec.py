from __future__ import annotations

from pathlib import Path

import pytest

import apprc as rc
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.storage import Storage
from apprc.definition.app_config.user_dotenv import UserDotenv


_DUPLICATE_OWNER_A_RC = rc.AppRC(
    app_id="duplicate_owner_a",
    display_name="Duplicate Owner A",
    config_package="duplicate_owner_a.config",
)


@_DUPLICATE_OWNER_A_RC.config(
    "dup.owner",
    title="Duplicate Owner A",
    prefix="DUP_A_",
    rc_path=("dup", "owner_a"),
)
class _DuplicateOwnerA(rc.Config):
    value: str = rc.field("DUP_A_VALUE", default="a")


_DUPLICATE_OWNER_B_RC = rc.AppRC(
    app_id="duplicate_owner_b",
    display_name="Duplicate Owner B",
    config_package="duplicate_owner_b.config",
)


@_DUPLICATE_OWNER_B_RC.config(
    "dup.owner",
    title="Duplicate Owner B",
    prefix="DUP_B_",
    rc_path=("dup", "owner_b"),
)
class _DuplicateOwnerB(rc.Config):
    value: str = rc.field("DUP_B_VALUE", default="b")


_DUPLICATE_ENV_A_RC = rc.AppRC(
    app_id="duplicate_env_a",
    display_name="Duplicate Env A",
    config_package="duplicate_env_a.config",
)


@_DUPLICATE_ENV_A_RC.config(
    "dup.env_a",
    title="Duplicate Env A",
    prefix="DUP_ENV_",
    rc_path=("dup", "env_a"),
)
class _DuplicateEnvA(rc.Config):
    value: str = rc.field("DUP_ENV_VALUE", default="a")


_DUPLICATE_ENV_B_RC = rc.AppRC(
    app_id="duplicate_env_b",
    display_name="Duplicate Env B",
    config_package="duplicate_env_b.config",
)


@_DUPLICATE_ENV_B_RC.config(
    "dup.env_b",
    title="Duplicate Env B",
    prefix="DUP_ENV_",
    rc_path=("dup", "env_b"),
)
class _DuplicateEnvB(rc.Config):
    value: str = rc.field("DUP_ENV_VALUE", default="b")


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
    assert spec.uses_user_dotenv() is False
    assert spec.uses_managed_files() is False


@pytest.mark.parametrize(
    ("user_dotenv", "storage", "uses_managed_files"),
    (
        (None, None, False),
        (UserDotenv(), None, True),
        (None, Storage(), True),
        (UserDotenv(), Storage(), True),
    ),
)
def test_app_config_spec_treats_persistent_capabilities_independently(
    user_dotenv: UserDotenv | None,
    storage: Storage | None,
    *,
    uses_managed_files: bool,
) -> None:
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        user_dotenv=user_dotenv,
        storage=storage,
    )

    assert spec.uses_user_dotenv() is (user_dotenv is not None)
    assert spec.uses_storage() is (storage is not None)
    assert spec.uses_managed_files() is uses_managed_files


def test_app_config_spec_rejects_directory_for_process_env_only_app(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="apprc_dir requires"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            config_package="apprc",
            apprc_dir=tmp_path,
        )


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
