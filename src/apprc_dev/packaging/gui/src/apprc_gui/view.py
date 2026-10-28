"""Gradio controls for application-owned AppRC configuration."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import gradio as gr

from apprc.services.inspection import FieldInspection
from apprc.services.manager import ConfigManager, WriteScope
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.app_home.application import AppFiles


class ConfigEditor:
    """Render setup and settings inside an existing Gradio Blocks.

    The host owns the Blocks, server, and runtime. The editor reads files
    after each action, delegates field edits to the configuration manager,
    and delegates registry operations to the workspace manager.

    :param manager: Application-bound configuration manager.
    :param workspace_manager: Optional manager for registry-backed workspaces.
    """

    def __init__(
        self,
        manager: ConfigManager,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.manager = manager
        self.workspace_manager = workspace_manager
        self.selected_workspace = manager.options.workspace

    def render(self) -> None:
        """Add controls to the current Gradio container."""
        status = gr.Textbox(label="Configuration status", interactive=False)
        revision = gr.State(0)

        @gr.render(inputs=revision)
        def show_current(_revision: int) -> None:
            inspection = self.manager.inspect(workspace=self.selected_workspace)
            if inspection.issues:
                gr.Markdown(
                    "### Needs attention\n"
                    + "\n".join(f"- {issue}" for issue in inspection.issues)
                )
            else:
                gr.Markdown("Configuration is ready.")
            self._render_workspace(status, revision)
            scopes = self.manager.writable_scopes(
                workspace=self.selected_workspace
            )
            scope = (
                gr.Dropdown(
                    choices=list(scopes),
                    value=scopes[0],
                    label="Save changes in",
                    interactive=True,
                )
                if scopes
                else None
            )
            if scope is not None:
                self._render_secret_actions(scopes, status, revision)
            for owner in self.manager.schema.owners:
                gr.Markdown(f"### {owner.title or owner.key}")
                for item in inspection.fields:
                    if item.owner.key == owner.key:
                        self._render_field(item, scope, status, revision)

    def _render_workspace(self, status: gr.Textbox, revision: gr.State) -> None:
        """Show the selected workspace and registry-backed workspace actions."""
        if not self.manager.schema.uses_workspaces():
            if (
                self.manager.schema.uses_user_dotenv()
                and not AppFiles(self.manager.schema, self.manager.paths)
                .user_dotenv_path()
                .is_file()
            ):
                gr.Button("Create user settings file").click(
                    self._setup_user,
                    inputs=revision,
                    outputs=[status, revision],
                )
            return
        workspaces = self.manager.schema.workspaces
        if workspaces is None or not workspaces.registry:
            return
        if self.workspace_manager is None:
            raise ValueError(
                "Registry-backed workspace UI requires a WorkspaceManager."
            )
        gr.Markdown("### Workspace")
        registry_state = self.workspace_manager.inspect_registry()
        if registry_state.error is not None:
            gr.Textbox(
                value=registry_state.error,
                label="Workspace status",
                interactive=False,
            )
            return
        registry = registry_state.registry or self.workspace_manager.registry()
        if self.selected_workspace is None:
            self.selected_workspace = registry.selected_workspace
        if registry.workspaces:
            selected = gr.Dropdown(
                choices=list(registry.workspaces),
                value=self.selected_workspace,
                label="Selected workspace",
                interactive=True,
            )
            gr.Button("Use selected workspace").click(
                self._select_workspace,
                inputs=[selected, revision],
                outputs=[status, revision],
            )
        name = gr.Textbox(
            value="default" if not registry.workspaces else "",
            label="New workspace name",
            interactive=True,
        )
        root = gr.Textbox(
            value=str(self.manager.paths.require("config") / "workspaces"),
            label="Workspace folder",
            info="AppRC creates this folder if needed.",
            interactive=True,
        )
        gr.Button("Create and select workspace", variant="primary").click(
            self._create_workspace,
            inputs=[name, root, revision],
            outputs=[status, revision],
        )

    def _render_secret_actions(
        self,
        scopes: tuple[WriteScope, ...],
        status: gr.Textbox,
        revision: gr.State,
    ) -> None:
        """Keep legacy secret migration and permission repair available."""
        for scope in scopes:
            try:
                migration = self.manager.plan_secret_migration(
                    scope, workspace=self.selected_workspace
                )
            except (OSError, ValueError):
                migration = None
            if migration is not None and migration.keys:
                gr.Button(f"Move {scope} secrets to private file").click(
                    partial(
                        self._migrate_secrets,
                        scope,
                        self.selected_workspace,
                    ),
                    inputs=revision,
                    outputs=[status, revision],
                )
            secret_status = self.manager.secret_status(
                scope, workspace=self.selected_workspace
            )
            if not secret_status.available:
                gr.Textbox(
                    value=secret_status.issue,
                    label=f"{scope.title()} secret file",
                    interactive=False,
                )
                gr.Button(f"Repair {scope} secret file permissions").click(
                    partial(
                        self._repair_secrets,
                        scope,
                        self.selected_workspace,
                    ),
                    inputs=revision,
                    outputs=[status, revision],
                )

    def _render_field(
        self,
        item: FieldInspection,
        scope: gr.Dropdown | None,
        status: gr.Textbox,
        revision: gr.State,
    ) -> None:
        """Show a declared value, its winning source, and edit actions."""
        spec = item.field
        key = item.owner.env_key(spec.name)
        title = spec.title or key
        if spec.restart_required:
            title = f"{title} (restart required)"
        if not item.active:
            gr.Textbox(
                value="Select a workspace to edit this setting.",
                label=title,
                interactive=False,
            )
            return
        source = (
            item.origin.path.name if item.origin.path else item.origin.origin
        )
        info = f"{spec.explanation_long or spec.explanation_short or ''} Effective source: {source}.".strip()
        if item.issue:
            info = f"{info} {item.issue}"
        if spec.secret:
            info = f"{info} {'A value is set.' if item.value else 'No value is set.'}"
        if spec.restart_required:
            info = (
                f"{info} Restart the application to load saved settings "
                "after changing this setting."
            )
        if spec.editable and scope is not None:
            value = "" if spec.secret or item.value is None else str(item.value)
            if spec.choices and not spec.secret:
                control: gr.Textbox | gr.Dropdown = gr.Dropdown(
                    choices=list(spec.choices),
                    value=value if value in spec.choices else None,
                    label=title,
                    info=info,
                    interactive=True,
                )
            else:
                control = gr.Textbox(
                    value=value,
                    label=title,
                    info=info,
                    type="password" if spec.secret else "text",
                    interactive=True,
                )
            with gr.Row():
                gr.Button("Save", size="sm").click(
                    partial(
                        self._save,
                        key,
                        spec.secret,
                        spec.restart_required,
                        workspace=self.selected_workspace,
                    ),
                    inputs=[control, scope, revision],
                    outputs=[status, revision],
                )
                gr.Button("Clear saved value", size="sm").click(
                    partial(
                        self._clear,
                        key,
                        spec.restart_required,
                        workspace=self.selected_workspace,
                    ),
                    inputs=[scope, revision],
                    outputs=[status, revision],
                )
        else:
            gr.Textbox(
                value="<redacted>" if spec.secret else str(item.display_value),
                label=title,
                info=info,
                interactive=False,
            )

    def _save(
        self,
        key: str,
        secret: bool,
        restart_required: bool,
        value: str | None,
        scope: WriteScope,
        revision: int,
        *,
        workspace: str | None = None,
    ) -> tuple[str, int]:
        """Validate and write one field without showing secret input on error."""
        if secret and not value:
            return (
                "Enter a replacement secret, or clear its saved value.",
                revision,
            )
        if secret:
            try:
                secret_status = self.manager.secret_status(
                    scope, workspace=workspace
                )
            except (OSError, ValueError):
                return (
                    f"Could not inspect the private file for {key}. Review its "
                    f"directory permissions, then run `config secrets repair "
                    f"--scope {scope}`.",
                    revision,
                )
            if not secret_status.available:
                issue = secret_status.issue or "The secret file is unavailable."
                next_step = (
                    "Move or remove the file blocking the layer directory, "
                    "then run setup again."
                    if issue == "The parent path exists but is not a directory."
                    else f"Review the directory permissions, then run `config "
                    f"secrets repair --scope {scope}`."
                )
                return (
                    f"Cannot save {key}: {issue} {next_step}",
                    revision,
                )
        try:
            plan = self.manager.plan_update(
                key, value or "", scope=scope, workspace=workspace
            )
            preview = self.manager.preview_edit(plan, workspace=workspace)
            if any(
                field.issue
                for field in preview.fields
                if field.owner.env_key(field.field.name) == key
            ):
                return f"Invalid value for {key}.", revision
            self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            message = (
                f"Could not save {key}. Check its value. If the secret file is "
                f"unavailable, review its directory permissions and run "
                f"`config secrets repair --scope {scope}`."
                if secret
                else str(exc)
            )
            return message, revision
        restart_notice = (
            " Restart the application to reload configuration."
            if restart_required
            else ""
        )
        return (
            f"Saved {key} in the {scope} layer.{restart_notice}",
            revision + 1,
        )

    def _clear(
        self,
        key: str,
        restart_required: bool,
        scope: WriteScope,
        revision: int,
        *,
        workspace: str | None = None,
    ) -> tuple[str, int]:
        """Remove a saved override and inspect the remaining winning value."""
        try:
            plan = self.manager.plan_removal(
                key, scope=scope, workspace=workspace
            )
            if plan is None:
                return (
                    f"No saved {key} value in the {scope} layer.",
                    revision,
                )
            self.manager.preview_edit(plan, workspace=workspace)
            self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            return str(exc), revision
        restart_notice = (
            " Restart the application to reload configuration."
            if restart_required
            else ""
        )
        return (
            f"Cleared the saved {key} value in the {scope} layer."
            f"{restart_notice}",
            revision + 1,
        )

    def _create_workspace(
        self, name: str, root: str, revision: int
    ) -> tuple[str, int]:
        """Initialize or register one named workspace through its managers."""
        if not name.strip() or not root.strip():
            return "Enter a workspace name and folder.", revision
        if self.workspace_manager is None:
            raise ValueError(
                "Workspace management requires a WorkspaceManager."
            )
        try:
            self.workspace_manager.register_workspace(name.strip(), Path(root))
            self.workspace_manager.select_workspace(name.strip())
            self.selected_workspace = name.strip()
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Selected workspace {name.strip()}.", revision + 1

    def _select_workspace(self, name: str, revision: int) -> tuple[str, int]:
        """Persist the selected registered workspace for later launches."""
        if self.workspace_manager is None:
            raise ValueError(
                "Workspace management requires a WorkspaceManager."
            )
        try:
            self.workspace_manager.select_workspace(name)
            self.selected_workspace = name
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Selected workspace {name}.", revision + 1

    def _setup_user(self, revision: int) -> tuple[str, int]:
        """Create the user layer for an application without workspaces."""
        try:
            self.manager.setup()
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return "Created user settings file.", revision + 1

    def _migrate_secrets(
        self, scope: WriteScope, workspace: str | None, revision: int
    ) -> tuple[str, int]:
        """Move legacy secret assignments to their private companion."""
        try:
            self.manager.apply_secret_migration(
                self.manager.plan_secret_migration(scope, workspace=workspace)
            )
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Moved {scope} secrets to the private file.", revision + 1

    def _repair_secrets(
        self, scope: WriteScope, workspace: str | None, revision: int
    ) -> tuple[str, int]:
        """Repair a secret companion after an explicit button press."""
        try:
            secret_status = self.manager.repair_secret_permissions(
                scope, workspace=workspace
            )
        except (OSError, ValueError) as exc:
            return str(exc), revision
        if not secret_status.available:
            issue = (
                secret_status.issue or "The secret file remains unavailable."
            )
            next_step = (
                "Remove or move the existing non-file secret path, then try again."
                if issue == "The secret path is not a file."
                else "Review the reported directory or file permissions, then try again."
            )
            return (
                f"Could not repair {scope} secret file: {issue} {next_step}",
                revision,
            )
        return f"Repaired {scope} secret file permissions.", revision + 1
