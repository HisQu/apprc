from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import apprc as rc
from apprc.user_files.workspace_roots import move as workspace_move
from apprc.user_files.workspace_roots.move import (
    WorkspaceMoveError,
    move_workspace,
)
from apprc.user_files.workspace_roots.registry import (
    load_workspace_registry_or_empty,
    register_workspace,
    repoint_workspace,
)


def test_move_resolves_relative_destination_from_registry_path(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "apprc" / "apprc.toml"
    source = tmp_path / "source"
    register_workspace(name="alpha", root=source, path=registry_path)
    (source / "payload.txt").write_text("keep", encoding="utf-8")

    result = move_workspace(
        name="alpha",
        destination=Path("moved"),
        path=registry_path,
    )

    destination = registry_path.parent / "moved"
    assert result.destination == destination
    assert not source.exists()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "keep"
    registry = load_workspace_registry_or_empty(registry_path)
    assert registry.workspaces["alpha"].root == destination


def test_move_restores_source_and_empty_destination_when_registry_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "apprc.toml"
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    register_workspace(name="alpha", root=source, path=registry_path)
    (source / "payload.txt").write_text("keep", encoding="utf-8")
    destination.mkdir()

    def fail_repoint(**_kwargs: object) -> None:
        raise OSError("registry unavailable")

    monkeypatch.setattr(
        "apprc.user_files.workspace_roots.move.repoint_workspace",
        fail_repoint,
    )

    with pytest.raises(WorkspaceMoveError, match="registry unavailable"):
        move_workspace(
            name="alpha",
            destination=destination,
            path=registry_path,
        )

    assert (source / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination.is_dir()
    assert not list(destination.iterdir())
    registry = load_workspace_registry_or_empty(registry_path)
    assert registry.workspaces["alpha"].root == source


def _use_copy_path(monkeypatch: pytest.MonkeyPatch, parent: Path) -> None:
    """Make the destination parent report a different filesystem device."""
    real_stat = Path.stat

    def parent_stat(
        path: Path, *, follow_symlinks: bool = True
    ) -> os.stat_result:
        result = real_stat(path, follow_symlinks=follow_symlinks)
        if path == parent and follow_symlinks:
            return os.stat_result(
                (result.st_mode, result.st_ino, result.st_dev + 1, *result[3:])
            )
        return result

    monkeypatch.setattr(Path, "stat", parent_stat)


@pytest.mark.parametrize(
    "has_foreign_file", [False, True], ids=["empty", "populated"]
)
def test_copy_rollback_keeps_destination_created_during_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, has_foreign_file: bool
) -> None:
    registry_path = tmp_path / "apprc.toml"
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    register_workspace(name="alpha", root=source, path=registry_path)
    (source / "payload").write_text("original", encoding="utf-8")
    _use_copy_path(monkeypatch, tmp_path)

    def copy_while_destination_appears(
        _source: Path, staging: Path, **_kwargs: object
    ) -> None:
        (staging / "payload").write_text("original", encoding="utf-8")
        destination.mkdir()
        if has_foreign_file:
            (destination / "foreign").write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        workspace_move.shutil, "copytree", copy_while_destination_appears
    )

    with pytest.raises(WorkspaceMoveError):
        move_workspace(
            name="alpha", destination=destination, path=registry_path
        )

    assert destination.is_dir()
    if has_foreign_file:
        assert (destination / "foreign").read_text(encoding="utf-8") == "keep"
    else:
        assert not list(destination.iterdir())
    assert (source / "payload").is_file()
    registry = load_workspace_registry_or_empty(registry_path)
    assert registry.selected("alpha").root == source
    assert not list(tmp_path.glob(".destination.apprc-moving-*"))


@pytest.mark.parametrize("use_copy", [False, True], ids=["rename", "copy"])
def test_move_rollback_keeps_destination_replaced_after_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, use_copy: bool
) -> None:
    registry_path = tmp_path / "apprc.toml"
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    published_root = tmp_path / "published-root"
    register_workspace(name="alpha", root=source, path=registry_path)
    (source / "payload").write_text("original", encoding="utf-8")
    destination.mkdir()
    if use_copy:
        _use_copy_path(monkeypatch, tmp_path)

    def replace_and_fail_repoint(**_kwargs: object) -> None:
        destination.rename(published_root)
        destination.mkdir()
        (destination / "foreign").write_text("keep", encoding="utf-8")
        raise OSError("registry unavailable")

    monkeypatch.setattr(
        workspace_move, "repoint_workspace", replace_and_fail_repoint
    )

    with pytest.raises(WorkspaceMoveError, match="registry unavailable"):
        move_workspace(
            name="alpha", destination=destination, path=registry_path
        )

    assert (destination / "foreign").read_text(encoding="utf-8") == "keep"
    assert (published_root / "payload").read_text(
        encoding="utf-8"
    ) == "original"
    assert (source / "payload").is_file() == use_copy
    registry = load_workspace_registry_or_empty(registry_path)
    assert registry.selected("alpha").root == source
    backups = list(tmp_path.glob(".destination.apprc-empty-*"))
    assert len(backups) == 1
    assert not list(backups[0].iterdir())


def test_manager_rejects_workspace_repointed_while_waiting_for_move_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declaration = rc.AppRC(
        app_id="stale-move",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "app"),
        workspaces=rc.Workspaces(),
    )
    manager = declaration.workspaces(environment={})
    source = tmp_path / "source"
    replacement = tmp_path / "replacement"
    destination = tmp_path / "destination"
    manager.register_workspace("alpha", source)
    (source / "payload").write_text("original", encoding="utf-8")
    replacement.mkdir()
    (replacement / "payload").write_text("keep", encoding="utf-8")
    registry_path = manager.registry_path()
    real_write_lock = manager._write_lock

    @contextmanager
    def repoint_before_lock(*roots: Path) -> Iterator[None]:
        assert roots == (registry_path.parent, source, destination)
        repoint_workspace(name="alpha", root=replacement, path=registry_path)
        with real_write_lock(*roots):
            yield

    monkeypatch.setattr(manager, "_write_lock", repoint_before_lock)

    with pytest.raises(WorkspaceMoveError, match="changed while waiting"):
        manager.move_workspace("alpha", destination)

    assert (source / "payload").is_file()
    assert (replacement / "payload").read_text(encoding="utf-8") == "keep"
    assert not destination.exists()
    assert manager.registry().selected("alpha").root == replacement
