"""Checks for the reusable Gradio configuration editor."""

from pathlib import Path

import apprc as rc
import gradio as gr

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
        "GUI_CHECK_TOKEN", True, "private-value", "storage", revision
    )
    assert status == "Saved GUI_CHECK_TOKEN in the storage layer."
    assert manager.resolve().build(Client).token == "private-value"
    assert "private-value" not in manager.writable_path("storage").read_text()
    assert "private-value" not in str(blocks.config)
    assert revision == 2
