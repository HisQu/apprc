"""Browser checks for editable controls in AppRC's dynamic Gradio view."""

from __future__ import annotations

import socket
from pathlib import Path

import gradio as gr
from apprc_gui import ConfigEditor
from playwright.sync_api import expect, sync_playwright

import apprc as rc


def test_prefilled_fields_and_selectors_are_interactive(
    tmp_path: Path,
) -> None:
    """Allow browser edits to prefilled controls and keep read-only fields disabled."""
    app = rc.AppRC(
        app_id="gui-browser-check",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path),
        user_dotenv=rc.UserDotenv(),
        workspaces=rc.Workspaces(selector_env_key="GUI_BROWSER_WORKSPACE"),
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
    app.ensure_path("config")

    workspace_manager = app.workspaces(environment={})
    workspace_manager.register_workspace("one", tmp_path / "workspace-one")
    workspace_manager.select_workspace("one")
    workspace_manager.register_workspace("two", tmp_path / "workspace-two")
    manager.setup()
    editor = ConfigEditor(manager, workspace_manager)

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
                page.get_by_role("option", name="workspace").click()

                workspace_folder = page.get_by_label("Workspace folder")
                expect(workspace_folder).to_be_enabled()
                expect(workspace_folder).to_have_value(
                    str(manager.paths.require("config") / "workspaces")
                )
                selected_workspace = page.get_by_label("Selected workspace")
                expect(selected_workspace).to_be_enabled()
                expect(selected_workspace).to_have_value("one")
                selected_workspace.click()
                page.get_by_role("option", name="two").click()
                page.get_by_role(
                    "button", name="Use selected workspace"
                ).click()
                status = page.get_by_label("Configuration status")
                expect(status).to_have_value("Selected workspace two.")

                scope = page.get_by_label("Save changes in")
                scope.click()
                page.get_by_role("option", name="workspace").click()
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
                    "Saved GUI_BROWSER_PORT in the workspace layer. Restart "
                    "the application to reload configuration."
                )
                assert manager.resolve().build(Server).port == 9000
            finally:
                browser.close()
    finally:
        blocks.close()
