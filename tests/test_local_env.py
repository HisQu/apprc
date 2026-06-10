from __future__ import annotations

from pathlib import Path

import pytest

from apprc.config.local_env import (
    clear_local_env_value,
    ensure_local_env_file,
    normalize_env_value,
    read_local_env,
    set_local_env_value,
    write_local_env,
)
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNER,
    APPRC_EXAMPLE_APP_OWNERS,
)


def test_write_local_env_orders_known_keys_before_unknown_keys(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.apprc_example_app"

    write_local_env(
        env_path,
        {
            "Z_USER_EXTRA": "last",
            "APPRC_EXAMPLE_APP_RETRY_COUNT": "7",
            "A_USER_EXTRA": "first",
            "APPRC_EXAMPLE_APP_PROFILE": "local-profile",
        },
        owners=APPRC_EXAMPLE_APP_OWNERS,
    )

    assert env_path.read_text(encoding="utf-8") == (
        'APPRC_EXAMPLE_APP_PROFILE="local-profile"\n'
        'APPRC_EXAMPLE_APP_RETRY_COUNT="7"\n'
        'A_USER_EXTRA="first"\n'
        'Z_USER_EXTRA="last"\n'
    )


def test_ensure_local_env_file_creates_parent_and_file(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"

    path = ensure_local_env_file(
        storage_root, filename=".env.apprc_example_app"
    )

    assert path == storage_root.resolve() / ".env.apprc_example_app"
    assert path.is_file()


def test_set_local_env_value_accepts_env_key_config_path_or_unique_name(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"

    update_by_env = set_local_env_value(
        storage_root=storage_root,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        raw_value="local-profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        local_env_filename=".env.apprc_example_app",
    )
    update_by_path = set_local_env_value(
        storage_root=storage_root,
        reference="app.retry_count",
        raw_value="5",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        local_env_filename=".env.apprc_example_app",
    )
    update_by_name = set_local_env_value(
        storage_root=storage_root,
        reference="enabled",
        raw_value="yes",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        local_env_filename=".env.apprc_example_app",
    )

    assert update_by_env.env_key == "APPRC_EXAMPLE_APP_PROFILE"
    assert update_by_path.value == "5"
    assert update_by_name.value == "true"
    assert read_local_env(storage_root / ".env.apprc_example_app") == {
        "APPRC_EXAMPLE_APP_PROFILE": "local-profile",
        "APPRC_EXAMPLE_APP_ENABLED": "true",
        "APPRC_EXAMPLE_APP_RETRY_COUNT": "5",
    }


def test_set_local_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="managed outside .env.local"):
        set_local_env_value(
            storage_root=tmp_path / "storage",
            reference="APPRC_EXAMPLE_APP_D_STORAGE",
            raw_value="/tmp/storage",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            local_env_filename=".env.apprc_example_app",
        )


def test_clear_local_env_value_removes_existing_override(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    set_local_env_value(
        storage_root=storage_root,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        raw_value="local-profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        local_env_filename=".env.apprc_example_app",
    )

    update = clear_local_env_value(
        storage_root=storage_root,
        reference="app.profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        local_env_filename=".env.apprc_example_app",
    )

    assert update is not None
    assert update.env_key == "APPRC_EXAMPLE_APP_PROFILE"
    assert update.value == ""
    assert read_local_env(storage_root / ".env.apprc_example_app") == {}


def test_clear_local_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="managed outside .env.local"):
        clear_local_env_value(
            storage_root=tmp_path / "storage",
            reference="APPRC_EXAMPLE_APP_D_STORAGE",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            local_env_filename=".env.apprc_example_app",
        )


def test_normalize_env_value_rejects_invalid_choices_and_bool() -> None:
    mode = APPRC_EXAMPLE_APP_OWNER.field("mode")
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")

    with pytest.raises(ValueError, match="mode must be one of"):
        normalize_env_value(mode, "OTHER")
    with pytest.raises(ValueError, match="Boolean values must be"):
        normalize_env_value(enabled, "maybe")
