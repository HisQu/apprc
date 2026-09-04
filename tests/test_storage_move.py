from __future__ import annotations

from pathlib import Path
import json

import pytest

from apprc.user_files.storage_roots.move import StorageMoveError, move_storage
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
    register_storage,
)


def test_move_resolves_relative_destination_from_apprc_toml(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "apprc" / "apprc.toml"
    source = tmp_path / "source"
    register_storage(name="alpha", root=source, path=registry_path)
    (source / "payload.txt").write_text("keep", encoding="utf-8")

    result = move_storage(
        name="alpha",
        destination=Path("moved"),
        path=registry_path,
    )

    destination = registry_path.parent / "moved"
    assert result.destination == destination
    assert not source.exists()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "keep"
    registry = load_storage_registry_or_empty(registry_path)
    assert registry.selected("alpha").root == destination


def test_move_rejects_root_shared_by_another_storage(tmp_path: Path) -> None:
    registry_path = tmp_path / "apprc.toml"
    source = tmp_path / "source"
    source.mkdir()
    (source / "apprc.storage.env").write_text("", encoding="utf-8")
    registry_path.write_text(
        'selected_storage = "alpha"\n\n'
        f"[storages.alpha]\nroot = {json.dumps(str(source))}\n\n"
        f"[storages.beta]\nroot = {json.dumps(str(source))}\n",
        encoding="utf-8",
    )

    with pytest.raises(StorageMoveError, match="also registered"):
        move_storage(
            name="alpha",
            destination=tmp_path / "destination",
            path=registry_path,
        )


def test_move_restores_source_and_empty_destination_when_registry_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "apprc.toml"
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    register_storage(name="alpha", root=source, path=registry_path)
    (source / "payload.txt").write_text("keep", encoding="utf-8")
    destination.mkdir()

    def fail_repoint(**_kwargs: object) -> None:
        raise OSError("registry unavailable")

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.move.repoint_storage",
        fail_repoint,
    )

    with pytest.raises(StorageMoveError, match="registry unavailable"):
        move_storage(
            name="alpha",
            destination=destination,
            path=registry_path,
        )

    assert (source / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination.is_dir()
    assert not list(destination.iterdir())
    registry = load_storage_registry_or_empty(registry_path)
    assert registry.selected("alpha").root == source


def test_move_rejects_symlink_storage_root(tmp_path: Path) -> None:
    registry_path = tmp_path / "apprc.toml"
    real_root = tmp_path / "real"
    real_root.mkdir()
    symlink_root = tmp_path / "linked"
    symlink_root.symlink_to(real_root, target_is_directory=True)
    register_storage(name="alpha", root=symlink_root, path=registry_path)

    with pytest.raises(StorageMoveError, match="symbolic links"):
        move_storage(
            name="alpha",
            destination=tmp_path / "destination",
            path=registry_path,
        )

    assert symlink_root.is_symlink()
    assert real_root.is_dir()
