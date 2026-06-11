"""Textual setup wizard for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ===============================
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.visual import VisualType
from textual.widgets import Button, Footer, Header, Static

# == Internal ================================
import apprc.config.setup.flow as setup_flow
import apprc.config.setup.text as setup_text
from apprc.config.storage.registry import StorageRegistry, ordered_storage_names
from apprc.config.tui.primitives import (
    ButtonVariant,
    ConfirmScreen,
    PathInputScreen,
    StorageNameScreen,
)
from apprc.config.tui.styles import (
    ENV_KEY_STYLE,
    PATH_STYLE,
    lines_text,
    path_markup,
    path_text,
    storage_name_text,
    style_literals,
)

if TYPE_CHECKING:
    from apprc.config.kit import AppConfigKit


class ConfigSetupApp(App[setup_flow.ConfigSetupResult | None]):
    """Textual wizard for registry and default-storage setup."""

    CSS = """
    #setup-pane {
        padding: 1 2;
    }

    #setup-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #setup-body {
        height: 1fr;
    }

    #setup-actions {
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, *, kit: "AppConfigKit") -> None:
        """Store the application facade used by the wizard.

        :param kit: Application config facade mounted by the host CLI.
        """
        super().__init__()
        self.kit = kit
        self.registry: StorageRegistry | None = None
        self.existing_action: setup_flow.ExistingSetupAction | None = None
        self.result: setup_flow.ConfigSetupResult | None = None

    def compose(self) -> ComposeResult:
        """Compose the setup wizard shell.

        :return: Header, body panel, action row, and footer widgets.
        """
        yield Header()
        with Vertical(id="setup-pane"):
            yield Static("", id="setup-title")
            yield Static("", id="setup-body")
            yield Horizontal(id="setup-actions")
        yield Footer()

    async def on_mount(self) -> None:
        """Show the setup overview as the first screen."""
        await self._show_overview()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dispatch setup wizard actions.

        :param event: Textual button event.
        """
        button_id = event.button.id
        if button_id in {"setup-cancel", "finish-close"}:
            self.exit(self.result)
            return
        if button_id == "setup-start":
            self.run_worker(self._start_setup(), exclusive=True)
            return
        if button_id in {"existing-keep", "existing-reset", "existing-move"}:
            action = setup_flow.ExistingSetupAction(
                str(button_id).removeprefix("existing-")
            )
            self.run_worker(
                self._handle_existing_registry(action),
                exclusive=True,
            )

    async def _show_overview(self) -> None:
        """Render the first setup screen."""
        paths = setup_text.setup_paths(self.kit)
        active_paths = () if paths.active is None else (paths.active,)
        await self._set_screen(
            title=f"{self.kit.spec.display_name} config setup",
            body=self._style_setup_text(
                setup_text.setup_overview_text(self.kit),
                paths=active_paths,
            ),
            buttons=(
                ("setup-start", "Start setup", "primary"),
                ("setup-cancel", "Cancel", "default"),
            ),
        )

    async def _start_setup(self) -> None:
        """Load any existing registry or start fresh AppRC TOML selection."""
        existing_path = setup_flow.find_existing_apprc_toml_path(self.kit)
        if existing_path is None:
            registry = await self._choose_new_registry()
            if registry is not None:
                await self._ensure_default_storage(registry)
            return
        try:
            registry = setup_flow.load_registry(self.kit, existing_path)
        except setup_flow.ConfigSetupError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        self.registry = registry
        default_action = setup_flow.default_existing_setup_action()
        await self._show_existing_registry(registry, default_action)

    async def _show_existing_registry(
        self,
        registry: StorageRegistry,
        default_action: setup_flow.ExistingSetupAction,
    ) -> None:
        """Render existing-registry choices.

        :param registry: Registry discovered by setup.
        :param default_action: Action that mirrors legacy setup defaults.
        """
        buttons: list[tuple[str, str, ButtonVariant]] = []
        labels = {
            setup_flow.ExistingSetupAction.KEEP: "Keep",
            setup_flow.ExistingSetupAction.RESET: "Reset",
            setup_flow.ExistingSetupAction.MOVE: "Move",
        }
        for action in setup_flow.ExistingSetupAction:
            variant: ButtonVariant = (
                "primary" if action == default_action else "default"
            )
            buttons.append(
                (f"existing-{action.value}", labels[action], variant)
            )
        buttons.append(("setup-cancel", "Cancel", "default"))
        await self._set_screen(
            title="Existing setup",
            body=self._style_registry_text(
                setup_text.existing_registry_text(self.kit, registry),
                registry,
            ),
            buttons=tuple(buttons),
        )

    async def _handle_existing_registry(
        self,
        action: setup_flow.ExistingSetupAction,
    ) -> None:
        """Apply one existing-registry action.

        :param action: User-selected existing setup behavior.
        """
        registry = self.registry
        if registry is None:
            return
        self.existing_action = action
        try:
            if action == setup_flow.ExistingSetupAction.KEEP:
                setup_flow.require_apprc_toml_path_available(
                    registry.path,
                )
                await self._ensure_default_storage(registry)
                return
            if action == setup_flow.ExistingSetupAction.RESET:
                confirmed = await self.push_screen_wait(
                    ConfirmScreen(
                        title="Reset config state",
                        message=self._style_registry_text(
                            setup_text.reset_warning_text(
                                self.kit,
                                registry,
                            ),
                            registry,
                        ),
                        actions=(("reset", "Reset", "warning"),),
                    )
                )
                if confirmed != "reset":
                    return
                setup_flow.remove_apprc_toml_config_state(registry.path)
                fresh = await self._choose_new_registry()
                if fresh is not None:
                    await self._ensure_default_storage(fresh)
                return
            moved = await self._move_existing_apprc_toml(registry)
        except setup_flow.ConfigSetupError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        if moved is not None:
            await self._ensure_default_storage(moved)

    async def _choose_new_registry(self) -> StorageRegistry | None:
        """Prompt for the AppRC directory and load the computed TOML file.

        :return: Empty or parsed registry at the selected AppRC TOML path.
        """
        apprc_dir = await self._choose_apprc_dir(
            default_dir=self._default_apprc_dir(),
            title=setup_text.apprc_dir_label(self.kit),
        )
        if apprc_dir is None:
            return None
        apprc_toml_path = setup_flow.setup_apprc_toml_path_from_dir(
            self.kit,
            apprc_dir,
        )
        try:
            return setup_flow.load_registry(self.kit, apprc_toml_path)
        except setup_flow.ConfigSetupError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return None

    async def _move_existing_apprc_toml(
        self,
        registry: StorageRegistry,
    ) -> StorageRegistry | None:
        """Prompt for a move target and move the AppRC TOML file.

        :param registry: Existing registry to move.
        :return: Registry loaded from the move target, or ``None``.
        """
        target_dir = await self._choose_apprc_dir(
            default_dir=registry.path.parent,
            title="Move AppRC TOML",
        )
        if target_dir is None:
            return None
        target_path = setup_flow.setup_apprc_toml_path_from_dir(
            self.kit,
            target_dir,
        )
        replace = False
        if target_path.exists() and not setup_flow.same_path(
            registry.path,
            target_path,
        ):
            if target_path.is_dir():
                self.notify(
                    "AppRC TOML target is a directory: "
                    f"{path_markup(target_path)}",
                    severity="error",
                )
                return None
            action = await self.push_screen_wait(
                ConfirmScreen(
                    title="Replace AppRC TOML?",
                    message=lines_text(
                        "Replace existing AppRC TOML?",
                        path_text(target_path),
                    ),
                    actions=(("replace", "Replace", "warning"),),
                )
            )
            replace = action == "replace"
            if not replace:
                return None
        try:
            return setup_flow.move_existing_apprc_toml(
                self.kit,
                source_path=registry.path,
                target_path=target_path,
                replace_existing_file=replace,
            )
        except setup_flow.ConfigSetupError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return None

    async def _choose_apprc_dir(
        self,
        *,
        default_dir: Path | None,
        title: str,
    ) -> Path | None:
        """Prompt until the user picks a usable AppRC directory.

        :param default_dir: Prefilled AppRC directory.
        :param title: Modal title.
        :return: Normalized AppRC directory, or ``None`` when canceled.
        """
        while True:
            result = await self.push_screen_wait(
                PathInputScreen(
                    title=title,
                    message=self._style_apprc_dir_step_text(
                        default_dir,
                    ),
                    placeholder=f"{self.kit.spec.display_name} directory",
                    value="" if default_dir is None else str(default_dir),
                )
            )
            if result is None:
                return None
            try:
                return setup_flow.setup_apprc_toml_dir(result.path)
            except setup_flow.ConfigSetupError as exc:
                self.notify(str(exc), severity="error", markup=False)
                continue

    def _default_apprc_dir(self) -> Path | None:
        """Return the env-selected AppRC TOML parent directory, if known."""
        active_path = self.kit.optional_apprc_toml_path()
        if active_path is None:
            return None
        return active_path.parent

    async def _ensure_default_storage(
        self,
        registry: StorageRegistry,
    ) -> None:
        """Ensure the chosen registry has a live setup/editor default storage.

        :param registry: Registry selected by setup.
        """
        self.registry = registry
        current_default = registry.default()
        if current_default is not None and current_default.root.is_dir():
            action = await self.push_screen_wait(
                ConfirmScreen(
                    title="Setup/editor default storage",
                    message=lines_text(
                        "Current setup/editor default storage:",
                        Text.assemble(
                            storage_name_text(current_default.name),
                            " -> ",
                            path_text(current_default.root),
                        ),
                        "",
                        "Keep this setup/editor default?",
                    ),
                    actions=(
                        ("keep", "Keep default", "primary"),
                        ("replace", "Choose new default", "default"),
                    ),
                )
            )
            if action == "keep":
                await self._finish_setup(registry)
                return
            if action != "replace":
                return

        name_result = await self.push_screen_wait(
            StorageNameScreen(
                default_name=registry.default_storage
                or self.kit.default_storage_name(),
                message="Choose the registry name used by --storage.",
            )
        )
        if name_result is None:
            return
        root_result = await self.push_screen_wait(
            PathInputScreen(
                title="Setup/editor default storage root",
                message=self._style_setup_text(
                    setup_text.default_storage_step_text(self.kit),
                ),
                placeholder="Storage root directory",
                value=str(self.kit.default_storage_data_root()),
            )
        )
        if root_result is None:
            return
        guarded_root = await self._guard_storage_root(
            root_result.path,
            storage_name=name_result.name,
        )
        if guarded_root is None:
            return
        try:
            updated = self.kit.register_storage(
                name=name_result.name,
                root=guarded_root,
                make_default=True,
                path=registry.path,
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return
        await self._finish_setup(updated)

    async def _guard_storage_root(
        self,
        storage_root: Path,
        *,
        storage_name: str,
    ) -> Path | None:
        """Validate and confirm a storage root before registry writes.

        :param storage_root: User-entered storage path.
        :param storage_name: Registry selector that will point at the path.
        :return: Safe path, or ``None`` when canceled.
        """
        try:
            root = setup_flow.validate_storage_root_for_setup(
                self.kit,
                storage_root,
                storage_name=storage_name,
                make_default=True,
                allow_non_empty_storage=True,
            )
        except setup_flow.ConfigSetupError as exc:
            self.notify(str(exc), severity="error", markup=False)
            return None
        if root.exists() and root.is_dir() and any(root.iterdir()):
            action = await self.push_screen_wait(
                ConfirmScreen(
                    title="Reuse storage root?",
                    message=self._style_storage_root_reuse_text(
                        root,
                        storage_name=storage_name,
                    ),
                    actions=(("proceed", "Proceed", "warning"),),
                )
            )
            if action != "proceed":
                return None
        return root

    async def _finish_setup(self, registry: StorageRegistry) -> None:
        """Render setup diagnostics and final next steps.

        :param registry: Registry selected by setup.
        """
        self.registry = registry
        self.result = setup_flow.ConfigSetupResult(
            registry=registry,
            existing_action=self.existing_action,
        )
        payload = self.kit.doctor_payload(
            storage_name=registry.default_storage,
            apprc_toml_path=registry.path,
        )
        status = "ok" if payload["ok"] else "needs setup"
        default = registry.default_storage or "<none>"
        body = (
            "Setup wrote or reused the AppRC TOML.\n\n"
            f"apprc_toml_path: {registry.path}\n"
            f"default_storage: {default}\n"
            f"doctor: {status}\n\n"
            "Next steps:\n"
            f"{setup_text.next_steps_text(self.kit, registry)}"
        )
        await self._set_screen(
            title="Done",
            body=self._style_setup_text(
                body,
                paths=(registry.path, registry.path.expanduser().resolve()),
            ),
            buttons=(("finish-close", "Close", "success"),),
        )

    async def _set_screen(
        self,
        *,
        title: str,
        body: VisualType,
        buttons: tuple[tuple[str, str, ButtonVariant], ...],
    ) -> None:
        """Replace the main wizard text and actions.

        :param title: Screen title.
        :param body: Screen body text or Rich renderable.
        :param buttons: Button IDs, labels, and Textual variants.
        """
        self.query_one("#setup-title", Static).update(title)
        self.query_one("#setup-body", Static).update(body)
        action_row = self.query_one("#setup-actions", Horizontal)
        await action_row.remove_children()
        await action_row.mount(
            *(
                Button(label, variant=variant, id=button_id)
                for button_id, label, variant in buttons
            )
        )

    def _style_setup_text(
        self,
        text: str,
        *,
        paths: tuple[Path | str, ...] = (),
    ) -> Text:
        """Style known env keys and path literals in setup prose.

        :param text: Plain setup text from :mod:`apprc.config.setup.text`.
        :param paths: Exact path values known by the caller.
        :return: Rich text with semantic spans.
        """
        styles = {
            self.kit.apprc_toml_env_key(): ENV_KEY_STYLE,
            self.kit.spec.storage_env_key: ENV_KEY_STYLE,
        }
        styles.update({str(path): PATH_STYLE for path in paths if str(path)})
        return style_literals(text, styles)

    def _style_registry_text(
        self,
        text: str,
        registry: StorageRegistry,
    ) -> Text:
        """Style known registry paths in setup prose.

        :param text: Plain text that mentions registry state.
        :param registry: Registry whose paths appear in the text.
        :return: Rich text with path and env-key spans.
        """
        paths = [registry.path]
        paths.extend(
            registry.selected(name).root
            for name in ordered_storage_names(registry)
        )
        return self._style_setup_text(text, paths=tuple(paths))

    def _style_apprc_dir_step_text(self, default_dir: Path | None) -> Text:
        """Return the AppRC directory step body with known paths styled.

        :param default_dir: Prefilled AppRC directory, if available.
        :return: Rich setup body.
        """
        paths: tuple[Path | str, ...]
        if default_dir is None:
            paths = ()
        else:
            paths = (
                default_dir,
                default_dir / self.kit.spec.apprc_toml_filename,
            )
        return self._style_setup_text(
            setup_text.apprc_dir_step_text(self.kit, default_dir),
            paths=paths,
        )

    def _style_storage_root_reuse_text(
        self,
        root: Path,
        *,
        storage_name: str,
    ) -> Text:
        """Return the non-empty storage-root warning with paths styled.

        :param root: Existing storage root selected by setup.
        :param storage_name: Registry selector that will point at ``root``.
        :return: Rich setup warning.
        """
        registry_path = (
            self.registry.path if self.registry is not None else None
        )
        text = setup_text.storage_root_reuse_text(
            self.kit,
            root,
            storage_name=storage_name,
            make_default=True,
            registry_path=registry_path,
        )
        active_registry_path = registry_path or self.kit.apprc_toml_path()
        return self._style_setup_text(
            text,
            paths=(
                root,
                root / self.kit.spec.local_env_filename,
                active_registry_path,
            ),
        )
