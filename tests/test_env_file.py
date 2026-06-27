from __future__ import annotations

from pathlib import Path

import pytest

from apprc.runtime_config.env_file import (
    clear_env_file_value,
    clear_storage_env_value,
    ensure_storage_env_file,
    normalize_env_value,
    read_env_file,
    set_storage_env_value,
    write_env_file,
)
from apprc.runtime_config.storage.paths import StorageRootPathError
from apprc.runtime_config.contract.schema import ConfigField
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNER,
    APPRC_EXAMPLE_APP_OWNERS,
)


def test_write_env_file_orders_known_keys_before_unknown_keys(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.apprc_example_app"

    write_env_file(
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


def test_ensure_storage_env_file_creates_file_in_existing_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    path = ensure_storage_env_file(
        storage_root, filename=".env.apprc_example_app"
    )

    assert path == storage_root.resolve() / ".env.apprc_example_app"
    assert path.is_file()


def test_ensure_storage_env_file_rejects_missing_root(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"

    with pytest.raises(StorageRootPathError, match="does not exist"):
        ensure_storage_env_file(
            storage_root,
            filename=".env.apprc_example_app",
        )


def test_set_storage_env_value_accepts_env_key_config_path_or_unique_name(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    update_by_env = set_storage_env_value(
        storage_root=storage_root,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        raw_value="local-profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_filename=".env.apprc_example_app",
    )
    update_by_path = set_storage_env_value(
        storage_root=storage_root,
        reference="app.retry_count",
        raw_value="5",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_filename=".env.apprc_example_app",
    )
    update_by_name = set_storage_env_value(
        storage_root=storage_root,
        reference="enabled",
        raw_value="yes",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_filename=".env.apprc_example_app",
    )

    assert update_by_env.env_key == "APPRC_EXAMPLE_APP_PROFILE"
    assert update_by_path.value == "5"
    assert update_by_name.value == "true"
    assert read_env_file(storage_root / ".env.apprc_example_app") == {
        "APPRC_EXAMPLE_APP_PROFILE": "local-profile",
        "APPRC_EXAMPLE_APP_ENABLED": "true",
        "APPRC_EXAMPLE_APP_RETRY_COUNT": "5",
    }


def test_set_storage_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    with pytest.raises(
        ValueError,
        match=r"managed outside \.env\.apprc_example_app",
    ):
        set_storage_env_value(
            storage_root=storage_root,
            reference="APPRC_EXAMPLE_APP_STORAGE",
            raw_value="/tmp/storage",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            storage_env_filename=".env.apprc_example_app",
        )


def test_set_storage_env_value_rejects_missing_storage_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"

    with pytest.raises(StorageRootPathError, match="does not exist"):
        set_storage_env_value(
            storage_root=storage_root,
            reference="APPRC_EXAMPLE_APP_PROFILE",
            raw_value="local-profile",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            storage_env_filename=".env.apprc_example_app",
        )

    assert not storage_root.exists()


def test_clear_storage_env_value_removes_existing_override(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    set_storage_env_value(
        storage_root=storage_root,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        raw_value="local-profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_filename=".env.apprc_example_app",
    )

    update = clear_storage_env_value(
        storage_root=storage_root,
        reference="app.profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        storage_env_filename=".env.apprc_example_app",
    )

    assert update is not None
    assert update.env_key == "APPRC_EXAMPLE_APP_PROFILE"
    assert update.value == ""
    assert read_env_file(storage_root / ".env.apprc_example_app") == {}


def test_clear_storage_env_value_rejects_registry_owned_storage_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    with pytest.raises(
        ValueError,
        match=r"managed outside \.env\.apprc_example_app",
    ):
        clear_storage_env_value(
            storage_root=storage_root,
            reference="APPRC_EXAMPLE_APP_STORAGE",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            storage_env_filename=".env.apprc_example_app",
        )


def test_clear_storage_env_value_rejects_missing_storage_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"

    with pytest.raises(StorageRootPathError, match="does not exist"):
        clear_storage_env_value(
            storage_root=storage_root,
            reference="APPRC_EXAMPLE_APP_PROFILE",
            owners=APPRC_EXAMPLE_APP_OWNERS,
            storage_env_filename=".env.apprc_example_app",
        )

    assert not storage_root.exists()


def test_clear_env_file_value_missing_file_is_zero_write(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.apprc_example_app"

    update = clear_env_file_value(
        path=env_path,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name=".env.apprc_example_app",
    )

    assert update is None
    assert not env_path.exists()


def test_clear_env_file_value_absent_key_preserves_existing_file(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.apprc_example_app"
    env_path.write_text('OTHER="value"\n', encoding="utf-8")

    update = clear_env_file_value(
        path=env_path,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name=".env.apprc_example_app",
    )

    assert update is None
    assert env_path.read_text(encoding="utf-8") == 'OTHER="value"\n'


def test_normalize_env_value_rejects_invalid_choices_and_bool() -> None:
    mode = APPRC_EXAMPLE_APP_OWNER.field("mode")
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")

    with pytest.raises(ValueError, match="mode must be one of"):
        normalize_env_value(mode, "OTHER")
    with pytest.raises(ValueError, match="converting"):
        normalize_env_value(enabled, "maybe")


def test_normalize_env_value_uses_runtime_converter_for_float() -> None:
    ratio = ConfigField("ratio", "RATIO", float, default=0.5)

    assert normalize_env_value(ratio, "1") == "1.0"

    with pytest.raises(ValueError, match="converting"):
        normalize_env_value(ratio, "nope")
