"""Setup workflow embedded in the config editor."""

from __future__ import annotations

# == Standard Library ===========================================
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ==================================================
from rich.text import Text

# == Internal ===================================================
from apprc.user_files.env_files.files import read_env_file
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupFlow
from apprc.user_files.setup.text import (
    setup_finish_text,
    setup_overview_text,
    storage_root_reuse_text,
)
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.user_files.storage_roots.registry import suggested_storage_root
from apprc.interfaces.tui._primitives import (
    ButtonVariant,
    ConfirmScreen,
    PathInputScreen,
)
from apprc.interfaces.tui._styles import lines_text, path_text

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorApp


class ConfigEditorSetupWorkflow:
    """Initialize the capability layers declared by one editor.

    :param editor: Config editor that owns the setup controls and current
        selection.
    """

    def __init__(self, editor: ConfigEditorApp) -> None:
        """Store the editor whose setup route should run."""
        self.editor = editor

    async def open_setup_flow(self) -> None:
        """Run the declared setup route and report what the user must do."""
        if self.editor.storage_enabled:
            await self._open_storage_setup_flow()
            return
        if self.editor.kit.spec.app_wide_default():
            await self._run_app_wide_setup()
            return
        await self._show_env_only_guidance()

    async def _open_storage_setup_flow(self) -> None:
        """Choose and initialize a storage root, then offer registration."""
        default_root = (
            self.editor.active_storage_root
            or suggested_storage_root(self.editor.kit.spec.app_name)
        )
        path_result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Set up application storage",
                message=(
                    "Choose the storage directory that will contain this "
                    "application's storage config."
                ),
                placeholder="Storage directory",
                value=str(default_root),
            )
        )
        if path_result is None:
            return
        storage_root = await self._confirm_storage_root(path_result.path)
        if storage_root is None:
            return
        try:
            result = await asyncio.to_thread(
                ConfigSetupFlow(self.editor.kit).run_storage_setup,
                storage_root,
            )
        except (ConfigSetupError, OSError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        if result.active_storage_root is None:
            self.editor.notify(
                "Storage setup did not return a storage root.",
                severity="error",
            )
            return

        self.editor.active_storage_root = result.active_storage_root
        self.editor.app_values = (
            read_env_file(result.app_wide_env)
            if result.app_wide_env is not None
            else self.editor.app_values
        )
        await self.editor._refresh_storage_list()
        await self._show_storage_setup_result(
            storage_root=result.active_storage_root,
            storage_env=result.storage_env,
            app_wide_env=result.app_wide_env,
        )

    async def _confirm_storage_root(self, path: Path) -> Path | None:
        """Validate a setup path and confirm filesystem changes.

        :param path: Storage directory entered by the user.
        :return: Normalized path approved by the user, or ``None``.
        """
        try:
            root = normalize_storage_root_path(path)
        except StorageRootPathError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        try:
            root_exists = root.exists()
            root_is_directory = root.is_dir()
            root_is_not_empty = root_exists and any(root.iterdir())
        except OSError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if root_exists and not root_is_directory:
            self.editor.notify(
                f"Storage root exists but is not a directory: {root}",
                severity="error",
                markup=False,
            )
            return None
        if root_is_not_empty:
            message = Text(storage_root_reuse_text(self.editor.kit, root))
            title = "Reuse storage directory?"
        else:
            message = lines_text(
                "AppRC will initialize storage config in:",
                path_text(root),
            )
            title = "Set up storage?"
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title=title,
                message=message,
                actions=(("setup", "Set up", "primary"),),
            )
        )
        return root if action == "setup" else None

    async def _show_storage_setup_result(
        self,
        *,
        storage_root: Path,
        storage_env: Path | None,
        app_wide_env: Path | None,
    ) -> None:
        """Show initialized files and optionally register the selected path.

        :param storage_root: Directory initialized by setup.
        :param storage_env: Storage dotenv file created by setup.
        :param app_wide_env: App-wide dotenv file created by setup.
        """
        can_register = (
            self.editor.named_storage_enabled
            and self.editor.storage_registry is not None
        )
        actions: tuple[tuple[str, str, ButtonVariant], ...] = (
            (
                ("register", "Register name", "primary"),
                ("done", "Done", "default"),
            )
            if can_register
            else (("done", "Done", "primary"),)
        )
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Storage setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        storage_root=storage_root,
                        storage_env=storage_env,
                        app_wide_env=app_wide_env,
                        config_group_name=self.editor.config_group_name,
                    )
                ),
                actions=actions,
                cancel_label=None,
            )
        )
        if action != "register":
            return
        await self.editor.storage_workflows.register_storage_directory_flow(
            storage_root,
            default_name=self.editor._suggest_storage_name(storage_root),
            directory_already_approved=True,
        )

    async def _run_app_wide_setup(self) -> None:
        """Initialize app-wide config and refresh the editor values."""
        try:
            result = await asyncio.to_thread(
                ConfigSetupFlow(self.editor.kit).run_app_wide_setup
            )
        except (ConfigSetupError, OSError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        if result.app_wide_env is not None:
            self.editor.app_values = read_env_file(result.app_wide_env)
        await self.editor._refresh_storage_list()
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        app_wide_env=result.app_wide_env,
                        config_group_name=self.editor.config_group_name,
                    )
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )

    async def _show_env_only_guidance(self) -> None:
        """Explain why an env-only app needs no AppRC file setup."""
        message = "\n".join(
            (
                setup_overview_text(self.editor.kit),
                "",
                "Set required values in the shell or an explicit env file.",
                "The editor table shows the current value for every field.",
                "",
                "Then verify:",
                f"  {self.editor.kit.spec.config_command_name()} "
                f"{self.editor.config_group_name} doctor",
            )
        )
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Environment setup",
                message=Text(message),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )
