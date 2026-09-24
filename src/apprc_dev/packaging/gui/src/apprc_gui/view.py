"""Gradio controls for application-owned AppRC configuration."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import gradio as gr

from apprc.services.inspection import FieldInspection
from apprc.services.manager import ConfigManager, WriteScope


class ConfigEditor:
    """Render setup and settings inside an existing Gradio Blocks.

    The host owns the Blocks, server, and runtime. The editor reads files
    after each action and delegates every write to the AppRC manager.

    :param manager: Application-bound configuration manager.
    """

    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def render(self) -> None:
        """Add controls to the current Gradio container."""
        status = gr.Textbox(label="Configuration status", interactive=False)
        revision = gr.State(0)

        @gr.render(inputs=revision)
        def show_current(_revision: int) -> None:
            inspection = self.manager.inspect()
            if inspection.issues:
                gr.Markdown(
                    "### Needs attention\n"
                    + "\n".join(f"- {issue}" for issue in inspection.issues)
                )
            else:
                gr.Markdown("Configuration is ready.")
            self._render_storage(status, revision)
            scopes = self.manager.writable_scopes()
            scope = (
                gr.Dropdown(
                    choices=list(scopes),
                    value=scopes[0],
                    label="Save changes in",
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

    def _render_storage(self, status: gr.Textbox, revision: gr.State) -> None:
        """Show the selected root and actions for managed storage."""
        if not self.manager.schema.uses_storage():
            if (
                self.manager.schema.uses_user_dotenv()
                and not self.manager.paths.user_dotenv.is_file()
            ):
                gr.Button("Create user settings file").click(
                    self._setup_user,
                    inputs=revision,
                    outputs=[status, revision],
                )
            return
        gr.Markdown("### Storage")
        registry_state = self.manager.inspect_registry()
        if registry_state.error is not None:
            gr.Textbox(
                value=registry_state.error,
                label="Storage status",
                interactive=False,
            )
            return
        registry = registry_state.registry or self.manager.registry()
        if registry.storages:
            selected = gr.Dropdown(
                choices=list(registry.storages),
                value=registry.selected_storage,
                label="Selected storage",
            )
            gr.Button("Use selected storage").click(
                self._select_storage,
                inputs=[selected, revision],
                outputs=[status, revision],
            )
        name = gr.Textbox(
            value="default" if not registry.storages else "",
            label="New storage name",
        )
        root = gr.Textbox(
            value=str(self.manager.paths.root / "storage"),
            label="Storage folder",
            info="AppRC creates this folder if needed.",
        )
        gr.Button("Create and select storage", variant="primary").click(
            self._create_storage,
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
                migration = self.manager.plan_secret_migration(scope)
            except (OSError, ValueError):
                migration = None
            if migration is not None and migration.keys:
                gr.Button(f"Move {scope} secrets to private file").click(
                    partial(self._migrate_secrets, scope),
                    inputs=revision,
                    outputs=[status, revision],
                )
            secret_status = self.manager.secret_status(scope)
            if not secret_status.available:
                gr.Textbox(
                    value=secret_status.issue,
                    label=f"{scope.title()} secret file",
                    interactive=False,
                )
                gr.Button(f"Repair {scope} secret file permissions").click(
                    partial(self._repair_secrets, scope),
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
        if not item.active:
            gr.Textbox(
                value="Select storage to edit this setting.",
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
        if spec.editable and scope is not None:
            value = "" if spec.secret or item.value is None else str(item.value)
            if spec.choices and not spec.secret:
                control: gr.Textbox | gr.Dropdown = gr.Dropdown(
                    choices=list(spec.choices),
                    value=value if value in spec.choices else None,
                    label=title,
                    info=info,
                )
            else:
                control = gr.Textbox(
                    value=value,
                    label=title,
                    info=info,
                    type="password" if spec.secret else "text",
                )
            with gr.Row():
                gr.Button("Save", size="sm").click(
                    partial(self._save, key, spec.secret),
                    inputs=[control, scope, revision],
                    outputs=[status, revision],
                )
                gr.Button("Clear saved value", size="sm").click(
                    partial(self._clear, key),
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
        value: str | None,
        scope: WriteScope,
        revision: int,
    ) -> tuple[str, int]:
        """Validate and write one field without showing secret input on error."""
        if secret and not value:
            return (
                "Enter a replacement secret, or clear its saved value.",
                revision,
            )
        try:
            plan = self.manager.plan_update(key, value or "", scope=scope)
            preview = self.manager.preview_edit(plan)
            if any(
                field.issue
                for field in preview.fields
                if field.owner.env_key(field.field.name) == key
            ):
                return f"Invalid value for {key}.", revision
            self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            message = (
                f"Could not save {key}. Check its value and private file permissions."
                if secret
                else str(exc)
            )
            return message, revision
        return f"Saved {key} in the {scope} layer.", revision + 1

    def _clear(
        self, key: str, scope: WriteScope, revision: int
    ) -> tuple[str, int]:
        """Remove a saved override and inspect the remaining winning value."""
        try:
            plan = self.manager.plan_removal(key, scope=scope)
            if plan is not None:
                self.manager.preview_edit(plan)
                self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return (
            f"Cleared the saved {key} value in the {scope} layer.",
            revision + 1,
        )

    def _create_storage(
        self, name: str, root: str, revision: int
    ) -> tuple[str, int]:
        """Initialize or register one named folder through the manager."""
        if not name.strip() or not root.strip():
            return "Enter a storage name and folder.", revision
        try:
            if self.manager.registry().storages:
                self.manager.register_storage(name.strip(), Path(root))
                self.manager.select_storage(name.strip())
            else:
                self.manager.setup(
                    storage_root=Path(root), storage_name=name.strip()
                )
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Selected storage {name.strip()}.", revision + 1

    def _select_storage(self, name: str, revision: int) -> tuple[str, int]:
        """Persist the selected registered storage for later launches."""
        try:
            self.manager.select_storage(name)
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Selected storage {name}.", revision + 1

    def _setup_user(self, revision: int) -> tuple[str, int]:
        """Create the user layer for an application without storage."""
        try:
            self.manager.setup_user_dotenv()
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return "Created user settings file.", revision + 1

    def _migrate_secrets(
        self, scope: WriteScope, revision: int
    ) -> tuple[str, int]:
        """Move legacy secret assignments to their private companion."""
        try:
            self.manager.apply_secret_migration(
                self.manager.plan_secret_migration(scope)
            )
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Moved {scope} secrets to the private file.", revision + 1

    def _repair_secrets(
        self, scope: WriteScope, revision: int
    ) -> tuple[str, int]:
        """Repair a secret companion after an explicit button press."""
        try:
            self.manager.repair_secret_permissions(scope)
        except (OSError, ValueError) as exc:
            return str(exc), revision
        return f"Repaired {scope} secret file permissions.", revision + 1
