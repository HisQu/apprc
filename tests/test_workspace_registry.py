"""Workspace registry serialization and selector behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import apprc as rc
from apprc.user_files.workspace_roots._io import (
    load_workspace_registry_or_empty,
    render_workspace_registry,
)
from apprc.user_files.workspace_roots.model import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from apprc.user_files.workspace_roots.registry import register_workspace
from apprc.user_files.workspace_roots.selector import (
    resolve_workspace_selector_value,
)


def test_workspace_registry_schema_v1_round_trip(tmp_path: Path) -> None:
    registry_path = tmp_path / "apprc.toml"
    registry = WorkspaceRegistry(
        path=registry_path,
        workspaces={"alpha": WorkspaceRecord("alpha", tmp_path / "alpha")},
        selected_workspace="alpha",
        archived_workspaces={
            "beta": ArchivedWorkspaceRecord(
                "beta",
                tmp_path / "beta.apprc.tar.xz",
                tmp_path / "beta",
            ),
        },
    )

    registry_path.write_text(
        render_workspace_registry(registry), encoding="utf-8"
    )
    loaded = load_workspace_registry_or_empty(registry_path)

    assert loaded.schema_version == 1
    assert loaded.selected_workspace == "alpha"
    assert loaded.workspaces == registry.workspaces
    assert loaded.archived_workspaces == registry.archived_workspaces
    assert render_workspace_registry(loaded) == render_workspace_registry(
        registry
    )


def test_workspace_registry_rejects_storage_schema_without_rewriting(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "apprc.toml"
    original = (
        'selected_storage = "alpha"\n[storages.alpha]\nroot = "/tmp/alpha"\n'
    )
    registry_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError):
        load_workspace_registry_or_empty(registry_path)

    assert registry_path.read_text(encoding="utf-8") == original


def test_register_workspace_persists_selected_workspace(tmp_path: Path) -> None:
    registry_path = tmp_path / "config" / "apprc.toml"

    registry = register_workspace(
        name="alpha",
        root=tmp_path / "alpha",
        path=registry_path,
    )

    assert registry.selected_workspace == "alpha"
    assert registry.workspaces["alpha"].root == (tmp_path / "alpha").resolve()
    assert load_workspace_registry_or_empty(registry_path) == registry


def test_direct_workspace_selector_resolves_relative_to_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    selection = resolve_workspace_selector_value(
        registry=None,
        raw_value="projects/demo",
        workspace_selector_env_key="DEMO_WORKSPACE",
    )

    assert selection.root == tmp_path / "projects" / "demo"
    assert selection.selector_kind == "path"


def test_direct_workspace_selector_rejects_bare_names() -> None:
    with pytest.raises(
        ValueError,
        match="^Named workspaces require a registry\\.$",
    ):
        resolve_workspace_selector_value(
            registry=None,
            raw_value="alpha",
            workspace_selector_env_key="DEMO_WORKSPACE",
        )


def test_direct_workspace_manager_returns_explicit_directory(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(
        app_id="direct-workspace",
        workspaces=rc.Workspaces(registry=False),
    )
    root = tmp_path / "workspace"
    root.mkdir()

    selected = app.workspaces(environment={}).select_workspace(str(root))

    assert selected == root


def test_initialize_workspace_resolves_relative_typed_path_from_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = rc.AppRC(
        app_id="direct-workspace",
        workspaces=rc.Workspaces(registry=False),
    )
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    root = app.workspaces(environment={}).initialize_workspace(
        Path("relative-dir")
    )

    assert root == working_directory / "relative-dir"
    assert (root / "apprc.workspace.env").is_file()
