"""Storage rename, repoint, and move workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ===========================================
import asyncio
from pathlib import Path

# == 3rd Party ==================================================
from rich.text import Text

# == Internal ===================================================
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputScreen,
    StorageNameScreen,
)
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
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty
from apprc.user_files.storage_roots.model import StorageRecord
from apprc.user_files.storage_roots.move import move_storage
from apprc.user_files.storage_roots.paths import (
    normalize_storage_root_path,
    resolve_storage_root_path,
)
from apprc.user_files.storage_roots.registry import (
    rename_storage,
    repoint_storage,
)


class StorageEditingWorkflows(StorageWorkflowBase):
    """Edit storage metadata and relocate live storage directories."""

    async def open_rename_storage_flow(self) -> None:
        """Prompt for a new selector and confirm its external migration.

        Renaming changes only registry metadata. Callers that select the
        storage through ``--storage`` or an environment variable continue to
        use the old selector until they are updated separately.
        """
        registry = self.editor._require_storage_registry()
        record = self._selected_editable_storage()
        if registry is None or record is None:
            return
        result = await self.editor.push_screen_wait(
            StorageNameScreen(
                default_name=record.name,
                message="Choose the storage name used by --storage.",
            )
        )
        if result is None:
            return
        name = result.name
        if name == record.name:
            return
        if name in registry.storages or name in registry.archived_storages:
            self.editor.notify(
                f"Storage name {name!r} is already in use.",
                severity="error",
                markup=False,
            )
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Rename storage",
                message=lines_text(
                    Text.assemble(
                        "Rename ",
                        storage_name_text(repr(record.name)),
                        " to ",
                        storage_name_text(repr(name)),
                        "?",
                    ),
                    "",
                    "This changes only the storage registry entry.",
                    Text.assemble(
                        "Update external --storage arguments and "
                        "environment values that use ",
                        storage_name_text(repr(record.name)),
                        ".",
                    ),
                ),
                actions=(("rename", "Rename", "warning"),),
            )
        )
        if action != "rename":
            return
        try:
            self.editor.storage_registry = await asyncio.to_thread(
                rename_storage,
                current_name=record.name,
                name=name,
                path=registry.path,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.editor._refresh_storage_list(select_name=name)
        self.editor.notify(f"Renamed storage {record.name!r} to {name!r}")

    async def open_storage_location_flow(self) -> None:
        """Prompt for an existing directory to record as the storage root."""
        registry = self.editor._require_storage_registry()
        record = self._selected_editable_storage()
        if registry is None or record is None:
            return
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Storage location",
                message=(
                    "Enter an existing storage directory. This changes only "
                    "the registry entry; it does not create, move, or delete "
                    "files."
                ),
                placeholder="Existing storage directory",
                value=str(record.root),
            )
        )
        if result is None:
            return
        root = self._existing_storage_directory(result.path)
        if root is None or root == record.root:
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Update storage location",
                message=lines_text(
                    label_value_text(
                        "Storage",
                        storage_name_text(record.name),
                    ),
                    label_value_text(
                        "Current location", path_text(record.root)
                    ),
                    label_value_text("New location", path_text(root)),
                    "",
                    "This changes only the storage registry entry.",
                    "It does not create, move, or delete files.",
                    "External --storage arguments and environment values "
                    "that use the current name are not changed.",
                ),
                actions=(("update", "Update location", "warning"),),
            )
        )
        if action != "update":
            return
        try:
            self.editor.storage_registry = await asyncio.to_thread(
                repoint_storage,
                name=record.name,
                root=root,
                path=registry.path,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        await self.editor._refresh_storage_list(select_name=record.name)
        self.editor.notify(f"Updated location for storage {record.name!r}")

    async def open_move_storage_flow(self) -> None:
        """Move the selected storage through the transactional service."""
        registry = self.editor._require_storage_registry()
        selection = self.editor.selection
        if registry is None or not isinstance(selection, LiveStorageSelection):
            return
        record = selection.record
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Move storage",
                message=(
                    "Enter a new or empty destination directory for the "
                    "complete storage. Existing files are never merged or "
                    "replaced."
                ),
                placeholder="New or empty storage directory",
            )
        )
        if result is None:
            return
        try:
            destination = resolve_storage_root_path(
                result.path,
                base=registry.path.parent,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Move storage",
                message=lines_text(
                    label_value_text("Storage", storage_name_text(record.name)),
                    label_value_text("Source", path_text(record.root)),
                    label_value_text("Destination", path_text(destination)),
                    "",
                    "The complete storage directory will be moved and its "
                    "registry root will be updated.",
                ),
                actions=(("move", "Move", "warning"),),
            )
        )
        if action != "move":
            return
        try:
            move_result = await asyncio.to_thread(
                move_storage,
                name=record.name,
                destination=destination,
                path=registry.path,
            )
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        self.editor.storage_registry = load_storage_registry_or_empty(
            registry.path
        )
        await self.editor._refresh_storage_list(select_name=record.name)
        for warning in move_result.warnings:
            self.editor.notify(warning, severity="warning", markup=False)
        self.editor.notify(f"Moved storage {record.name!r}")

    def _selected_editable_storage(self) -> StorageRecord | None:
        """Return the selected live or missing storage record."""
        selection = self.editor.selection
        if isinstance(
            selection,
            LiveStorageSelection | MissingStorageSelection,
        ):
            return selection.record
        return None

    def _existing_storage_directory(self, candidate: Path) -> Path | None:
        """Validate a directory for a registry-only location update.

        :param candidate: Path entered through the location modal.
        :return: Absolute directory, or ``None`` after reporting a failure.
        """
        try:
            root = normalize_storage_root_path(candidate).resolve()
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if not root.exists():
            self.editor.notify(
                f"Storage location does not exist: {root}",
                severity="error",
                markup=False,
            )
            return None
        if not root.is_dir():
            self.editor.notify(
                f"Storage location is not a directory: {root}",
                severity="error",
                markup=False,
            )
            return None
        return root
