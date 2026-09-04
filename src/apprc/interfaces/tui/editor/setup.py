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
    storage_root_reuse_text,
)
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.user_files.storage_roots.registry import suggested_storage_root
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputScreen,
)
from apprc.interfaces.tui._styles import lines_text, path_text

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorApp


class ConfigEditorSetupWorkflow:
    """Initialize the managed files declared by one editor.

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
        await self._run_app_setup()

    async def _open_storage_setup_flow(self) -> None:
        """Choose and initialize the default registered storage."""
        default_root = self.editor.active_storage_root or (
            suggested_storage_root(self.editor.kit.spec.app_id)
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
        self.editor.user_dotenv_values = (
            read_env_file(result.user_dotenv)
            if result.user_dotenv is not None
            else self.editor.user_dotenv_values
        )
        await self.editor._refresh_storage_list()
        await self._show_storage_setup_result(
            storage_root=result.active_storage_root,
            storage_dotenv=result.storage_dotenv,
            user_dotenv=result.user_dotenv,
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
        storage_dotenv: Path | None,
        user_dotenv: Path | None,
    ) -> None:
        """Show initialized files and optionally register the selected path.

        :param storage_root: Directory initialized by setup.
        :param storage_dotenv: Storage dotenv file created by setup.
        :param user_dotenv: User dotenv file created by setup.
        """
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Storage setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        storage_root=storage_root,
                        storage_dotenv=storage_dotenv,
                        user_dotenv=user_dotenv,
                        config_group_name=self.editor.config_group_name,
                    )
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )

    async def _run_app_setup(self) -> None:
        """Initialize the per-user dotenv and refresh editor values."""
        try:
            result = await asyncio.to_thread(
                ConfigSetupFlow(self.editor.kit).run_app_setup
            )
        except (ConfigSetupError, OSError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        if result.user_dotenv is not None:
            self.editor.user_dotenv_values = read_env_file(result.user_dotenv)
        await self.editor._refresh_storage_list()
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        user_dotenv=result.user_dotenv,
                        config_group_name=self.editor.config_group_name,
                    )
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )
