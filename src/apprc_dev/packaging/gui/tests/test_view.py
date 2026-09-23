"""Headless checks for the public native configuration view."""

from pathlib import Path

import apprc as rc
import toga

from apprc_gui import ConfigView


def test_view_handles_first_run_and_secret_edit(
    tmp_path: Path, monkeypatch
) -> None:
    """Keep setup usable before storage exists and route secret edits privately."""
    monkeypatch.setenv("TOGA_BACKEND", "toga_dummy")
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
    desktop = toga.App("GUI check", "org.example.gui-check")
    window = toga.MainWindow()
    view = ConfigView(manager, window)
    assert not view.inspection.ready

    manager.setup(storage_root=tmp_path / "storage")
    view.refresh()
    assert view.inspection.ready
    assert view._scope_select is not None
    view._scope_select.value = "storage"
    view._save("GUI_CHECK_TOKEN", toga.PasswordInput(value="private-value"))
    assert view._error == ""
    assert view._scope_select is not None
    assert view._scope_select.value == "storage"
    assert manager.resolve().build(Client).token == "private-value"
    assert "private-value" not in manager.writable_path("storage").read_text()
    assert "private-value" not in str(view.widget.content)

    manager.registry_path.write_text("invalid = [", encoding="utf-8")
    view.refresh()
    assert not view.inspection.ready
    assert view.widget.content is not None
    desktop.exit()
