"""Workspace selection and configuration sources resolve per invocation."""

from __future__ import annotations

from pathlib import Path

import pytest

import apprc as rc


class _Client(rc.Config):
    label: str = rc.field("CLIENT_LABEL", default="default")
    token: str = rc.field("CLIENT_TOKEN", default="", secret=True)


def _app(*, registry: bool) -> tuple[rc.AppRC, type[_Client]]:
    """Build a workspace-capable application for resolution scenarios."""
    app = rc.AppRC(
        app_id="resolution-test",
        paths=rc.Paths(config=True),
        workspaces=rc.Workspaces(
            selector_env_key="RESOLUTION_TEST_WORKSPACE",
            registry=registry,
        ),
    )

    Client = app.config("client", prefix="CLIENT_", requires_workspace=True)(
        _Client
    )
    return app, Client


def test_direct_workspace_resolution_captures_path_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _app(registry=False)
    root = tmp_path / "workspace"
    app.workspaces(environment={}).initialize_workspace(root)
    monkeypatch.chdir(tmp_path)

    resolved = app.resolve(
        rc.ResolveOptions(workspace="./workspace"),
        environment={},
    )

    assert resolved.workspace is not None
    assert resolved.workspace.root == root
    assert resolved.workspace.workspace_name is None
    assert resolved.workspace.selector_kind == "path"
    assert resolved.workspace_issues == ()
    assert resolved.paths is not None


def test_direct_workspace_resolution_rejects_bare_name() -> None:
    app, _ = _app(registry=False)

    with pytest.raises(
        ValueError, match="^Named workspaces require a registry\\.$"
    ):
        app.resolve(rc.ResolveOptions(workspace="alpha"), environment={})


def test_registered_workspace_output_and_saved_settings_reload(
    tmp_path: Path,
) -> None:
    app, Client = _app(registry=True)
    workspace_root = tmp_path / "alpha"
    manager = app.workspaces(environment={})
    registry = manager.register_workspace("alpha", workspace_root)
    assert registry.selected_workspace == "alpha"

    settings = app.manage(environment={})
    settings.apply_edit(
        settings.plan_update(
            "CLIENT_LABEL",
            "saved",
            scope="workspace",
            workspace="alpha",
        )
    )
    settings.apply_edit(
        settings.plan_update(
            "CLIENT_TOKEN",
            "private-token",
            scope="workspace",
            workspace="alpha",
        )
    )

    resolved = app.resolve(
        rc.ResolveOptions(workspace="alpha"),
        environment={},
    )
    config = resolved.build(Client)
    secret_path = settings.writable_path(
        "workspace",
        workspace="alpha",
        secret=True,
    )
    ordinary_path = settings.writable_path("workspace", workspace="alpha")

    assert resolved.workspace is not None
    assert resolved.workspace.root == workspace_root.resolve()
    assert resolved.workspace.workspace_name == "alpha"
    assert resolved.workspace_count == 1
    assert config.label == "saved"
    assert config.token == "private-token"
    assert "private-token" not in config.to_dict().values()
    assert secret_path.name == "apprc.workspace.secret.env"
    assert "CLIENT_TOKEN" in secret_path.read_text(encoding="utf-8")
    assert "CLIENT_TOKEN" not in ordinary_path.read_text(encoding="utf-8")
