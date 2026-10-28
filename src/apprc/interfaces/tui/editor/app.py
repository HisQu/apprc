"""Interactive Textual editor for AppRC dotenv override files.

Applications declare config fields once through :mod:`apprc.definition.env_config.schema`.
This module turns those declarations into a terminal UI that inspects shell,
user dotenv, workspace dotenv, and packaged-default layers without writing files
on open.

Rendering rules for table cells live in :mod:`apprc.interfaces.tui._rendering` so
the widget code here stays focused on Textual events, modal handling, and file
persistence.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
)

from apprc.interfaces.tui._field_state import (
    ConfigWriteScope,
    SelectedField,
    config_value_sources,
    selected_field_for_row,
)
from apprc.interfaces.tui._primitives import ConfirmScreen
from apprc.interfaces.tui._rendering import (
    active_workspace_title,
    archived_workspace_title,
    build_field_table_rows,
    field_table_columns,
    live_workspace_title,
    missing_workspace_title,
)
from apprc.interfaces.tui.editor.setup import ConfigEditorSetupWorkflow
from apprc.interfaces.tui.editor.workflows import ConfigEditorWorkspaceWorkflows
from apprc.interfaces.tui.modals import (
    ConfigValueEditScreen,
    ValueEditResult,
)
from apprc.interfaces.tui.workspaces import (
    ActivePathWorkspaceSelection,
    ArchivedWorkspaceSelection,
    EditorWorkspaceSelection,
    LiveWorkspaceSelection,
    MissingWorkspaceSelection,
    NoWorkspaceSelection,
    ordered_workspace_entries,
    suggest_workspace_name,
    workspace_entry_index,
    workspace_entry_label,
)
from apprc.runtime.resolution import ResolvedConfig
from apprc.services.manager import ConfigManager
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.app_home.application import AppFiles

# == Internal ================================
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
)
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.paths import WorkspaceRootPathError
from apprc.user_files.workspace_roots.selector import (
    WorkspaceSelectorIssue,
    workspace_selector_is_path_like,
)

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


class ConfigEditorApp(App[None]):
    """Small terminal UI for editing AppRC dotenv override files."""

    CSS = """
    #workspace-list {
        width: 28;
        border: solid $primary;
    }

    #editor-pane {
        width: 1fr;
        padding: 0 1;
    }

    #selector-status {
        border: solid $warning;
        color: $warning;
        padding: 0 1;
    }

    #config-action-row {
        height: 4;
        margin: 1 0;
    }

    #config-action-row Button {
        min-width: 0;
    }

    #field-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        apprc: AppRC,
        workspace_manager: WorkspaceManager | None = None,
        manager: ConfigManager | None = None,
        workspace_registry_error: str | None = None,
        workspace_selector_issue: WorkspaceSelectorIssue | None = None,
        initial_workspace: str | None = None,
        active_workspace_root: Path | None = None,
        config_group_name: str = "config",
    ) -> None:
        """Keep workspace table and field metadata while editing dotenv state.

        :param apprc: Application config facade.
        :param manager: Captured invocation inputs, including explicit dotenv files.
        :param workspace_manager: Workspace operations supplied by the caller.
        :param workspace_registry_error: Read failure that prevents
            registry-backed workspace actions.
        :param workspace_selector_issue: Active selector failure kept separate
            from managed-file readiness.
        :param initial_workspace: Optional workspace entry selected on startup.
        :param active_workspace_root: Optional path-backed workspace selected by
            the current invocation.
        :param config_group_name: Config command group name used in generated
            guidance.
        """
        super().__init__()
        self.apprc = apprc
        self.manager = manager or apprc.manage()
        self.paths = self.manager.paths
        self.files = AppFiles(apprc.schema, self.paths)
        self.workspace_enabled = apprc.schema.uses_workspaces()
        self.registry_enabled = (
            self.workspace_enabled
            and apprc.schema.require_workspaces().registry
        )
        if self.workspace_enabled and workspace_manager is None:
            raise ValueError("Workspace controls require a WorkspaceManager.")
        if (
            workspace_manager is not None
            and workspace_manager.app_paths != self.paths
        ):
            raise ValueError(
                "ConfigManager and WorkspaceManager must share captured AppPaths."
            )
        self.workspace_manager = workspace_manager
        self.workspace_registry_error = workspace_registry_error
        self.workspace_selector_issue = workspace_selector_issue
        self.workspace_registry = (
            workspace_manager.registry()
            if self.registry_enabled
            and workspace_manager is not None
            and workspace_registry_error is None
            else None
        )
        self.owners = apprc.schema.owners
        self.initial_workspace = initial_workspace
        self.config_group_name = config_group_name
        self.user_dotenv_enabled = apprc.schema.uses_user_dotenv()
        self.init_command = (
            f"{apprc.schema.config_command_name()} workspace add NAME PATH"
            if self.registry_enabled
            else f"{apprc.schema.config_command_name()} workspace init PATH"
        )
        self.apprc_toml_label = apprc.schema.apprc_toml_filename
        self.hidden_env_keys = (
            frozenset({apprc.schema.workspace_selector_env_key})
            if apprc.schema.workspace_selector_env_key is not None
            else frozenset()
        )
        self.active_workspace_root = (
            Path(active_workspace_root).expanduser().resolve()
            if active_workspace_root is not None
            else None
        )
        self.user_dotenv_active = self._user_dotenv_is_active()
        self.workspace_entries = (
            ordered_workspace_entries(self.workspace_registry)
            if self.workspace_registry is not None
            else []
        )
        self.selection: EditorWorkspaceSelection = NoWorkspaceSelection()
        self.row_env_keys: list[str | None] = []
        self._config_action_in_progress = False
        self.workspace_workflows = ConfigEditorWorkspaceWorkflows(self)
        self.setup_workflow = ConfigEditorSetupWorkflow(self)

    def compose(self) -> ComposeResult:
        """Compose the workspace list and field editor."""
        yield Header()
        if self.workspace_selector_issue is not None:
            yield Static(
                self._workspace_selector_issue_message(),
                id="selector-status",
            )
        with Horizontal():
            if self.registry_enabled:
                yield ListView(id="workspace-list")
            with Vertical(id="editor-pane"):
                yield Static("", id="scope-title")
                with HorizontalScroll(id="config-action-row"):
                    if self._setup_needed():
                        yield Button(
                            self._setup_button_label(),
                            variant="primary",
                            id="config-setup",
                        )
                    if self.registry_enabled:
                        yield Button(
                            "New",
                            id="workspace-new",
                        )
                        yield Button(
                            "Register",
                            id="workspace-register-active",
                            disabled=True,
                        )
                        yield Button(
                            "Rename",
                            id="workspace-rename",
                            disabled=True,
                        )
                        yield Button(
                            "Reconnect",
                            id="workspace-location",
                            disabled=True,
                        )
                        yield Button(
                            "Move",
                            id="workspace-move",
                            disabled=True,
                        )
                        yield Button(
                            "Archive",
                            id="workspace-archive",
                            disabled=True,
                        )
                        yield Button(
                            "Unregister",
                            id="workspace-delete",
                            disabled=True,
                        )
                yield DataTable(id="field-table")
        yield Footer()

    async def on_mount(self) -> None:
        """Populate selectable sources and select the active one."""
        await self._refresh_workspace_list(select_name=self.initial_workspace)
        if self.workspace_registry_error is not None:
            self.notify(
                self.workspace_registry_error,
                severity="error",
                markup=False,
            )

    async def action_quit(self) -> None:
        """Keep an in-flight config action from being canceled on exit."""
        if self._config_action_in_progress:
            self.notify(
                "Finish the current config action before quitting.",
                severity="warning",
            )
            return
        await super().action_quit()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Switch the edited dotenv file when a workspace is selected."""
        if self._config_action_in_progress:
            return
        index = event.list_view.index
        if index is None or index >= len(self.workspace_entries):
            return
        entry = self.workspace_entries[index]
        if entry.kind == "live":
            self._select_workspace(entry.name)
            return
        if entry.kind == "missing":
            self._select_missing_workspace(entry.name)
            return
        self._select_archived_workspace(entry.name)
        self._start_config_action(
            lambda: (
                self.workspace_workflows.restore_or_prune_archived_workspace(
                    entry.name
                )
            )
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open a modal editor when a config field row is selected."""
        del event
        if self._config_action_in_progress:
            return
        self._open_selected_field_editor()

    def _open_selected_field_editor(self) -> None:
        """Open the modal editor for the current table row."""
        if self._config_action_in_progress:
            return
        selected = self._selected_field()
        if selected is None:
            return
        if not selected.spec.editable:
            self.notify(
                f"This setting is managed by {self.apprc_toml_label}.",
                severity="warning",
            )
            return
        env_key = selected.owner.env_key(selected.spec.name)
        self.push_screen(
            ConfigValueEditScreen(
                spec=selected.spec,
                env_key=env_key,
                value_sources=config_value_sources(
                    spec=selected.spec,
                    env_key=env_key,
                    resolved=self._inspected_resolution(),
                    include_user_dotenv=self.user_dotenv_active,
                    include_workspace=self._workspace_scope_is_active(),
                ),
                writable_scopes=self._writable_scopes(),
            ),
            self._handle_edit_result,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle config action button clicks."""
        if event.button.id == "config-setup":
            self._start_config_action(self.setup_workflow.open_setup_flow)
            return
        if event.button.id == "workspace-new":
            self._start_config_action(
                self.workspace_workflows.open_new_workspace_flow
            )
            return
        if event.button.id == "workspace-register-active":
            self._start_config_action(
                self.workspace_workflows.register_active_workspace_flow
            )
            return
        if event.button.id == "workspace-rename":
            self._start_config_action(
                self.workspace_workflows.open_rename_workspace_flow
            )
            return
        if event.button.id == "workspace-location":
            self._start_config_action(
                self.workspace_workflows.open_workspace_reconnect_flow
            )
            return
        if event.button.id == "workspace-move":
            self._start_config_action(
                self.workspace_workflows.open_move_workspace_flow
            )
            return
        if event.button.id == "workspace-delete":
            self._start_config_action(
                self.workspace_workflows.open_delete_workspace_flow
            )
            return
        if event.button.id == "workspace-archive":
            self._start_config_action(
                self.workspace_workflows.open_archive_workspace_flow
            )
            return

    def _require_workspace_registry(self) -> WorkspaceRegistry | None:
        """Return the registry needed by named-workspace actions."""
        if self.workspace_registry is None:
            message = self.workspace_registry_error or (
                "This workspace declaration does not use a registry."
            )
            self.notify(message, severity="error", markup=False)
            return None
        return self.workspace_registry

    def _start_config_action(
        self,
        workflow: Callable[[], Awaitable[None]],
    ) -> None:
        """Run one config workflow while preventing conflicting edits.

        :param workflow: Async config operation to run after the action lock
            is active.
        """
        if self._config_action_in_progress:
            self.notify(
                "Finish the current config action before starting another.",
                severity="warning",
            )
            return
        self._config_action_in_progress = True
        self._disable_config_action_controls()
        self.run_worker(
            self._run_config_action(workflow),
            group="config-actions",
        )

    async def _run_config_action(
        self,
        workflow: Callable[[], Awaitable[None]],
    ) -> None:
        """Complete a locked workflow and restore controls from selection.

        :param workflow: Async config operation that owns the active lock.
        """
        try:
            await workflow()
        finally:
            self._config_action_in_progress = False
            await self.clear_resolved_selector_issue()
            await self._refresh_workspace_list(
                select_name=self._selected_workspace_name()
            )

    def _disable_config_action_controls(self) -> None:
        """Block controls that could conflict with a config action."""
        self.query_one("#field-table", DataTable).disabled = True
        for button in self.query("#config-setup"):
            button.disabled = True
        if not self.registry_enabled:
            return
        self.query_one("#workspace-list", ListView).disabled = True
        for button_id in (
            "workspace-new",
            "workspace-register-active",
            "workspace-rename",
            "workspace-location",
            "workspace-move",
            "workspace-archive",
            "workspace-delete",
        ):
            self.query_one(f"#{button_id}", Button).disabled = True

    async def _handle_edit_result(
        self,
        result: ValueEditResult | None,
    ) -> None:
        """Persist the value returned by the edit modal."""
        if result is None:
            return
        if result.action == "clear":
            self._clear_env_key(result.env_key, scope=result.scope)
            return
        await self._save_env_key(
            result.env_key,
            result.raw_value,
            scope=result.scope,
        )

    async def _save_env_key(
        self,
        env_key: str,
        raw_value: str,
        *,
        scope: ConfigWriteScope,
    ) -> None:
        """Validate, confirm, and persist one user or workspace env value."""
        if scope == "user" and not self.user_dotenv_active:
            self.notify(
                "Set up the user dotenv before writing user-scoped values.",
                severity="error",
            )
            return
        try:
            plan = self.manager.plan_update(
                env_key,
                raw_value,
                scope=scope,
                workspace=self._inspected_workspace_selector(),
            )
        except (
            OSError,
            WorkspaceRootPathError,
            TypeError,
            ValueError,
        ) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        if not await self._confirm_env_file_edit(plan):
            return
        try:
            update = self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        self.user_dotenv_active = self._user_dotenv_is_active()
        self._populate_field_table()
        restart_notice = (
            ". Restart the application to reload configuration."
            if self._field_requires_restart(env_key)
            else ""
        )
        self.notify(f"Saved {update.env_key}{restart_notice}")

    async def _confirm_env_file_edit(self, plan: EnvFileEditPlan) -> bool:
        """Ask before disabling duplicate dotenv assignments.

        :param plan: Validated dotenv edit that may contain duplicate warnings.
        :return: Whether the caller may write the edit.
        """
        if not plan.warnings:
            return True
        action = await self.push_screen_wait(
            ConfirmScreen(
                title="Duplicate dotenv assignments",
                message=f"{plan.warnings[0]}\n\nProceed?",
                actions=(("confirm", "Proceed", "warning"),),
            )
        )
        return action == "confirm"

    def _clear_env_key(
        self,
        env_key: str,
        *,
        scope: ConfigWriteScope,
    ) -> None:
        """Remove one key from a user or workspace env file."""
        if scope == "user" and not self.user_dotenv_active:
            self.notify(
                "Set up the user dotenv before clearing user-scoped values.",
                severity="error",
            )
            return
        try:
            plan = self.manager.plan_removal(
                env_key,
                scope=scope,
                workspace=self._inspected_workspace_selector(),
            )
            update = self.manager.apply_edit(plan) if plan is not None else None
        except (
            OSError,
            WorkspaceRootPathError,
            ValueError,
        ) as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        if update is None:
            return
        self.user_dotenv_active = self._user_dotenv_is_active()
        self._populate_field_table()
        restart_notice = (
            ". Restart the application to reload configuration."
            if self._field_requires_restart(env_key)
            else ""
        )
        self.notify(f"Cleared {update.env_key}{restart_notice}")

    def _field_requires_restart(self, env_key: str) -> bool:
        """Return whether one field needs an application restart.

        :param env_key: Full environment key used to identify the field.
        :return: Whether the field declaration requires a restart.
        """
        return any(
            owner.env_key(spec.name) == env_key and spec.restart_required
            for owner in self.owners
            for spec in owner.fields
        )

    async def _refresh_workspace_list(
        self,
        *,
        select_name: str | None = None,
    ) -> None:
        """Reload workspace rows and select the requested workspace."""
        registry = self.workspace_registry if self.registry_enabled else None
        self.workspace_entries = (
            ordered_workspace_entries(registry) if registry is not None else []
        )
        if not self.registry_enabled:
            if self.active_workspace_root is not None:
                self._select_active_workspace()
            else:
                self._select_user_dotenv()
            return
        workspace_list = self.query_one("#workspace-list", ListView)
        await workspace_list.clear()
        if not self.workspace_entries:
            if self.active_workspace_root is not None:
                self._select_active_workspace()
                return
            self._select_user_dotenv()
            return
        for entry in self.workspace_entries:
            if registry is None:
                return
            await workspace_list.append(
                ListItem(Label(workspace_entry_label(registry, entry)))
            )

        selected_index = workspace_entry_index(
            self.workspace_entries, select_name
        )
        if selected_index is None:
            active_name = self._registered_active_workspace_name()
            if active_name is None and self.active_workspace_root is not None:
                self._select_active_workspace()
                return
            selected_index = workspace_entry_index(
                self.workspace_entries, active_name
            )
        if selected_index is None:
            selected_index = 0
        workspace_list.index = selected_index
        entry = self.workspace_entries[selected_index]
        if entry.kind == "live":
            self._select_workspace(entry.name)
            return
        if entry.kind == "missing":
            self._select_missing_workspace(entry.name)
            return
        self._select_archived_workspace(entry.name)

    def _select_active_workspace(self) -> None:
        """Load the env-selected active path without requiring a named row."""
        root = self.active_workspace_root
        if root is None:
            return
        self.selection = ActivePathWorkspaceSelection(root=root)
        path = self._env_file_path_for_root(root)
        if not path.is_file():
            self.query_one("#scope-title", Static).update(
                f"Workspace path: {root}\nMissing AppRC marker: {path}. "
                "Initialize workspace config before editing workspace values."
            )
            self._clear_field_table()
            self._set_workspace_controls_enabled(
                fields=False,
                register_active=False,
                rename=False,
                location=False,
                move=False,
                delete=False,
                archive=False,
            )
            return
        self.query_one("#scope-title", Static).update(
            active_workspace_title(root, path)
        )
        self._populate_field_table()
        self._set_workspace_controls_enabled(
            fields=bool(self._writable_scopes()),
            register_active=self.workspace_registry is not None,
            rename=False,
            location=False,
            move=False,
            delete=False,
            archive=False,
        )

    def _select_workspace(self, name: str) -> None:
        """Load one workspace env file and refresh the field table."""
        registry = self._require_workspace_registry()
        if registry is None:
            return
        record = registry.selected(name)
        self.selection = LiveWorkspaceSelection(record=record)
        path = self._env_file_path_for_root(record.root)
        if not path.is_file():
            self.query_one("#scope-title", Static).update(
                f"Workspace {name!r}: {record.root}\n"
                f"Missing AppRC marker: {path}. Initialize workspace config "
                "before editing workspace values."
            )
            self._clear_field_table()
            self._set_workspace_controls_enabled(
                fields=False,
                register_active=False,
                rename=True,
                location=True,
                move=True,
                delete=True,
                archive=False,
            )
            return
        self.query_one("#scope-title", Static).update(
            live_workspace_title(record, path)
        )
        self._populate_field_table()
        self._set_live_controls_enabled(True)

    async def clear_setup_status(self) -> None:
        """Remove the setup action after successful initialization.

        :return: None.
        """
        if not self._setup_needed():
            for button in self.query("#config-setup"):
                await button.remove()

    async def clear_resolved_selector_issue(self) -> None:
        """Remove the selector warning after its name becomes registered."""
        issue = self.workspace_selector_issue
        registry = self.workspace_registry
        if issue is None or issue.selector is None or registry is None:
            return
        if issue.selector.raw_value.strip() not in registry.workspaces:
            return
        self.workspace_selector_issue = None
        for status in self.query("#selector-status"):
            await status.remove()

    def _workspace_marker_setup_target(self) -> tuple[str, Path] | None:
        """Return a registered live root whose marker must be initialized."""
        selection = self.selection
        if isinstance(selection, LiveWorkspaceSelection):
            record = selection.record
        else:
            registry = self.workspace_registry
            if registry is None or not registry.workspaces:
                return None
            name = registry.selected_workspace or next(
                iter(registry.workspaces)
            )
            record = registry.workspaces.get(name)
            if record is None:
                return None
        if not record.root.is_dir():
            return None
        if self._env_file_path_for_root(record.root).is_file():
            return None
        return record.name, record.root

    def _requested_workspace_name(self) -> str | None:
        """Return a bare failed selector that setup can register by name."""
        issue = self.workspace_selector_issue
        if issue is None or issue.selector is None:
            return None
        value = issue.selector.raw_value.strip()
        if not value or workspace_selector_is_path_like(value):
            return None
        return value

    def _select_missing_workspace(self, name: str) -> None:
        """Show a registered workspace whose root no longer exists."""
        registry = self._require_workspace_registry()
        if registry is None:
            return
        record = registry.selected(name)
        self.selection = MissingWorkspaceSelection(record=record)
        self.query_one("#scope-title", Static).update(
            missing_workspace_title(record)
        )
        self._clear_field_table()
        self._set_workspace_controls_enabled(
            fields=False,
            register_active=False,
            rename=True,
            location=True,
            move=False,
            delete=True,
            archive=False,
        )

    def _select_archived_workspace(self, name: str) -> None:
        """Show archived metadata without enabling field editing."""
        registry = self._require_workspace_registry()
        if registry is None:
            return
        record = registry.archived_workspaces[name]
        self.selection = ArchivedWorkspaceSelection(record=record)
        self.query_one("#scope-title", Static).update(
            archived_workspace_title(record)
        )
        self._clear_field_table()
        self._set_live_controls_enabled(False)

    def _select_user_dotenv(self) -> None:
        """Show user, shell, and default sources without a selected workspace."""
        self._clear_selection()
        self.query_one("#scope-title", Static).update(
            self._no_workspace_message()
        )
        self._populate_field_table()
        self._set_workspace_controls_enabled(
            fields=True,
            register_active=False,
            rename=False,
            location=False,
            move=False,
            delete=False,
            archive=False,
        )

    def _populate_field_table(self) -> None:
        """Render every known config field for the active workspace."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns(
            *field_table_columns(
                include_user_dotenv=self.user_dotenv_enabled,
                include_workspace=self.workspace_enabled,
                include_explicit=bool(self.manager.options.env_files),
            )
        )
        self.row_env_keys = []
        for row in build_field_table_rows(
            resolved=self._inspected_resolution(),
            include_user_dotenv=self.user_dotenv_enabled,
            include_workspace=self.workspace_enabled,
            hidden_env_keys=self.hidden_env_keys,
        ):
            if row.height is None:
                table.add_row(*row.cells)
            else:
                table.add_row(*row.cells, height=row.height)
            self.row_env_keys.append(row.env_key)

    def _clear_field_table(self) -> None:
        """Clear the field table when no live workspace is selected."""
        table = self.query_one("#field-table", DataTable)
        table.clear(columns=True)
        self.row_env_keys = []

    def _selected_field(self) -> SelectedField | None:
        """Return the field represented by the current table cursor."""
        table = self.query_one("#field-table", DataTable)
        return selected_field_for_row(
            owners=self.owners,
            row_env_keys=self.row_env_keys,
            row_index=table.cursor_row,
        )

    def _inspected_workspace_selector(self) -> str | None:
        """Return the browsed root independently of the runtime selection."""
        if isinstance(self.selection, ActivePathWorkspaceSelection):
            return str(self.selection.root)
        if isinstance(self.selection, LiveWorkspaceSelection):
            return str(self.selection.record.root)
        return None

    def _inspected_resolution(self) -> ResolvedConfig:
        """Read current sources through shared management inspection."""
        workspace = self._inspected_workspace_selector()
        return self.manager.inspect(
            workspace=workspace, include_workspace=workspace is not None
        ).resolved

    def _current_workspace_root(self) -> Path:
        """Return the selected editable workspace root."""
        selection = self.selection
        if isinstance(selection, ActivePathWorkspaceSelection):
            return selection.root
        if isinstance(selection, LiveWorkspaceSelection):
            return selection.record.root
        raise RuntimeError("No editable workspace is selected.")

    def _env_file_path_for_root(self, root: Path) -> Path:
        """Return the editable dotenv path below one current root."""
        return self.files.workspace_dotenv_path(root.expanduser().resolve())

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable editor controls."""
        self.query_one("#field-table", DataTable).disabled = (
            self._config_action_in_progress or not enabled
        )
        for button in self.query("#config-setup"):
            button.disabled = self._config_action_in_progress

    def _set_live_controls_enabled(self, enabled: bool) -> None:
        """Enable workspace-specific controls only for live workspaces."""
        self._set_workspace_controls_enabled(
            fields=enabled,
            register_active=False,
            rename=enabled,
            location=enabled,
            move=enabled,
            delete=enabled,
            archive=enabled,
        )

    def _set_workspace_controls_enabled(
        self,
        *,
        fields: bool,
        register_active: bool,
        rename: bool,
        location: bool,
        move: bool,
        delete: bool,
        archive: bool,
    ) -> None:
        """Enable or disable each workspace-scoped editor control.

        :param fields: Whether config field rows may be edited.
        :param register_active: Whether the active path may be registered.
        :param rename: Whether the selected named workspace may be renamed.
        :param location: Whether the selected named workspace may be repointed.
        :param move: Whether the selected workspace directory may be moved.
        :param delete: Whether the current named workspace may be unregistered.
        :param archive: Whether the current workspace directory may be archived.
        """
        self._set_controls_enabled(fields)
        if not self.registry_enabled:
            return
        self.query_one(
            "#workspace-list", ListView
        ).disabled = self._config_action_in_progress
        self.query_one("#workspace-new", Button).disabled = (
            self._config_action_in_progress or self.workspace_registry is None
        )
        self.query_one("#workspace-register-active", Button).disabled = (
            self._config_action_in_progress or not register_active
        )
        self.query_one("#workspace-rename", Button).disabled = (
            self._config_action_in_progress or not rename
        )
        self.query_one("#workspace-location", Button).disabled = (
            self._config_action_in_progress or not location
        )
        self.query_one("#workspace-move", Button).disabled = (
            self._config_action_in_progress or not move
        )
        self.query_one("#workspace-delete", Button).disabled = (
            self._config_action_in_progress or not delete
        )
        self.query_one("#workspace-archive", Button).disabled = (
            self._config_action_in_progress or not archive
        )

    def _clear_selection(self) -> None:
        """Clear workspace selection and workspace values."""
        self.selection = NoWorkspaceSelection()

    def _selected_workspace_name(self) -> str | None:
        """Return the current named row for control-state restoration."""
        selection = self.selection
        if isinstance(
            selection,
            LiveWorkspaceSelection
            | MissingWorkspaceSelection
            | ArchivedWorkspaceSelection,
        ):
            return selection.record.name
        return None

    def _user_dotenv_is_active(self) -> bool:
        """Return whether the user dotenv source should be visible."""
        return (
            self.user_dotenv_enabled and self.files.user_dotenv_path().is_file()
        )

    def _workspace_scope_is_active(self) -> bool:
        """Return whether the selection has an initialized workspace env."""
        return (
            isinstance(
                self.selection,
                ActivePathWorkspaceSelection | LiveWorkspaceSelection,
            )
            and self._env_file_path_for_root(
                self._current_workspace_root()
            ).is_file()
        )

    def _writable_scopes(self) -> tuple[ConfigWriteScope, ...]:
        """Return write scopes currently available for the selected field."""
        return self.manager.writable_scopes(
            workspace=self._inspected_workspace_selector(),
            include_workspace=self._workspace_scope_is_active(),
        )

    def _registered_active_workspace_name(self) -> str | None:
        """Return the named workspace that matches the active path, if any."""
        if (
            self.active_workspace_root is None
            or self.workspace_registry is None
        ):
            return None
        for name in sorted(self.workspace_registry.workspaces):
            record = self.workspace_registry.workspaces[name]
            record_root = Path(record.root).expanduser().resolve()
            if record_root == self.active_workspace_root:
                return name
        return None

    def _suggest_workspace_name(self, path: Path) -> str:
        """Return a simple workspace-name suggestion from a path."""
        return suggest_workspace_name(
            path,
            fallback_name=self.apprc.schema.app_id,
        )

    def _no_workspace_message(self) -> str:
        """Return guidance when no workspace row or path is selected."""
        if not self.workspace_enabled:
            return self._user_dotenv_message()
        if self.user_dotenv_active and self.active_workspace_root is None:
            return f"{self._user_dotenv_message()}\n\nNo workspace is selected."
        selector_env_key = (
            self.apprc.schema.require_workspace_selector_env_key()
        )
        if self.workspace_registry is not None:
            return (
                "No workspaces are registered. Use New to add one, or set "
                f"{selector_env_key} to a registered name or initialized path.\n"
                f"CLI: {self.init_command}"
            )
        return (
            "No workspace is selected. Set "
            f"{selector_env_key} to an initialized directory path."
        )

    def _user_dotenv_message(self) -> str:
        """Return source guidance for the per-user dotenv."""
        if self.user_dotenv_active:
            return f"User dotenv:\n{self.files.user_dotenv_path()}"
        if self.user_dotenv_enabled:
            return (
                "The user dotenv is not set up.\n"
                f"Proposed path: {self.files.user_dotenv_path()}\n"
                f"Run {self.apprc.schema.config_command_name()} "
                f"{self.config_group_name} setup or choose Set up user "
                "dotenv."
            )
        return (
            "This application reads process environment values and defaults. "
            "It does not declare a user dotenv."
        )

    def _setup_needed(self) -> bool:
        """Return whether a declared managed feature needs initialization."""
        user_missing = self.user_dotenv_enabled and not self.user_dotenv_active
        return user_missing or self._workspace_setup_needed()

    def _workspace_setup_needed(self) -> bool:
        """Return whether the declared workspace feature needs initialization."""
        if not self.workspace_enabled:
            return False
        if self.workspace_registry_error is not None:
            return False
        registry = self.workspace_registry
        if self.active_workspace_root is not None:
            registered = registry is not None and any(
                record.root.expanduser().resolve() == self.active_workspace_root
                for record in registry.workspaces.values()
            )
            if registered and not self.active_workspace_root.is_dir():
                return False
            return not self._env_file_path_for_root(
                self.active_workspace_root
            ).is_file()
        if registry is None or not registry.workspaces:
            return True
        selected_name = registry.selected_workspace or next(
            iter(registry.workspaces)
        )
        record = registry.workspaces.get(selected_name)
        if record is None or not record.root.is_dir():
            return False
        return not self._env_file_path_for_root(record.root).is_file()

    def _setup_button_label(self) -> str:
        """Return a setup action that names the missing capability."""
        user_missing = self.user_dotenv_enabled and not self.user_dotenv_active
        workspace_missing = self._workspace_setup_needed()
        if user_missing and workspace_missing:
            return "Set up user dotenv and workspace..."
        if user_missing:
            return "Set up user dotenv..."
        if workspace_missing:
            if self.workspace_registry and self.workspace_registry.workspaces:
                return "Initialize workspace config..."
            return "Set up workspace..."
        return "Finish setup..."

    def _workspace_selector_issue_message(self) -> str:
        """Explain one selector failure without claiming setup is damaged."""
        issue = self.workspace_selector_issue
        if issue is None:
            return ""
        selector = issue.selector
        lines = ["Workspace selection needs attention:", issue.message]
        if selector is not None:
            source_labels = {
                "cli": "command-line --workspace",
                "process_environment": (
                    f"{selector.source} from the process environment"
                ),
                "explicit_dotenv": (
                    f"{selector.source} from an explicit dotenv file"
                ),
                "registry": "apprc.toml selected_workspace",
            }
            lines.append(f"Source: {source_labels[selector.source_kind]}.")
            if (
                selector.source_kind != "registry"
                and issue.configured_workspace is not None
            ):
                lines.append(
                    f"This value overrides selected_workspace="
                    f"{issue.configured_workspace!r}."
                )
        registry = self.workspace_registry
        if registry is not None and registry.workspaces:
            lines.append(
                "Registered workspaces: "
                + ", ".join(sorted(registry.workspaces))
                + "."
            )
            lines.append(
                "Select a registered workspace below to inspect it. This does "
                "not change the runtime selector."
            )
        lines.append(
            "Register or rename the requested workspace, or change/unset the "
            "selector at its source. Setup is not a selector repair."
        )
        return "\n".join(lines)
