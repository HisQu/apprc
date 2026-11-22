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
    """Keep browser edits tied to the workspace shown in each session."""
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
    original_root = tmp_path / "workspace-one"
    workspace_manager.register_workspace("one", original_root)
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
                other_page = browser.new_page()
                other_page.goto(local_url, wait_until="domcontentloaded")
                other_workspace = other_page.get_by_label("Selected workspace")
                expect(other_workspace).to_have_value("one")
                other_workspace.click()
                other_page.get_by_role("option", name="two").click()
                other_page.get_by_role(
                    "button", name="Use selected workspace"
                ).click()
                other_status = other_page.get_by_label("Configuration status")
                expect(other_status).to_have_value("Selected workspace two.")
                assert workspace_manager.registry().selected_workspace == "two"

                expect(selected_workspace).to_have_value("one")
                server_port.fill("8000")

                read_only = page.get_by_label("Server state")
                expect(read_only).to_be_disabled()
                page.get_by_role(
                    "button", name="Save", exact=True
                ).first.click()
                status = page.get_by_label("Configuration status")
                expect(status).to_have_value(
                    "Saved GUI_BROWSER_PORT in the workspace layer. Restart "
                    "the application to reload configuration."
                )
                assert manager.resolve().build(Server).port == 7860

                workspace_manager.select_workspace("one")
                page.reload(wait_until="domcontentloaded")
                expect(selected_workspace).to_have_value("one")
                expect(server_port).to_have_value("8000")

                expect(other_workspace).to_have_value("two")
                other_scope = other_page.get_by_label("Save changes in")
                other_scope.click()
                other_page.get_by_role("option", name="workspace").click()
                other_port = other_page.get_by_label(
                    "Server port (restart required)"
                )
                expect(other_port).to_have_value("7860")
                other_port.fill("9000")
                other_page.get_by_role(
                    "button", name="Save", exact=True
                ).first.click()
                expect(other_status).to_have_value(
                    "Saved GUI_BROWSER_PORT in the workspace layer. Restart "
                    "the application to reload configuration."
                )
                expect(other_workspace).to_have_value("two")
                assert manager.resolve().build(Server).port == 8000
                workspace_manager.select_workspace("two")
                assert manager.resolve().build(Server).port == 9000

                workspace_manager.select_workspace("one")
                scope.click()
                page.get_by_role("option", name="workspace").click()
                server_port.fill("8001")
                new_root = tmp_path / "repointed-workspace"
                new_root.mkdir(mode=0o700)
                workspace_manager.repoint_workspace("one", new_root)
                page.get_by_role(
                    "button", name="Save", exact=True
                ).first.click()
                expect(server_port).to_have_value("7860")
                repointed = manager.inspect(workspace="one")
                assert repointed.resolved.build(Server).port == 7860
                original = manager.inspect(workspace=str(original_root))
                assert original.resolved.build(Server).port == 8001
            finally:
                browser.close()
    finally:
        blocks.close()
