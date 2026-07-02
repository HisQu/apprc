"""Storage registration workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
from rich.text import Text

# == Internal ================================
from apprc.user_files.env_files.files import read_env_file
from apprc.user_files.storage_roots.paths import normalize_storage_root_path
from apprc.user_files.storage_roots.registry import register_storage
from apprc.interfaces.tui._primitives import ConfirmScreen, StorageNameScreen
from apprc.interfaces.tui._styles import (
    lines_text,
    path_markup,
    path_text,
    storage_name_text,
)
from apprc.interfaces.tui.editor.storage_base import StorageWorkflowBase
from apprc.interfaces.tui.storage.selection import ActivePathStorageSelection


class StorageRegistrationWorkflows(StorageWorkflowBase):
    """Register directory-backed storage roots in the editor."""

    async def register_active_storage_flow(self) -> None:
        """Register the env-selected active storage path by name."""
        if self.editor._require_storage_registry() is None:
            return
        selection = self.editor.selection
        if not isinstance(selection, ActivePathStorageSelection):
            self.editor.notify(
                "No active storage path is selected.",
                severity="warning",
            )
            return
        await self.register_storage_directory_flow(
            selection.root,
            default_name=self.editor._suggest_storage_name(selection.root),
        )

    async def register_storage_directory_flow(
        self,
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        """Prompt for confirmation and register one live storage root.

        :param storage_root: Directory selected by the user.
        :param default_name: Suggested storage selector.
        """
        registry = self.editor._require_storage_registry()
        if registry is None:
            return
        guarded_root = await self.guard_storage_directory(storage_root)
        if guarded_root is None:
            return
        name_result = await self.editor.push_screen_wait(
            StorageNameScreen(
                default_name=default_name,
                message="Choose the storage name used by --storage.",
            )
        )
        if name_result is None:
            return
        name = name_result.name
        if name in registry.storages:
            existing = registry.selected(name)
            action = await self.editor.push_screen_wait(
                ConfirmScreen(
                    title="Replace storage entry?",
                    message=lines_text(
                        Text.assemble(
                            storage_name_text(repr(name)),
                            " is already registered at:",
                        ),
                        path_text(existing.root),
                        "",
                        "Replace it with:",
                        path_text(guarded_root),
                    ),
                    actions=(("replace", "Replace", "warning"),),
                )
            )
            if action != "replace":
                return
        try:
            self.editor.storage_registry = register_storage(
                name=name,
                root=guarded_root,
                path=registry.path,
                storage_env_filename=self.editor.kit.spec.storage_env_filename,
            )
        except (TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.editor._refresh_storage_list(select_name=name)
        self.editor.notify(f"Registered storage {name!r}")

    async def guard_storage_directory(self, storage_root: Path) -> Path | None:
        """Confirm the requested directory is safe to register.

        :param storage_root: User-entered storage path.
        :return: Safe path, or ``None`` when canceled.
        """
        try:
            root = normalize_storage_root_path(storage_root)
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if not root.exists():
            parent = root.parent
            if parent.exists():
                action = await self.editor.push_screen_wait(
                    ConfirmScreen(
                        title="Directory does not exist",
                        message=Text.assemble(
                            "Directory does not exist, create new directory "
                            "inside ",
                            path_text(parent),
                            "?",
                        ),
                        actions=(("create", "Create", "primary"),),
                    )
                )
                return root if action == "create" else None
            self.editor.notify(
                f"Path not found! {path_markup(parent)}",
                severity="error",
            )
            return None
        resolved_root = root.resolve()
        if not resolved_root.is_dir():
            self.editor.notify(
                "Storage path exists but is not a directory: "
                f"{path_markup(resolved_root)}",
                severity="error",
            )
            return None
        if not any(resolved_root.iterdir()):
            return resolved_root

        storage_env_filename = self.editor.kit.spec.storage_env_filename
        env_path = resolved_root / storage_env_filename
        if env_path.is_file():
            keys = list(read_env_file(env_path))[:10]
            preview = ", ".join(keys) if keys else "<none>"
            message = (
                f"Storage not empty, found {storage_env_filename} "
                f"with these env vars: {preview}.\n"
                "All these storage env vars will be exported on runtime. "
                "Proceed?"
            )
        else:
            message = lines_text(
                "Storage not empty, but no "
                f"{storage_env_filename} found, initialize with "
                f"empty {storage_env_filename}?",
                path_text(resolved_root),
            )
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Confirm storage directory",
                message=message,
                actions=(("proceed", "Proceed", "warning"),),
            )
        )
        return resolved_root if action == "proceed" else None
