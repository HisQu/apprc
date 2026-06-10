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
from tests.support_config import EXAMPLE_OWNER, EXAMPLE_OWNERS


def test_write_local_env_orders_known_keys_before_unknown_keys(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.example"

    write_local_env(
        env_path,
        {
            "Z_USER_EXTRA": "last",
            "EXAMPLE_RETRY_COUNT": "7",
            "A_USER_EXTRA": "first",
            "EXAMPLE_PROFILE": "local-profile",
        },
        owners=EXAMPLE_OWNERS,
    )

    assert env_path.read_text(encoding="utf-8") == (
        'EXAMPLE_PROFILE="local-profile"\n'
        'EXAMPLE_RETRY_COUNT="7"\n'
        'A_USER_EXTRA="first"\n'
        'Z_USER_EXTRA="last"\n'
    )


def test_ensure_local_env_file_creates_parent_and_file(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"

    path = ensure_local_env_file(storage_root, filename=".env.example")

    assert path == storage_root.resolve() / ".env.example"
    assert path.is_file()


def test_set_local_env_value_accepts_env_key_config_path_or_unique_name(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"

    update_by_env = set_local_env_value(
        storage_root=storage_root,
        reference="EXAMPLE_PROFILE",
        raw_value="local-profile",
        owners=EXAMPLE_OWNERS,
        local_env_filename=".env.example",
    )
    update_by_path = set_local_env_value(
        storage_root=storage_root,
        reference="app.retry_count",
        raw_value="5",
        owners=EXAMPLE_OWNERS,
        local_env_filename=".env.example",
    )
    update_by_name = set_local_env_value(
        storage_root=storage_root,
        reference="enabled",
        raw_value="yes",
        owners=EXAMPLE_OWNERS,
        local_env_filename=".env.example",
    )

    assert update_by_env.env_key == "EXAMPLE_PROFILE"
    assert update_by_path.value == "5"
    assert update_by_name.value == "true"
    assert read_local_env(storage_root / ".env.example") == {
        "EXAMPLE_PROFILE": "local-profile",
        "EXAMPLE_ENABLED": "true",
        "EXAMPLE_RETRY_COUNT": "5",
    }


def test_set_local_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="managed outside .env.local"):
        set_local_env_value(
            storage_root=tmp_path / "storage",
            reference="EXAMPLE_D_STORAGE",
            raw_value="/tmp/storage",
            owners=EXAMPLE_OWNERS,
            local_env_filename=".env.example",
        )


def test_clear_local_env_value_removes_existing_override(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    set_local_env_value(
        storage_root=storage_root,
        reference="EXAMPLE_PROFILE",
        raw_value="local-profile",
        owners=EXAMPLE_OWNERS,
        local_env_filename=".env.example",
    )

    update = clear_local_env_value(
        storage_root=storage_root,
        reference="app.profile",
        owners=EXAMPLE_OWNERS,
        local_env_filename=".env.example",
    )

    assert update is not None
    assert update.env_key == "EXAMPLE_PROFILE"
    assert update.value == ""
    assert read_local_env(storage_root / ".env.example") == {}


def test_clear_local_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="managed outside .env.local"):
        clear_local_env_value(
            storage_root=tmp_path / "storage",
            reference="EXAMPLE_D_STORAGE",
            owners=EXAMPLE_OWNERS,
            local_env_filename=".env.example",
        )


def test_normalize_env_value_rejects_invalid_choices_and_bool() -> None:
    mode = EXAMPLE_OWNER.field("mode")
    enabled = EXAMPLE_OWNER.field("enabled")

    with pytest.raises(ValueError, match="mode must be one of"):
        normalize_env_value(mode, "OTHER")
    with pytest.raises(ValueError, match="Boolean values must be"):
        normalize_env_value(enabled, "maybe")
