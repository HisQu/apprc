from __future__ import annotations

from pathlib import Path

import pytest

from apprc.user_files.workspace_roots.move import (
    WorkspaceMoveError,
    move_workspace,
)
from apprc.user_files.workspace_roots.registry import (
    load_workspace_registry_or_empty,
    register_workspace,
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
