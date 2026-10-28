"""Checks for the reusable Gradio configuration editor."""

import os
from pathlib import Path

import gradio as gr
import pytest
from apprc_gui import ConfigEditor

import apprc as rc


def test_editor_configures_workspace_and_saves_secret(tmp_path: Path) -> None:
    """Show workspace controls and route secret values to the private layer."""
    app = rc.AppRC(
        app_id="gui-check",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(selector_env_key="GUI_CHECK_WORKSPACE"),
    )

    @app.config("client", prefix="GUI_CHECK_")
    class Client(rc.Config):
        token: str = rc.field("GUI_CHECK_TOKEN", default="", secret=True)

    options = rc.ResolveOptions(workspace_required=True)
    manager = app.manage(options, environment={})
    workspace_manager = app.workspaces(options, environment={})
    app.ensure_path("config")
    editor = ConfigEditor(manager, workspace_manager)
    with gr.Blocks() as blocks:
        editor.render()
    assert not manager.inspect().ready

    _, revision = editor._create_workspace(
        "default", str(tmp_path / "workspace"), 0
    )
    assert manager.inspect().ready
    _, revision = editor._save(
        "GUI_CHECK_TOKEN",
        True,
        False,
        "private-value",
        "workspace",
        revision,
    )
    assert manager.resolve().build(Client).token == "private-value"
    assert "private-value" not in manager.writable_path("workspace").read_text()
    assert "private-value" not in str(blocks.config)
    assert revision == 2


def test_registry_editor_requires_workspace_manager(tmp_path: Path) -> None:
    app = rc.AppRC(
        app_id="gui-missing-workspace-manager",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        workspaces=rc.Workspaces(),
    )
    manager = app.manage(environment={})
    editor = ConfigEditor(manager)

    app.ensure_path("config")
    with (
        gr.Blocks(),
        pytest.raises(
            ValueError,
            match="Registry-backed workspace UI requires a WorkspaceManager",
        ),
    ):
        editor._render_workspace(gr.Textbox(), gr.State(0))


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory mode check")
def test_save_secret_reports_repair_without_echoing_value(
    tmp_path: Path,
) -> None:
    """Explain an unsafe workspace directory without exposing the value."""
    app = rc.AppRC(
        app_id="gui-shared-secret-check",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(selector_env_key="GUI_SHARED_WORKSPACE"),
    )

    @app.config("client", prefix="GUI_SHARED_")
    class Client(rc.Config):
        token: str = rc.field("GUI_SHARED_TOKEN", default="", secret=True)

    options = rc.ResolveOptions(workspace_required=True)
    manager = app.manage(options, environment={})
    workspace_manager = app.workspaces(options, environment={})
    app.ensure_path("config")
    editor = ConfigEditor(manager, workspace_manager)
    workspace_root = tmp_path / "shared-workspace"
    workspace_root.mkdir()
    workspace_root.chmod(0o755)

    _, revision = editor._create_workspace(
        "default", str(workspace_root), 0
    )

    entered_value = "must-never-appear-in-the-status"
    message, revision = editor._save(
        "GUI_SHARED_TOKEN",
        True,
        False,
        entered_value,
        "workspace",
        revision,
    )

    assert entered_value not in message
    assert revision == 1
    assert workspace_root.stat().st_mode & 0o777 == 0o755


def test_repair_reports_unusable_secret_path(tmp_path: Path) -> None:
    """Do not claim a repair succeeded when the secret path is a directory."""
    app = rc.AppRC(
        app_id="gui-invalid-secret-path",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(selector_env_key="GUI_INVALID_WORKSPACE"),
    )

    @app.config("client", prefix="GUI_INVALID_")
    class Client(rc.Config):
        token: str = rc.field("GUI_INVALID_TOKEN", default="", secret=True)

    options = rc.ResolveOptions(workspace_required=True)
    manager = app.manage(options, environment={})
    app.ensure_path("config")
    workspace_manager = app.workspaces(options, environment={})
    workspace_manager.register_workspace("default", tmp_path / "workspace")
    workspace_manager.select_workspace("default")
    editor = ConfigEditor(manager, workspace_manager)
    secret_path = manager.writable_path(
        "workspace", workspace="default", secret=True
    )
    secret_path.unlink()
    secret_path.mkdir()

    _, revision = editor._repair_secrets("workspace", "default", 4)

    assert revision == 4


def test_restart_required_setting_is_labeled_and_notifies_after_edit(
    tmp_path: Path,
) -> None:
    """The editor labels and reports changes that need an application restart."""
    app = rc.AppRC(
        app_id="gui-restart-required",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        user_dotenv=rc.UserDotenv(),
    )

    @app.config("server", prefix="GUI_RESTART_")
    class Server(rc.Config):
        port: int = rc.field(
            "GUI_RESTART_PORT",
            default=7860,
            title="Server port",
            restart_required=True,
        )

    app.ensure_path("config")

    manager = app.manage(environment={})
    manager.setup()
    editor = ConfigEditor(manager)
    _, revision = editor._save(
        "GUI_RESTART_PORT",
        False,
        True,
        "9000",
        "user",
        0,
    )
    _, revision = editor._clear(
        "GUI_RESTART_PORT",
        True,
        "user",
        revision,
    )
    assert revision == 2


def test_clearing_absent_restart_required_value_is_a_no_op(
    tmp_path: Path,
) -> None:
    """A no-op clear neither increments revision nor asks for a restart."""
    app = rc.AppRC(
        app_id="gui-restart-required-noop-clear",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
    )

    @app.config("server", prefix="GUI_RESTART_NOOP_")
    class Server(rc.Config):
        port: int = rc.field(
            "GUI_RESTART_NOOP_PORT",
            default=7860,
            restart_required=True,
        )

    app.ensure_path("config")

    manager = app.manage(environment={})
    manager.setup()
    editor = ConfigEditor(manager)

    _, revision = editor._clear(
        "GUI_RESTART_NOOP_PORT",
        True,
        "user",
        7,
    )

    assert revision == 7
