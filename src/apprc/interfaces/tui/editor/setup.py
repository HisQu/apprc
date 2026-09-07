"""Setup workflow embedded in the config editor."""

from __future__ import annotations

# == Standard Library ===========================================
import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

# == 3rd Party ==================================================
from rich.text import Text

# == Internal ===================================================
from apprc.user_files.env_files.files import read_env_file
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    normalize_apprc_dir,
)
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupFlow
from apprc.user_files.setup.text import (
    setup_finish_text,
    storage_root_reuse_text,
)
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.user_files.storage_roots._loading import (
    load_optional_runtime_storage_registry,
)
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputScreen,
)
from apprc.interfaces.tui._styles import lines_text, path_text

if TYPE_CHECKING:
    from apprc.interfaces.tui.editor.app import ConfigEditorApp
    from apprc.user_files.storage_roots.registry import StorageRegistry


class ConfigEditorSetupWorkflow:
    """Initialize the managed files declared by one editor.

    :param editor: Config editor that owns the setup controls and current
        selection.
    """

    def __init__(self, editor: ConfigEditorApp) -> None:
        """Store the editor whose setup route should run."""
        self.editor = editor
        self._previous_apprc_dir: Path | None = None

    async def open_setup_flow(self) -> None:
        """Run the declared setup route and report what the user must do."""
        apprc_dir = await self._choose_apprc_dir()
        if apprc_dir is None:
            return
        self._previous_apprc_dir = self.editor.kit.spec.apprc_dir()
        if self.editor.storage_enabled and (
            apprc_dir != self._previous_apprc_dir
            or self.editor._storage_setup_needed()
        ):
            await self._open_storage_setup_flow(apprc_dir)
            return
        await self._run_user_dotenv_setup(apprc_dir)

    async def _choose_apprc_dir(self) -> Path | None:
        """Ask where AppRC should keep this application's managed files."""
        suggested = self.editor.kit.spec.apprc_dir()
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Choose AppRC directory",
                message=(
                    "Choose the directory for AppRC-managed files. "
                    "Path completion is available while typing."
                ),
                placeholder="AppRC directory",
                value=str(suggested),
            )
        )
        if result is None:
            return None
        try:
            return normalize_apprc_dir(result.path)
        except AppRCDirectoryError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None

    async def _open_storage_setup_flow(self, apprc_dir: Path) -> None:
        """Choose and initialize the default registered storage.

        :param apprc_dir: AppRC directory selected in the first setup step.
        """
        proc_env = {
            **os.environ,
            self.editor.kit.spec.apprc_dir_env_key: str(apprc_dir),
        }
        try:
            target_registry = load_optional_runtime_storage_registry(
                self.editor.kit.spec,
                proc_env=proc_env,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        default_root = apprc_dir / "storage"
        if (
            target_registry is not None
            and target_registry.selected_storage is not None
        ):
            default_root = target_registry.selected(
                target_registry.selected_storage
            ).root
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
            storage_name = self._storage_name_for_setup(
                storage_root,
                registry=target_registry,
            )
            result = await asyncio.to_thread(
                ConfigSetupFlow(self.editor.kit).run_storage_setup,
                storage_root,
                storage_name=storage_name,
                apprc_dir=apprc_dir,
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

        os.environ[self.editor.kit.spec.apprc_dir_env_key] = str(
            result.apprc_dir
        )
        self.editor.active_storage_root = result.active_storage_root
        self.editor.storage_registry = load_optional_runtime_storage_registry(
            self.editor.kit.spec
        )
        self.editor.storage_registry_error = None
        self.editor.user_dotenv_values = (
            read_env_file(result.user_dotenv)
            if result.user_dotenv is not None
            else self.editor.user_dotenv_values
        )
        self.editor.user_dotenv_active = (
            result.user_dotenv is not None or self.editor.user_dotenv_active
        )
        await self.editor.clear_setup_status()
        await self.editor._refresh_storage_list()
        await self._show_storage_setup_result(
            storage_root=result.active_storage_root,
            storage_dotenv=result.storage_dotenv,
            user_dotenv=result.user_dotenv,
            apprc_dir=result.apprc_dir,
        )

    def _storage_name_for_setup(
        self,
        storage_root: Path,
        *,
        registry: StorageRegistry | None,
    ) -> str:
        """Choose the registry name that setup should initialize.

        :param storage_root: Approved setup directory.
        :param registry: Registry loaded from the selected AppRC directory.
        :return: Existing associated name or a stable new suggestion.
        """
        if registry is None or not registry.storages:
            return "default"
        resolved_root = storage_root.expanduser().resolve()
        matches = [
            name
            for name, record in registry.storages.items()
            if record.root.expanduser().resolve() == resolved_root
        ]
        if len(matches) == 1:
            return matches[0]
        return self.editor._suggest_storage_name(resolved_root)

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
        apprc_dir: Path,
    ) -> None:
        """Show initialized files and optionally register the selected path.

        :param storage_root: Directory initialized by setup.
        :param storage_dotenv: Storage dotenv file created by setup.
        :param user_dotenv: User dotenv file created by setup.
        :param apprc_dir: Directory containing AppRC's central files.
        """
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Storage setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        apprc_dir=apprc_dir,
                        storage_root=storage_root,
                        storage_dotenv=storage_dotenv,
                        user_dotenv=user_dotenv,
                        config_group_name=self.editor.config_group_name,
                        previous_apprc_dir=self._previous_apprc_dir,
                    )
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )

    async def _run_user_dotenv_setup(self, apprc_dir: Path) -> None:
        """Initialize the per-user dotenv and refresh editor values.

        :param apprc_dir: AppRC directory selected in the first setup step.
        """
        try:
            result = await asyncio.to_thread(
                ConfigSetupFlow(self.editor.kit).run_user_dotenv_setup,
                apprc_dir=apprc_dir,
            )
        except (ConfigSetupError, OSError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        os.environ[self.editor.kit.spec.apprc_dir_env_key] = str(
            result.apprc_dir
        )
        if result.user_dotenv is not None:
            self.editor.user_dotenv_active = True
            self.editor.user_dotenv_values = read_env_file(result.user_dotenv)
        await self.editor.clear_setup_status()
        await self.editor._refresh_storage_list()
        await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Setup complete",
                message=Text(
                    setup_finish_text(
                        self.editor.kit,
                        apprc_dir=result.apprc_dir,
                        user_dotenv=result.user_dotenv,
                        config_group_name=self.editor.config_group_name,
                        previous_apprc_dir=self._previous_apprc_dir,
                    )
                ),
                actions=(("done", "Done", "primary"),),
                cancel_label=None,
            )
        )
