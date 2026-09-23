"""Reusable Toga view for setup and editing AppRC-managed layers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import toga

from apprc.services.inspection import ConfigInspection, FieldInspection
from apprc.services.manager import ConfigManager, WriteScope


class ConfigView:
    """Show one AppRC declaration inside an application-owned Toga window.

    The view owns widgets and prompts. ``ConfigManager`` remains responsible
    for every read, setup action, preview, and write.

    :param manager: Application-bound manager captured from one ``AppRC``.
    :param window: Host window used for the native folder chooser.
    :param on_change: Called with refreshed inspection after any view change.
    """

    def __init__(
        self,
        manager: ConfigManager,
        window: toga.Window,
        *,
        on_change: Callable[[ConfigInspection], None] | None = None,
    ) -> None:
        self.manager = manager
        self.window = window
        self.on_change = on_change
        self.widget = toga.ScrollContainer(horizontal=False)
        self.inspection = manager.inspect()
        self._error = ""
        self._scope_select: toga.Selection | None = None
        self.refresh()

    def refresh(self) -> None:
        """Read current files and redraw the user and storage controls."""
        self.inspection = self.manager.inspect()
        root = toga.Column()
        root.add(toga.Label(f"{self.manager.schema.display_name} settings"))
        if self._error:
            root.add(toga.Label(self._error))
        if self.inspection.issues:
            root.add(
                toga.Label(
                    "Needs attention: " + "; ".join(self.inspection.issues)
                )
            )
        else:
            root.add(toga.Label("Configuration is ready."))
        root.add(
            toga.Label(
                "Saved secret settings stay in a private file beside the selected settings layer. "
                "AppRC does not upload them."
            )
        )
        self._add_storage_controls(root)
        self._add_scope_control(root)
        for owner in self.manager.schema.owners:
            root.add(toga.Label(owner.title or owner.key))
            for item in self.inspection.fields:
                if item.owner.key == owner.key:
                    self._add_field(root, item)
        self.widget.content = root
        if self.on_change is not None:
            self.on_change(self.inspection)

    def _add_storage_controls(self, root: toga.Box) -> None:
        """Let users initialize and select named storage without app policy."""
        if not self.manager.schema.uses_storage():
            if (
                self.manager.schema.uses_user_dotenv()
                and not self.manager.paths.user_dotenv.is_file()
            ):
                root.add(
                    toga.Button(
                        "Create user settings file", on_press=self._setup_user
                    )
                )
            return
        root.add(toga.Label("Storage"))
        registry_state = self.manager.inspect_registry()
        if registry_state.error is not None or registry_state.registry is None:
            root.add(
                toga.Label(
                    registry_state.error or "Storage registry is unavailable."
                )
            )
            return
        registry = registry_state.registry
        if registry.storages:
            selection = self.inspection.resolved.selection
            if (
                selection is not None
                and selection.source != "apprc.toml selected_storage"
            ):
                root.add(
                    toga.Label(
                        f"This run uses {selection.storage_name or selection.root.name} "
                        f"from {selection.source}; it overrides the saved default."
                    )
                )
            names = list(registry.storages)
            selected = toga.Selection(
                items=names, value=registry.selected_storage
            )
            root.add(selected)
            root.add(
                toga.Button(
                    "Use selected storage",
                    on_press=lambda _widget: self._select_storage(selected),
                )
            )
        name_input = toga.TextInput(
            value="default" if not registry.storages else ""
        )
        root.add(toga.Label("Name for a new storage"))
        root.add(name_input)
        root.add(
            toga.Button(
                "Choose storage folder",
                on_press=self._folder_handler(name_input),
            )
        )

    def _folder_handler(
        self, name_input: toga.TextInput
    ) -> Callable[..., object]:
        """Return an async handler bound to the visible storage name."""

        async def choose(_widget: toga.Widget) -> None:
            await self._choose_storage(name_input)

        return choose

    def _add_scope_control(self, root: toga.Box) -> None:
        """Show which saved layer the following edit buttons will change."""
        scopes = self.manager.writable_scopes()
        if scopes:
            root.add(toga.Label("Save changes in"))
            previous = (
                None if self._scope_select is None else self._scope_select.value
            )
            self._scope_select = toga.Selection(
                items=list(scopes),
                value=previous if previous in scopes else scopes[0],
            )
            root.add(self._scope_select)
            for scope in scopes:
                self._add_secret_controls(root, scope)
        else:
            self._scope_select = None

    def _add_secret_controls(self, root: toga.Box, scope: WriteScope) -> None:
        """Offer explicit migration and permission repair for a saved layer."""
        try:
            plan = self.manager.plan_secret_migration(scope)
        except (OSError, ValueError) as exc:
            root.add(toga.Label(f"{scope.title()} secret migration: {exc}"))
            plan = None
        if plan is not None and plan.keys:
            root.add(
                toga.Label(
                    f"{scope.title()} settings have secret values in the ordinary file: "
                    + ", ".join(plan.keys)
                )
            )
            root.add(
                toga.Button(
                    f"Move {scope} secrets to private file",
                    on_press=lambda _widget: self._migrate_secrets(scope),
                )
            )
        status = self.manager.secret_status(scope)
        if not status.available:
            root.add(
                toga.Label(f"{scope.title()} secret saving: {status.issue}")
            )
            root.add(
                toga.Button(
                    f"Repair {scope} secret file permissions",
                    on_press=lambda _widget: self._repair_secrets(scope),
                )
            )

    def _add_field(self, root: toga.Box, item: FieldInspection) -> None:
        """Show field documentation, effective source, and edit actions."""
        spec = item.field
        key = item.owner.env_key(spec.name)
        root.add(toga.Label(spec.title or key))
        if spec.explanation_short:
            root.add(toga.Label(spec.explanation_short))
        if (
            spec.explanation_long
            and spec.explanation_long != spec.explanation_short
        ):
            root.add(toga.Label(spec.explanation_long))
        if not item.active:
            root.add(toga.Label("Select storage to edit this setting."))
            return
        source = (
            item.origin.path.name if item.origin.path else item.origin.origin
        )
        root.add(toga.Label(f"Effective source: {source}"))
        if item.issue:
            root.add(toga.Label(item.issue))
        if spec.secret:
            root.add(
                toga.Label(
                    "A value is set." if item.value else "No value is set."
                )
            )
        else:
            root.add(toga.Label(f"Effective value: {item.display_value}"))
        if not spec.editable:
            return
        if spec.secret:
            control: toga.TextInput | toga.PasswordInput | toga.Selection = (
                toga.PasswordInput(placeholder="Enter a replacement value")
            )
        elif spec.choices:
            control = toga.Selection(items=["", *spec.choices])
        else:
            control = toga.TextInput(placeholder="Enter a new value")
        root.add(control)
        available = self._scope_select is not None
        root.add(
            toga.Row(
                children=[
                    toga.Button(
                        "Save",
                        enabled=available,
                        on_press=lambda _widget: self._save(key, control),
                    ),
                    toga.Button(
                        "Clear saved value",
                        enabled=available,
                        on_press=lambda _widget: self._clear(key),
                    ),
                ]
            )
        )

    def _selected_scope(self) -> WriteScope:
        """Return the edit target currently shown above the fields."""
        if self._scope_select is None or self._scope_select.value not in (
            "user",
            "storage",
        ):
            raise ValueError("Run setup before saving settings.")
        return "user" if self._scope_select.value == "user" else "storage"

    def _save(
        self,
        key: str,
        control: toga.TextInput | toga.PasswordInput | toga.Selection,
    ) -> None:
        """Preview and apply one field edit through the shared manager."""
        value = control.value
        if value is None or str(value) == "":
            self._show_error("Enter a value, or use Clear saved value.")
            return
        try:
            plan = self.manager.plan_update(
                key, str(value), scope=self._selected_scope()
            )
            self.manager.preview_edit(plan)
            self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            if isinstance(control, toga.PasswordInput):
                self._show_error(
                    f"Could not save {key}. Check its value and secret file permissions."
                )
            else:
                self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    def _clear(self, key: str) -> None:
        """Remove one saved override while preserving higher-priority layers."""
        try:
            plan = self.manager.plan_removal(key, scope=self._selected_scope())
            if plan is not None:
                self.manager.preview_edit(plan)
                self.manager.apply_edit(plan)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    def _setup_user(self, _widget: toga.Widget) -> None:
        """Create the declared user layer when storage is not enabled."""
        try:
            self.manager.setup_user_dotenv()
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    async def _choose_storage(self, name_input: toga.TextInput) -> None:
        """Ask the host window for a directory, then initialize it."""
        root = await self.window.dialog(
            toga.SelectFolderDialog("Choose storage folder")
        )
        if root is None:
            return
        name = (name_input.value or "").strip()
        if not name:
            self._show_error("Enter a storage name first.")
            return
        try:
            if self.manager.registry().storages:
                self.manager.register_storage(name, Path(root))
                self.manager.select_storage(name)
            else:
                self.manager.setup(storage_root=Path(root), storage_name=name)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    def _select_storage(self, selected: toga.Selection) -> None:
        """Save the selected registry name for subsequent launches."""
        if selected.value is None:
            return
        try:
            self.manager.select_storage(str(selected.value))
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    def _show_error(self, message: str) -> None:
        """Show an actionable error without logging field input values."""
        self._error = message
        self.refresh()

    def _migrate_secrets(self, scope: WriteScope) -> None:
        """Move legacy values after a visible, scope-specific button press."""
        try:
            self.manager.apply_secret_migration(
                self.manager.plan_secret_migration(scope)
            )
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()

    def _repair_secrets(self, scope: WriteScope) -> None:
        """Change permissions only after the user presses Repair."""
        try:
            self.manager.repair_secret_permissions(scope)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._error = ""
        self.refresh()
