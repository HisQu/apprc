"""Browser checks for editable controls in AppRC's dynamic Gradio view."""

from __future__ import annotations

import socket
from pathlib import Path

import apprc as rc
import gradio as gr
from playwright.sync_api import expect, sync_playwright
from apprc_gui import ConfigEditor


def test_prefilled_fields_and_selectors_are_interactive(
    tmp_path: Path,
) -> None:
    """Allow browser edits to prefilled controls and keep read-only fields disabled."""
    app = rc.AppRC(
        app_id="gui-browser-check",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="GUI_BROWSER_STORAGE"),
        apprc_dir=tmp_path / "config",
    )

    @app.config("server", prefix="GUI_BROWSER_")
    class Server(rc.Config):
        port: int = rc.field(
            "GUI_BROWSER_PORT",
            default=7860,
            title="Server port",
            restart_required=True,
        )
        mode: str = rc.field(
            "GUI_BROWSER_MODE",
            default="AUTO",
            title="Mode",
            choices=("AUTO", "MANUAL"),
        )
        state: str = rc.field(
            "GUI_BROWSER_STATE",
            default="managed",
            title="Server state",
            editable=False,
        )

    manager = app.manage(environment={})
    manager.setup(storage_root=tmp_path / "storage-one", storage_name="one")
    manager.register_storage("two", tmp_path / "storage-two")
    manager.setup_user_dotenv()
    editor = ConfigEditor(manager)

    with gr.Blocks() as blocks:
        editor.render()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    _, local_url, _ = blocks.launch(
        server_name="127.0.0.1",
        server_port=port,
        quiet=True,
        prevent_thread_lock=True,
    )
    assert local_url is not None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(local_url, wait_until="domcontentloaded")

                server_port = page.get_by_label(
                    "Server port (restart required)"
                )
                expect(server_port).to_be_enabled(timeout=30_000)
                expect(server_port).to_have_value("7860")

                mode = page.get_by_label("Mode")
                expect(mode).to_be_enabled()
                expect(mode).to_have_value("AUTO")
                mode.click()
                page.get_by_role("option", name="MANUAL").click()
                expect(mode).to_have_value("MANUAL")

                scope = page.get_by_label("Save changes in")
                expect(scope).to_be_enabled()
                scope.click()
                page.get_by_role("option", name="storage").click()

                storage_folder = page.get_by_label("Storage folder")
                expect(storage_folder).to_be_enabled()
                expect(storage_folder).to_have_value(
                    str(manager.paths.root / "storage")
                )
                selected_storage = page.get_by_label("Selected storage")
                expect(selected_storage).to_be_enabled()
                expect(selected_storage).to_have_value("one")
                selected_storage.click()
                page.get_by_role("option", name="two").click()
                page.get_by_role("button", name="Use selected storage").click()
                status = page.get_by_label("Configuration status")
                expect(status).to_have_value("Selected storage two.")

                scope = page.get_by_label("Save changes in")
                scope.click()
                page.get_by_role("option", name="storage").click()
                server_port = page.get_by_label(
                    "Server port (restart required)"
                )
                server_port.fill("9000")

                read_only = page.get_by_label("Server state")
                expect(read_only).to_be_disabled()

                page.get_by_role(
                    "button", name="Save", exact=True
                ).first.click()
                expect(status).to_have_value(
                    "Saved GUI_BROWSER_PORT in the storage layer. Restart "
                    "the application to reload configuration."
                )
                assert manager.resolve().build(Server).port == 9000
            finally:
                browser.close()
    finally:
        blocks.close()
