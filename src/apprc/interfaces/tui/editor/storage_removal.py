"""Storage removal workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import shutil

# == Internal ================================
from apprc.user_files.storage_roots.registry import unregister_storage
from apprc.interfaces.tui._primitives import ButtonVariant, ConfirmScreen
from apprc.interfaces.tui._styles import (
    label_value_text,
    lines_text,
    path_text,
    storage_name_text,
)
from apprc.interfaces.tui.editor.storage_base import StorageWorkflowBase
from apprc.interfaces.tui.storage.selection import (
    LiveStorageSelection,
    MissingStorageSelection,
)


class StorageRemovalWorkflows(StorageWorkflowBase):
    """Unregister live or missing storage entries from the editor."""

    async def open_delete_storage_flow(self) -> None:
        """Prompt for unregister/delete behavior for the current storage."""
        selection = self.editor.selection
        if not isinstance(
            selection,
            LiveStorageSelection | MissingStorageSelection,
        ):
            return
        record = selection.record
        can_delete_content = record.root.is_dir()
        message = (
            lines_text(
                label_value_text("Storage", storage_name_text(record.name)),
                label_value_text("Root", path_text(record.root)),
                "",
                "Choose whether to only unregister it or delete the "
                "directory contents too.",
            )
            if can_delete_content
            else lines_text(
                label_value_text("Storage", storage_name_text(record.name)),
                label_value_text("Root", path_text(record.root)),
                "",
                "The storage root is missing or is not a directory. "
                "Only the named storage entry will be removed.",
            )
        )
        actions: tuple[tuple[str, str, ButtonVariant], ...] = (
            (
                ("unregister", "Unregister only", "warning"),
                (
                    "delete-content",
                    "Delete directory and unregister",
                    "error",
                ),
            )
            if can_delete_content
            else (("unregister", "Unregister only", "warning"),)
        )
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Delete storage",
                message=message,
                actions=actions,
            )
        )
        if action == "unregister":
            await self.remove_live_storage(record.name, delete_content=False)
        if action == "delete-content":
            await self.remove_live_storage(record.name, delete_content=True)

    async def remove_live_storage(
        self,
        name: str,
        *,
        delete_content: bool,
    ) -> bool:
        """Remove one live named-storage row.

        :param name: Storage selector to remove.
        :param delete_content: Whether to delete the storage directory too.
        :return: Whether the removal completed.
        """
        registry = self.editor._require_storage_registry()
        if registry is None:
            return False
        try:
            record = registry.selected(name)
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return False
        try:
            self.editor.storage_registry = unregister_storage(
                name=name,
                path=registry.path,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return False
        select_name = self.editor._registered_active_storage_name()
        await self.editor._refresh_storage_list(select_name=select_name)
        if delete_content and record.root.exists():
            try:
                shutil.rmtree(record.root)
            except OSError as exc:
                self.editor.notify(
                    f"Removed storage {name!r}; directory deletion failed: {exc}",
                    severity="warning",
                    markup=False,
                )
                return True
        self.editor.notify(f"Removed storage {name!r}")
        return True
