from __future__ import annotations

from pathlib import Path

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.interfaces.cli.config_command._output import workspace_list_payload


def test_workspace_list_payload_reports_marker_readiness(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(
        app_id="workspace_output",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        workspaces=rc.Workspaces(),
    )
    paths = app.paths(environment={})
    manager = app.workspaces(environment={})
    manager.register_workspace("beta", tmp_path / "beta")
    registry = manager.register_workspace("alpha", tmp_path / "alpha")
    beta_marker = tmp_path / "beta" / "apprc.workspace.env"
    beta_marker.unlink()

    payload = workspace_list_payload(
        registry,
        workspace_dotenv_filename="apprc.workspace.env",
        active_workspace_root=tmp_path / "alpha",
    )
    assert paths.config_dir is not None

    assert payload == {
        "config_file": str(paths.config_dir / "apprc.toml"),
        "workspaces": [
            {
                "name": "alpha",
                "active": True,
                "root": str((tmp_path / "alpha").resolve()),
                "root_exists": True,
                "workspace_dotenv": str(
                    (tmp_path / "alpha" / "apprc.workspace.env").resolve()
                ),
                "workspace_dotenv_exists": True,
            },
            {
                "name": "beta",
                "active": False,
                "root": str((tmp_path / "beta").resolve()),
                "root_exists": True,
                "workspace_dotenv": str(
                    (tmp_path / "beta" / "apprc.workspace.env").resolve()
                ),
                "workspace_dotenv_exists": False,
            },
        ],
    }
