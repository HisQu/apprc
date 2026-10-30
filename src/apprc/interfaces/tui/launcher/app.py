"""Responsive Textual launcher with owned foreground child management."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import platform
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Select, Static

from apprc.services.workspaces import WorkspaceManager


from apprc.interfaces.tui._primitives import ConfirmScreen
from apprc.interfaces.tui.editor.app import ConfigEditorScreen
from apprc.interfaces.tui.launcher.model import (
    LauncherAction,
    LauncherContext,
    LauncherHandler,
    _SAVED_UNINSTALL_REQUESTED,
)
from apprc.user_files.app_home.locations import assert_no_links

_SAFE_STATUSES = frozenset(("missing", "ready", "removed-retained"))


class LauncherApp(App[Any]):
    """Run one reusable launcher screen in one Textual event loop."""

    TITLE = "AppRC launcher"

    def __init__(
        self,
        *,
        context: LauncherContext,
        handlers: Mapping[str, LauncherHandler],
    ) -> None:
        """Capture app inputs and construct the home screen."""
        super().__init__()
        self.context = context
        self.handlers = dict(handlers)
        self.home = LauncherHomeScreen(context=context, launcher_app=self)

    def on_mount(self) -> None:
        """Show the home screen without creating another application loop."""
        self.push_screen(self.home)


class LauncherHomeScreen(Screen[None]):
    """Capability-driven launcher home with diagnostic recovery actions."""

    CSS = """
    #launcher-content {
        height: 1fr;
        min-height: 1;
    }
    #launcher-actions {
        height: auto;
        margin: 1 2;
    }
    #launcher-status {
        margin: 1 2;
        padding: 1;
        border: solid $primary;
    }
    #launcher-title {
        margin: 1 2;
        text-style: bold;
    }
    """
    BINDINGS = [("q", "quit_launcher", "Quit")]

    def __init__(
        self, *, context: LauncherContext, launcher_app: LauncherApp
    ) -> None:
        """Keep the captured host state and owned child process set."""
        super().__init__()
        self.context = context
        self.launcher_app = launcher_app
        self._children: dict[int, asyncio.subprocess.Process] = {}
        self._uninstall_pending = False

    def compose(self) -> ComposeResult:
        """Show app actions and only those management controls with authority."""
        inspection = self.context.inspection
        safe = (
            inspection.status in _SAFE_STATUSES
            and self.context.paths is not None
        )
        yield Header()
        with VerticalScroll(id="launcher-content"):
            yield Static(
                self.context.spec.title, id="launcher-title", markup=False
            )
            status = {
                "status": "error"
                if self.context.path_error is not None
                else inspection.status,
                "installation_status": inspection.status,
                "path_error": self.context.path_error,
                "directory": str(inspection.directory),
                "diagnostics": [
                    item.message for item in inspection.diagnostics
                ],
            }
            yield Static(
                json.dumps(status, indent=2), id="launcher-status", markup=False
            )
            with Vertical(id="launcher-actions"):
                for group, label in (("main", "Main"), ("project", "Project")):
                    actions = tuple(
                        action
                        for action in self.context.spec.actions
                        if action.group == group
                    )
                    if actions:
                        yield Static(label)
                    for action in actions:
                        yield Button(
                            Text(action.label),
                            id=f"launcher-action-{action.id}",
                            disabled=not safe,
                        )
                has_config = bool(
                    self.context.apprc.schema.paths.config
                    or self.context.apprc.schema.owners
                    or self.context.apprc.schema.user_dotenv
                )
                yield Button(
                    "Configuration",
                    id="launcher-config",
                    disabled=not (safe and has_config),
                )
                yield Button("Paths", id="launcher-paths")
                yield Button(
                    "Workspaces",
                    id="launcher-workspaces",
                    disabled=not (
                        safe and self.context.apprc.schema.uses_workspaces()
                    ),
                )
                yield Button("Doctor", id="launcher-doctor")
                yield Button(
                    "Migrate legacy placement",
                    id="launcher-migrate",
                    disabled=inspection.status not in _SAFE_STATUSES,
                )
                repairable = inspection.status in {
                    "provisional",
                    "incomplete",
                    "invalid",
                    "removed-retained",
                }
                yield Button(
                    "Repair", id="launcher-repair", disabled=not repairable
                )
                has_record = (
                    inspection.record is not None
                    and inspection.status
                    in {
                        "ready",
                        "removed-retained",
                    }
                )
                yield Button(
                    "Uninstall",
                    id="launcher-uninstall",
                    disabled=not has_record,
                )
                yield Button("Quit", id="launcher-quit")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dispatch a UI action without blocking Textual's event loop."""
        action_id = event.button.id
        if action_id is None:
            return
        if self._uninstall_pending:
            return
        if action_id == "launcher-quit":
            self.run_worker(self._quit(), group="launcher-quit", exclusive=True)
        elif action_id == "launcher-config":
            self._open_config()
        elif action_id == "launcher-workspaces":
            self._open_config()
        elif action_id == "launcher-paths":
            self._show_paths()
        elif action_id == "launcher-doctor":
            self.notify(
                f"Installation {self.context.inspection.status}: "
                f"{self.context.inspection.directory}",
                markup=False,
            )
        elif action_id == "launcher-migrate":
            self.run_worker(
                self._migrate(),
                group="launcher-maintenance",
                exclusive=True,
            )
        elif action_id == "launcher-repair":
            self.run_worker(
                self._repair(), group="launcher-maintenance", exclusive=True
            )
        elif action_id == "launcher-uninstall":
            self._uninstall_pending = True
            self.run_worker(
                self._uninstall(), group="launcher-maintenance", exclusive=True
            )
        elif action_id.startswith("launcher-action-"):
            name = action_id.removeprefix("launcher-action-")
            action = next(
                (item for item in self.context.spec.actions if item.id == name),
                None,
            )
            if action is not None:
                self.run_worker(
                    self._run_action(action),
                    group="launcher-actions",
                    exclusive=True,
                )

    def _open_config(self) -> None:
        """Push the shared editor screen using the launcher's captured paths."""
        paths = self.context.paths
        if paths is None:
            self.notify(
                "Configuration is unavailable until installation paths are repaired.",
                severity="error",
            )
            return
        apprc = self.context.apprc
        manager = apprc._manage_with_paths(
            self.context.options, self.context.environment, paths
        )
        workspace_manager = (
            WorkspaceManager(
                apprc.schema,
                options=self.context.options,
                environment=self.context.environment,
                app_paths=paths,
            )
            if apprc.schema.uses_workspaces()
            else None
        )

        def close_editor() -> None:
            """Return to the existing launcher screen."""
            self.app.pop_screen()

        self.app.push_screen(
            ConfigEditorScreen(
                apprc=apprc,
                manager=manager,
                workspace_manager=workspace_manager,
                on_exit=close_editor,
            )
        )

    def _show_paths(self) -> None:
        """Display captured paths and installation diagnostics without writes."""
        paths = self.context.paths
        directories: dict[str, Path] = {}
        if paths is None:
            values = {
                "installation": str(self.context.inspection.directory),
                "status": self.context.inspection.status,
                "path_error": self.context.path_error,
                "diagnostics": [
                    item.message for item in self.context.inspection.diagnostics
                ],
            }
        else:
            values = {
                "layout": paths.layout.mode,
                "config": str(paths.config_dir) if paths.config_dir else None,
                "appdata": str(paths.appdata_dir)
                if paths.appdata_dir
                else None,
                "cache": str(paths.cache_dir) if paths.cache_dir else None,
                "state": str(paths.state_dir) if paths.state_dir else None,
                "logs": str(paths.logs_dir) if paths.logs_dir else None,
                "installation": str(paths.installation.directory),
            }
            directories = {
                kind: directory
                for kind, directory in (
                    ("config", paths.config_dir),
                    ("appdata", paths.appdata_dir),
                    ("cache", paths.cache_dir),
                    ("state", paths.state_dir),
                    ("logs", paths.logs_dir),
                )
                if directory is not None
            }
        directories["installation"] = self.context.inspection.directory
        self.app.push_screen(
            LauncherInfoScreen(
                values=values,
                directories=directories,
                open_path=self._open_path,
            )
        )

    async def _run_action(self, action: LauncherAction) -> None:
        """Run one app-owned argv or handler as a responsive Textual worker."""
        handler = self.launcher_app.handlers.get(action.id)
        if handler is not None:
            if inspect.iscoroutinefunction(handler):
                await handler(self.context, action.interactive)
            else:
                result = await asyncio.to_thread(
                    handler, self.context, action.interactive
                )
                if inspect.isawaitable(result):
                    await result
            return
        argv = tuple(action.argv(self.context, action.interactive))
        if not argv or any(not isinstance(token, str) for token in argv):
            self.notify(
                f"Action {action.label!r} produced invalid arguments.",
                severity="error",
            )
            return
        await self._run_child(argv, interactive=action.interactive)

    async def _run_child(
        self,
        argv: Sequence[str],
        *,
        interactive: bool,
        cwd: Path | None = None,
    ) -> int:
        """Start and await one owned foreground process using argv, never a shell."""

        async def launch_and_wait() -> int:
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=cwd or self.context.cwd,
                    env=dict(self.context.environment),
                )
            except OSError as exc:
                self.notify(str(exc), severity="error", markup=False)
                return 127
            self._children[process.pid] = process
            try:
                return await process.wait()
            finally:
                # > Cancellation must not leave a live opener or command unowned.
                if process.returncode is None:
                    await self._stop_children((process,))
                self._children.pop(process.pid, None)

        if interactive:
            with self.app.suspend():
                return await launch_and_wait()
        return await launch_and_wait()

    async def _open_path(self, argv: Sequence[str]) -> None:
        """Open a path through the trackable foreground-child runner."""
        await self._run_child(argv, interactive=False)

    async def _migrate(self) -> None:
        """Preview recognized migration and require old-consumer consent."""
        manager = self.context.apprc.installation(
            environment=self.context.environment
        )
        try:
            plan = await asyncio.to_thread(manager.preview_migration)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        entries = "\n".join(str(entry.path) for entry in plan.inventory.entries)
        prompt = (
            "Stop all older application consumers before migration.\n"
            f"Recognized files to move:\n{entries or '(none)'}\n"
            f"From: {plan.inventory.source_root}\n"
            f"To: {plan.inventory.destination_root}"
        )
        result = await self.app.push_screen_wait(
            ConfirmScreen(
                title="Migrate legacy AppRC placement",
                message=Text(prompt),
                actions=(("migrate", "Migrate", "warning"),),
            )
        )
        if result != "migrate":
            return
        try:
            inspection = await asyncio.to_thread(
                manager.migrate, plan, quiescent=True
            )
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        self.notify(
            f"Installation migration completed with status {inspection.status}."
        )

    async def _repair(self) -> None:
        """Invoke only the saved matching installer for this installation."""
        try:
            from apprc.distribution.runtime import controllers

            argv = controllers.repair_saved(self.context.inspection.directory)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        status = await self._run_child(argv, interactive=True)
        if status:
            self.notify(
                f"Repair exited with status {status}.", severity="error"
            )

    async def _uninstall(self) -> None:
        """Guard the complete saved-uninstall interaction against competing actions."""
        self._uninstall_pending = True
        try:
            await self._uninstall_saved_entry()
        finally:
            self._uninstall_pending = False

    async def _uninstall_saved_entry(self) -> None:
        """Preview, obtain consent, and await the verified authored procedure."""
        try:
            from apprc.distribution.runtime import controllers

            preparation_task = asyncio.create_task(
                asyncio.to_thread(
                    controllers.prepare_uninstall,
                    self.context.inspection.directory,
                    categories=frozenset(),
                    complete=False,
                    forget_retained=False,
                )
            )
            try:
                preparation = await asyncio.shield(preparation_task)
            except asyncio.CancelledError:
                await asyncio.gather(preparation_task, return_exceptions=True)
                raise
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        entries = "\n".join(f"• {item.path}" for item in preparation.entries)
        diagnostics = "\n".join(
            item.message for item in preparation.diagnostics
        )
        detail = "\n".join(part for part in (entries, diagnostics) if part)
        result = await self.app.push_screen_wait(
            ConfirmScreen(
                title="Remove application program",
                message=Text(
                    "The installation's saved procedure will remove the program "
                    "and preserve user data by default. Exact targets:\n"
                    + (detail or "No data targets are selected.")
                ),
                actions=(("remove", "Remove program", "warning"),),
            )
        )
        if result != "remove":
            return
        if preparation.plan is None or not preparation.can_execute:
            self.notify(
                "The saved procedure cannot safely execute this removal.",
                severity="error",
            )
            return
        try:
            argv = controllers.uninstall_saved(
                self.context.inspection.directory,
                original_pid=os.getpid(),
                expected_revision=preparation.plan.expected_revision,
            )
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        await self._stop_owned_children()
        status = await self._run_child(argv, interactive=False)
        if status:
            self.notify(
                f"Saved uninstall exited with status {status}.",
                severity="error",
            )
            return
        self.app.exit(result=_SAVED_UNINSTALL_REQUESTED)

    async def action_quit_launcher(self) -> None:
        """Stop and await only processes started by this launcher."""
        await self._quit()

    async def _quit(self) -> None:
        if self._uninstall_pending:
            return
        await self._stop_owned_children()
        self.app.exit()

    async def on_unmount(self) -> None:
        """Ensure owned foreground children exit before this screen disappears."""
        await self._stop_owned_children()

    async def _stop_owned_children(self) -> None:
        """Gracefully stop owned children, then kill and await stragglers."""
        await self._stop_children(tuple(self._children.values()))

    @staticmethod
    async def _stop_children(
        children: Sequence[asyncio.subprocess.Process],
    ) -> None:
        """Stop and await the exact owned processes supplied by the caller."""
        for process in children:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        waiting = asyncio.gather(
            *(process.wait() for process in children),
            return_exceptions=True,
        )
        try:
            await asyncio.wait_for(asyncio.shield(waiting), timeout=1.0)
            return
        except TimeoutError:
            pass
        for process in children:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        await waiting


class LauncherInfoScreen(Screen[None]):
    """Inspect, copy and safely open each independently enabled directory."""

    CSS = """
    #launcher-info-content {
        height: 1fr;
        min-height: 1;
        padding: 0 1;
    }
    #launcher-info-actions {
        height: 3;
    }
    #launcher-info-actions Button {
        width: 1fr;
        min-width: 8;
    }
    #launcher-selected-path, #launcher-path-availability {
        height: auto;
        margin-bottom: 1;
    }
    """
    BINDINGS = [("escape", "back", "Back")]

    def __init__(
        self,
        *,
        values: Mapping[str, Any],
        directories: Mapping[str, Path],
        open_path: Callable[[Sequence[str]], Awaitable[None]],
    ) -> None:
        """Capture diagnostics, enabled addresses and the owned async opener."""
        super().__init__()
        self.values = dict(values)
        self.directories = dict(directories)
        self.open_path = open_path

    def compose(self) -> ComposeResult:
        """Keep selection and details scrollable, with actions always reachable."""
        yield Header()
        with VerticalScroll(id="launcher-info-content"):
            yield Select(
                [(kind.capitalize(), kind) for kind in self.directories],
                allow_blank=False,
                id="launcher-path-selection",
            )
            yield Static("", id="launcher-selected-path", markup=False)
            yield Static("", id="launcher-path-availability", markup=False)
            yield Static(
                json.dumps(self.values, indent=2),
                id="launcher-paths-output",
                markup=False,
            )
        with Horizontal(id="launcher-info-actions"):
            yield Button("Copy", id="launcher-copy-path")
            yield Button("Open", id="launcher-open-path")
            yield Button("Back", id="launcher-info-back")
        yield Footer()

    def on_mount(self) -> None:
        """Set the initial path and availability without creating directories."""
        self._update_selection()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh the exact selected address and its current safety status."""
        if event.select.id == "launcher-path-selection":
            self._update_selection()

    def _selected_directory(self) -> Path | None:
        """Return only an enabled address from the selection."""
        selection = self.query_one("#launcher-path-selection", Select).value
        if not isinstance(selection, str):
            return None
        return self.directories.get(selection)

    @staticmethod
    def _directory_error(directory: Path) -> str | None:
        """Reject missing directories and linked ancestors without mutation."""
        try:
            assert_no_links(directory)
            if not directory.is_dir():
                return f"Directory does not exist: {directory}"
        except (OSError, ValueError) as error:
            return str(error)
        return None

    def _update_selection(self) -> None:
        """Keep copy available for missing paths while disabling unsafe opens."""
        directory = self._selected_directory()
        error = (
            "No directory selected."
            if directory is None
            else self._directory_error(directory)
        )
        self.query_one("#launcher-selected-path", Static).update(
            "" if directory is None else str(directory)
        )
        self.query_one("#launcher-path-availability", Static).update(
            error or "Directory is available."
        )
        self.query_one("#launcher-copy-path", Button).disabled = (
            directory is None
        )
        self.query_one("#launcher-open-path", Button).disabled = (
            error is not None
        )

    def action_back(self) -> None:
        """Return to the existing launcher home."""
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Copy through the host App or start its tracked asynchronous opener."""
        action_id = event.button.id
        if action_id == "launcher-info-back":
            self.action_back()
            return
        directory = self._selected_directory()
        if directory is None:
            return
        if action_id == "launcher-copy-path":
            self.app.copy_to_clipboard(str(directory))
        elif action_id == "launcher-open-path":
            self.run_worker(
                self._open_directory(directory),
                group="launcher-open-path",
                exclusive=True,
            )

    async def _open_directory(self, directory: Path) -> None:
        """Revalidate at activation before handing argv to the owned runner."""
        error = self._directory_error(directory)
        if error is not None:
            self._update_selection()
            self.notify(error, severity="warning", markup=False)
            return
        system = platform.system()
        argv = (
            ["explorer.exe", str(directory)]
            if system == "Windows"
            else ["open", str(directory)]
            if system == "Darwin"
            else ["xdg-open", str(directory)]
        )
        await self.open_path(argv)
