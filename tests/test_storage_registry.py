from __future__ import annotations

from pathlib import Path

import pytest

from apprc.config.storage_registry import (
    app_config_dir,
    load_storage_registry,
    register_storage,
    set_default_storage,
)
from apprc.config.paths import windows_drive_path_to_posix


def test_app_config_dir_uses_xdg_config_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert app_config_dir("demo") == tmp_path / "xdg" / "demo"


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
