from __future__ import annotations

from pathlib import Path

import pytest

from apprc.config.local_env import (
    normalize_env_value,
    read_local_env,
    set_local_env_value,
    write_local_env,
)
from tests.support_config import DEMO_OWNER, DEMO_OWNERS


def test_write_local_env_orders_known_keys_before_unknown_keys(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.demo"

    write_local_env(
        env_path,
        {
            "Z_USER_EXTRA": "last",
            "DEMO_RETRY_COUNT": "7",
            "A_USER_EXTRA": "first",
            "DEMO_MODEL": "local-model",
        },
        owners=DEMO_OWNERS,
    )

    assert env_path.read_text(encoding="utf-8") == (
        'DEMO_MODEL="local-model"\n'
        'DEMO_RETRY_COUNT="7"\n'
        'A_USER_EXTRA="first"\n'
        'Z_USER_EXTRA="last"\n'
    )


def test_set_local_env_value_accepts_env_key_config_path_or_unique_name(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"

    update_by_env = set_local_env_value(
        storage_root=storage_root,
        reference="DEMO_MODEL",
        raw_value="env-model",
        owners=DEMO_OWNERS,
        local_env_filename=".env.demo",
    )
    update_by_path = set_local_env_value(
        storage_root=storage_root,
        reference="runtime.retry_count",
        raw_value="5",
        owners=DEMO_OWNERS,
        local_env_filename=".env.demo",
    )
    update_by_name = set_local_env_value(
        storage_root=storage_root,
        reference="enabled",
        raw_value="yes",
        owners=DEMO_OWNERS,
        local_env_filename=".env.demo",
    )

    assert update_by_env.env_key == "DEMO_MODEL"
    assert update_by_path.value == "5"
    assert update_by_name.value == "true"
    assert read_local_env(storage_root / ".env.demo") == {
        "DEMO_MODEL": "env-model",
        "DEMO_ENABLED": "true",
        "DEMO_RETRY_COUNT": "5",
    }


def test_set_local_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="managed outside .env.local"):
        set_local_env_value(
            storage_root=tmp_path / "storage",
            reference="DEMO_D_STORAGE",
            raw_value="/tmp/storage",
            owners=DEMO_OWNERS,
            local_env_filename=".env.demo",
        )


def test_normalize_env_value_rejects_invalid_choices_and_bool() -> None:
    strategy = DEMO_OWNER.field("strategy")
    enabled = DEMO_OWNER.field("enabled")

    with pytest.raises(ValueError, match="strategy must be one of"):
        normalize_env_value(strategy, "OTHER")
    with pytest.raises(ValueError, match="Boolean values must be"):
        normalize_env_value(enabled, "maybe")
