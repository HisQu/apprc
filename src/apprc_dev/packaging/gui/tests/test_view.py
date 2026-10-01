"""Checks for the reusable Gradio configuration editor."""

import os
from pathlib import Path

import apprc as rc
import gradio as gr
import pytest

from apprc_gui import ConfigEditor


def test_editor_configures_storage_and_saves_secret(tmp_path: Path) -> None:
    """Show first-run controls and route secret values to the private layer."""
    app = rc.AppRC(
        app_id="gui-check",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="GUI_CHECK_STORAGE"),
        apprc_dir=tmp_path / "config",
    )

    @app.config("client", prefix="GUI_CHECK_")
    class Client(rc.Config):
        token: str = rc.field("GUI_CHECK_TOKEN", default="", secret=True)

    manager = app.manage(
        rc.ResolveOptions(storage_required=True), environment={}
    )
    editor = ConfigEditor(manager)
    with gr.Blocks() as blocks:
        editor.render()
    assert not manager.inspect().ready
    assert blocks.fns
    with gr.Blocks() as first_run_controls:
        editor._render_storage(gr.Textbox(), gr.State(0))
    assert "Create and select storage" in str(first_run_controls.config)

    status, revision = editor._create_storage(
        "default", str(tmp_path / "storage"), 0
    )
    assert status == "Selected storage default."
    assert manager.inspect().ready
    status, revision = editor._save(
        "GUI_CHECK_TOKEN",
        True,
        False,
        "private-value",
        "storage",
        revision,
    )
    assert status == "Saved GUI_CHECK_TOKEN in the storage layer."
    assert manager.resolve().build(Client).token == "private-value"
    assert "private-value" not in manager.writable_path("storage").read_text()
    assert "private-value" not in str(blocks.config)
    assert revision == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory mode check")
def test_save_secret_reports_repair_without_echoing_value(
    tmp_path: Path,
) -> None:
    """Explain a shared storage directory without exposing the submitted value."""
    app = rc.AppRC(
        app_id="gui-shared-secret-check",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="GUI_SHARED_STORAGE"),
        apprc_dir=tmp_path / "config",
    )

    @app.config("client", prefix="GUI_SHARED_")
    class Client(rc.Config):
        token: str = rc.field("GUI_SHARED_TOKEN", default="", secret=True)

    manager = app.manage(
        rc.ResolveOptions(storage_required=True), environment={}
    )
    editor = ConfigEditor(manager)
    storage_root = tmp_path / "shared-storage"
    storage_root.mkdir()
    storage_root.chmod(0o755)

    message, revision = editor._create_storage("default", str(storage_root), 0)
    assert message == "Selected storage default."
    assert revision == 1

    entered_value = "must-never-appear-in-the-status"
    message, revision = editor._save(
        "GUI_SHARED_TOKEN",
        True,
        False,
        entered_value,
        "storage",
        revision,
    )

    assert "parent directory is readable by other users" in message
    assert "config secrets repair --scope storage" in message
    assert entered_value not in message
    assert revision == 1
    assert storage_root.stat().st_mode & 0o777 == 0o755


def test_repair_reports_unusable_secret_path(tmp_path: Path) -> None:
    """Do not claim a repair succeeded when the secret path is a directory."""
    app = rc.AppRC(
        app_id="gui-invalid-secret-path",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="GUI_INVALID_STORAGE"),
        apprc_dir=tmp_path / "config",
    )

    @app.config("client", prefix="GUI_INVALID_")
    class Client(rc.Config):
        token: str = rc.field("GUI_INVALID_TOKEN", default="", secret=True)

    manager = app.manage(environment={})
    editor = ConfigEditor(manager)
    manager.setup(storage_root=tmp_path / "storage")
    secret_path = manager.writable_path("storage", secret=True)
    secret_path.unlink()
    secret_path.mkdir()

    message, revision = editor._repair_secrets("storage", 4)

    assert "The secret path is not a file." in message
    assert "Repaired storage secret file permissions." not in message
    assert revision == 4


def test_restart_required_setting_is_labeled_and_notifies_after_edit(
    tmp_path: Path,
) -> None:
    """The editor labels and reports changes that need an application restart."""
    app = rc.AppRC(
        app_id="gui-restart-required",
        user_dotenv=rc.UserDotenv(),
        apprc_dir=tmp_path / "config",
    )

    @app.config("server", prefix="GUI_RESTART_")
    class Server(rc.Config):
        port: int = rc.field(
            "GUI_RESTART_PORT",
            default=7860,
            title="Server port",
            restart_required=True,
        )

    manager = app.manage(environment={})
    manager.setup()
    editor = ConfigEditor(manager)
    with gr.Blocks() as blocks:
        editor._render_field(
            manager.inspect().fields[0],
            gr.Dropdown(
                choices=["user"],
                value="user",
                label="Save changes in",
            ),
            gr.Textbox(label="Configuration status", interactive=False),
            gr.State(0),
        )

    assert "Server port (restart required)" in str(blocks.config)
    assert "Restart the application to load saved settings" in str(
        blocks.config
    )
    status, revision = editor._save(
        "GUI_RESTART_PORT",
        False,
        True,
        "9000",
        "user",
        0,
    )
    assert status == (
        "Saved GUI_RESTART_PORT in the user layer. Restart the application "
        "to reload configuration."
    )
    status, revision = editor._clear(
        "GUI_RESTART_PORT",
        True,
        "user",
        revision,
    )
    assert status == (
        "Cleared the saved GUI_RESTART_PORT value in the user layer. "
        "Restart the application to reload configuration."
    )
    assert revision == 2


def test_clearing_absent_restart_required_value_is_a_no_op(
    tmp_path: Path,
) -> None:
    """A no-op clear neither increments revision nor asks for a restart."""
    app = rc.AppRC(
        app_id="gui-restart-required-noop-clear",
        user_dotenv=rc.UserDotenv(),
        apprc_dir=tmp_path / "config",
    )

    @app.config("server", prefix="GUI_RESTART_NOOP_")
    class Server(rc.Config):
        port: int = rc.field(
            "GUI_RESTART_NOOP_PORT",
            default=7860,
            restart_required=True,
        )

    manager = app.manage(environment={})
    manager.setup()
    editor = ConfigEditor(manager)

    message, revision = editor._clear(
        "GUI_RESTART_NOOP_PORT",
        True,
        "user",
        7,
    )

    assert message == "No saved GUI_RESTART_NOOP_PORT value in the user layer."
    assert revision == 7
