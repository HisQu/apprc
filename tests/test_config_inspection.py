"""Inspection captures declared workspace state without filesystem writes."""

from __future__ import annotations

from pathlib import Path

import pytest

import apprc as rc
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.paths import Layout, Paths


def test_declarations_keep_paths_and_workspaces_independent() -> None:
    direct = rc.AppRC(
        app_id="direct-workspace",
        paths=Paths(cache=True),
        workspaces=Workspaces(registry=False),
    )
    registered = rc.AppRC(
        app_id="registered-workspace",
        paths=Paths(config=True, appdata=True),
        workspaces=Workspaces(selector_env_key="CUSTOM_WORKSPACE"),
    )

    assert direct.schema.paths == Paths(cache=True)
    assert direct.schema.require_workspaces().registry is False
    assert registered.schema.paths == Paths(config=True, appdata=True)
    assert registered.schema.workspace_selector_env_key == "CUSTOM_WORKSPACE"


def test_workspace_inspection_captures_selection_without_writing(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(
        app_id="workspace-inspection",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "app"),
        workspaces=Workspaces(registry=False),
    )
    root = tmp_path / "project"
    options = rc.ResolveOptions(workspace=str(root))
    app.workspaces(options, environment={}).initialize_workspace(root)

    inspected = app.manage(options, environment={}).inspect()

    assert inspected.resolved.workspace is not None
    assert inspected.resolved.workspace.root == root
    assert inspected.resolved.workspace_issues == ()
    assert inspected.resolved.paths.config_dir == tmp_path / "app" / "config"
    assert not (tmp_path / "app").exists()


def test_disabled_workspace_component_is_rejected_by_spec() -> None:
    with pytest.raises(
        ValueError, match="UserDotenv requires paths.config=True"
    ):
        AppConfigSpec(
            app_id="no-config",
            display_name="No Config",
            user_dotenv=UserDotenv(),
        )
