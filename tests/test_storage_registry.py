from __future__ import annotations

from pathlib import Path

import pytest

from apprc.config.storage_registry import (
    app_config_dir,
    app_data_dir,
    config_file_env_key,
    configured_storage_registry_path,
    default_storage_data_root,
    load_storage_registry,
    prune_missing_archived_storages,
    record_archived_storage,
    register_storage,
    remove_archived_storage,
    replace_default_storage,
    set_default_storage,
    unregister_storage,
)
from apprc.config.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
    windows_drive_path_to_posix,
)


def test_app_config_dir_uses_xdg_config_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert app_config_dir("demo") == tmp_path / "xdg" / "demo"


def test_app_data_dir_uses_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert app_data_dir("demo") == tmp_path / "data" / "demo"
    assert (
        default_storage_data_root("demo")
        == tmp_path / "data" / "demo" / "default"
    )


def test_config_file_env_key_normalizes_app_name() -> None:
    assert config_file_env_key("demo") == "DEMO_CONFIG_FILE"
    assert config_file_env_key("my-app.rc") == "MY_APP_RC_CONFIG_FILE"


def test_configured_storage_registry_path_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    custom_registry = tmp_path / "custom" / "demo.toml"

    assert configured_storage_registry_path(
        app_name="demo",
        registry_filename="demo.toml",
    ) == (tmp_path / "config" / "demo" / "demo.toml")

    monkeypatch.setenv("DEMO_CONFIG_FILE", str(custom_registry))

    assert (
        configured_storage_registry_path(
            app_name="demo",
            registry_filename="demo.toml",
        )
        == custom_registry
    )


def test_register_storage_writes_sorted_toml_and_local_env(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "config" / "demo.toml"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    register_storage(
        name="zeta",
        root=second_root,
        make_default=True,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    registry = register_storage(
        name="alpha",
        root=first_root,
        make_default=False,
        path=registry_path,
        local_env_filename=".env.demo",
    )

    assert registry.default_storage == "zeta"
    assert (first_root / ".env.demo").is_file()
    assert registry_path.read_text(encoding="utf-8") == (
        'default_storage = "zeta"\n'
        "\n"
        "[storages.alpha]\n"
        f'root = "{first_root.resolve()}"\n'
        "\n"
        "[storages.zeta]\n"
        f'root = "{second_root.resolve()}"\n'
    )


def test_load_storage_registry_keeps_old_toml_compatible(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "demo.toml"
    registry_path.write_text(
        'default_storage = "alpha"\n'
        "\n"
        "[storages.alpha]\n"
        f'root = "{tmp_path / "alpha"}"\n',
        encoding="utf-8",
    )

    registry = load_storage_registry(registry_path)

    assert registry.default_storage == "alpha"
    assert sorted(registry.storages) == ["alpha"]
    assert registry.archived_storages == {}


def test_archived_storage_records_round_trip_sorted_toml(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "demo.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
        path=registry_path,
        local_env_filename=".env.demo",
    )

    registry = record_archived_storage(
        name="zeta",
        archive=tmp_path / "zeta.apprc.tar.xz",
        source_root=tmp_path / "zeta",
        path=registry_path,
    )

    assert registry.archived_storages["zeta"].archive == (
        tmp_path / "zeta.apprc.tar.xz"
    )
    assert load_storage_registry(registry_path).archived_storages[
        "zeta"
    ].source_root == (tmp_path / "zeta")
    assert "[archived_storages.zeta]" in registry_path.read_text(
        encoding="utf-8"
    )


def test_remove_and_prune_archived_storage_records(tmp_path: Path) -> None:
    registry_path = tmp_path / "demo.toml"
    existing_archive = tmp_path / "alpha.apprc.tar.xz"
    existing_archive.write_bytes(b"placeholder")
    record_archived_storage(
        name="alpha",
        archive=existing_archive,
        source_root=tmp_path / "alpha",
        path=registry_path,
    )
    record_archived_storage(
        name="beta",
        archive=tmp_path / "missing.apprc.tar.xz",
        source_root=tmp_path / "beta",
        path=registry_path,
    )

    registry = prune_missing_archived_storages(path=registry_path)
    registry = remove_archived_storage(name="alpha", path=registry_path)

    assert sorted(registry.archived_storages) == []
    assert "beta" not in load_storage_registry(registry_path).archived_storages


def test_unregister_storage_repairs_or_clears_default(tmp_path: Path) -> None:
    registry_path = tmp_path / "demo.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
        path=registry_path,
    )
    register_storage(
        name="beta",
        root=tmp_path / "beta",
        make_default=False,
        path=registry_path,
    )

    registry = unregister_storage(
        name="alpha",
        replacement_default="beta",
        path=registry_path,
    )
    registry = unregister_storage(name="beta", path=registry_path)

    assert registry.default_storage is None
    assert registry.storages == {}


def test_replace_default_storage_can_clear_default(tmp_path: Path) -> None:
    registry_path = tmp_path / "demo.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
        path=registry_path,
    )

    registry = replace_default_storage(name=None, path=registry_path)

    assert registry.default_storage is None


def test_register_storage_normalizes_windows_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "config" / "demo.toml"
    normalized_root = tmp_path / "demo-storage"

    monkeypatch.setattr(
        "apprc.config.storage_registry.normalize_storage_root_path",
        lambda path: normalized_root,
    )

    registry = register_storage(
        name="demo",
        root=Path(r"D:\Training\demo-project"),
        make_default=True,
        path=registry_path,
        local_env_filename=".env.demo",
    )

    assert registry.selected("demo").root == normalized_root.resolve()
    assert (normalized_root / ".env.demo").is_file()


def test_windows_drive_path_to_posix_falls_back_to_mnt_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda command: None)

    assert windows_drive_path_to_posix(r"D:\Training\demo-project") == Path(
        "/mnt/d/Training/demo-project"
    )


def test_normalize_storage_root_path_accepts_windows_drive_spellings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda command: None)

    assert normalize_storage_root_path(r"C:\Projects\demo-storage") == Path(
        "/mnt/c/Projects/demo-storage"
    )
    assert normalize_storage_root_path("C:/Projects/demo-storage") == Path(
        "/mnt/c/Projects/demo-storage"
    )


def test_normalize_storage_root_path_rejects_damaged_windows_path() -> None:
    with pytest.raises(StorageRootPathError) as exc_info:
        normalize_storage_root_path("C:Projectsdemo-storage")

    message = str(exc_info.value)
    assert "unquoted backslashes are consumed" in message
    assert "`C:/Projects/demo-storage`" in message
    assert "`/mnt/c/Projects/demo-storage`" in message
    assert normalize_storage_root_path("./C:Projectsdemo-storage") == Path(
        "C:Projectsdemo-storage"
    )


def test_set_default_storage_requires_existing_name(tmp_path: Path) -> None:
    registry_path = tmp_path / "demo.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "storage",
        make_default=True,
        path=registry_path,
    )

    with pytest.raises(ValueError, match="Unknown storage 'beta'"):
        set_default_storage(name="beta", path=registry_path)


def test_load_storage_registry_rejects_invalid_default(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "demo.toml"
    registry_path.write_text('default_storage = "missing"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="default_storage 'missing'"):
        load_storage_registry(registry_path)


def test_register_storage_rejects_names_that_cannot_be_toml_keys(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Storage names may contain only"):
        register_storage(
            name="not valid",
            root=tmp_path / "storage",
            make_default=True,
            path=tmp_path / "demo.toml",
        )
