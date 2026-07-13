"""Storage rename, repoint, and move workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import asyncio
import errno
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

# == 3rd Party ===============================
from rich.text import Text

# == Internal ================================
from apprc.user_files.storage_roots.paths import normalize_storage_root_path
from apprc.user_files.storage_roots.model import StorageRecord
from apprc.user_files.storage_roots.registry import _update_storage
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


@dataclass(frozen=True, slots=True)
class _StorageMoveState:
    """Track filesystem changes that await a registry update."""

    source_root: Path
    destination_root: Path
    destination_backup: Path | None
    copied_across_filesystems: bool


class StorageEditingWorkflows(StorageWorkflowBase):
    """Edit named-storage metadata and relocate live storage directories."""

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
                    "This changes only the named-storage registry entry.",
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
            self.editor.storage_registry = _update_storage(
                current_name=record.name,
                name=name,
                root=record.root,
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
        if root is None or root == record.root.resolve():
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
                    "This changes only the named-storage registry entry.",
                    "It does not create, move, or delete files.",
                ),
                actions=(("update", "Update location", "warning"),),
            )
        )
        if action != "update":
            return
        try:
            self.editor.storage_registry = _update_storage(
                current_name=record.name,
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
        """Move the selected live directory and update its registry root."""
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
        source_root = record.root.resolve()
        destination_root = self._move_destination(
            source_root=source_root,
            candidate=result.path,
        )
        if destination_root is None:
            return
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Move storage",
                message=lines_text(
                    label_value_text(
                        "Storage",
                        storage_name_text(record.name),
                    ),
                    label_value_text("Source", path_text(source_root)),
                    label_value_text(
                        "Destination",
                        path_text(destination_root),
                    ),
                    "",
                    "The complete storage directory will be moved.",
                    "Proceed?",
                ),
                actions=(("move", "Move", "warning"),),
            )
        )
        if action != "move":
            return
        try:
            move_state = await asyncio.to_thread(
                self._move_storage_directory,
                source_root=source_root,
                destination_root=destination_root,
            )
        except (OSError, shutil.Error) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        try:
            self.editor.storage_registry = _update_storage(
                current_name=record.name,
                name=record.name,
                root=destination_root,
                path=registry.path,
            )
        except (OSError, TypeError, ValueError) as exc:
            restore_error = await asyncio.to_thread(
                self._restore_moved_storage_directory,
                move_state=move_state,
            )
            if restore_error is not None:
                self.editor.notify(
                    "Storage registry update failed after moving files, and "
                    "rolling back the filesystem change also failed: "
                    f"{restore_error}",
                    severity="warning",
                    markup=False,
                )
            self.editor.notify(str(exc), severity="error", markup=False)
            return
        cleanup_error = await asyncio.to_thread(
            self._clean_up_completed_storage_move,
            move_state=move_state,
        )
        await self.editor._refresh_storage_list(select_name=record.name)
        if cleanup_error is not None:
            self.editor.notify(
                "Storage was moved, but cleanup of its previous location "
                f"needs attention: {cleanup_error}",
                severity="warning",
                markup=False,
            )
        self.editor.notify(f"Moved storage {record.name!r}")

    def _selected_editable_storage(self) -> StorageRecord | None:
        """Return the selected live or missing named-storage record."""
        selection = self.editor.selection
        if isinstance(
            selection,
            LiveStorageSelection | MissingStorageSelection,
        ):
            return selection.record
        return None

    def _existing_storage_directory(self, candidate: Path) -> Path | None:
        """Return an existing directory for a registry-only location update.

        :param candidate: Path entered through the location modal.
        :return: Resolved directory, or ``None`` after reporting validation
            failure.
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

    def _move_destination(
        self,
        *,
        source_root: Path,
        candidate: Path,
    ) -> Path | None:
        """Return a safe new or empty destination for one directory move.

        :param source_root: Existing directory that will be relocated.
        :param candidate: Path entered through the move modal.
        :return: Resolved destination, or ``None`` after reporting why it is
            unsafe.
        """
        try:
            destination_root = normalize_storage_root_path(candidate).resolve()
        except (OSError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if destination_root == source_root:
            self.editor.notify(
                "Storage destination must differ from the current location.",
                severity="error",
            )
            return None
        if destination_root.is_relative_to(
            source_root
        ) or source_root.is_relative_to(destination_root):
            self.editor.notify(
                "Storage destination may not contain or be contained by the "
                "current location.",
                severity="error",
            )
            return None
        try:
            if self._path_exists(destination_root):
                if not destination_root.is_dir():
                    self.editor.notify(
                        "Storage destination is not a directory: "
                        f"{destination_root}",
                        severity="error",
                        markup=False,
                    )
                    return None
                if any(destination_root.iterdir()):
                    self.editor.notify(
                        "Storage destination must be new or empty: "
                        f"{destination_root}",
                        severity="error",
                        markup=False,
                    )
                    return None
            elif not destination_root.parent.is_dir():
                self.editor.notify(
                    "Storage destination parent does not exist or is not a "
                    f"directory: {destination_root.parent}",
                    severity="error",
                    markup=False,
                )
                return None
        except OSError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        return destination_root

    @staticmethod
    def _path_exists(path: Path) -> bool:
        """Return whether a path has a filesystem entry, including links.

        :param path: Filesystem location to inspect.
        :return: Whether the location exists or is a dangling symbolic link.
        """
        return path.exists() or path.is_symlink()

    def _move_storage_directory(
        self,
        *,
        source_root: Path,
        destination_root: Path,
    ) -> _StorageMoveState:
        """Move one directory to a destination that passed safety checks.

        A same-filesystem move is an atomic rename. Cross-filesystem moves
        first copy into a private staging directory, so the source remains
        intact until the registry accepts the new location.

        :param source_root: Existing source directory.
        :param destination_root: New or empty destination directory.
        :return: State used to finish or roll back the filesystem change.
        """
        if not source_root.is_dir():
            raise OSError(f"Storage source is not a directory: {source_root}")
        destination_backup = self._park_empty_destination(destination_root)
        try:
            if self._move_requires_copy(
                source_root=source_root,
                destination_root=destination_root,
            ):
                return self._copy_storage_directory(
                    source_root=source_root,
                    destination_root=destination_root,
                    destination_backup=destination_backup,
                )
            try:
                os.replace(source_root, destination_root)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                return self._copy_storage_directory(
                    source_root=source_root,
                    destination_root=destination_root,
                    destination_backup=destination_backup,
                )
        except (OSError, shutil.Error) as exc:
            restore_error = self._restore_destination_backup(
                destination_root=destination_root,
                destination_backup=destination_backup,
            )
            if restore_error is not None:
                raise OSError(
                    f"{exc}; also could not restore the empty destination: "
                    f"{restore_error}"
                ) from exc
            raise
        return _StorageMoveState(
            source_root=source_root,
            destination_root=destination_root,
            destination_backup=destination_backup,
            copied_across_filesystems=False,
        )

    def _park_empty_destination(self, destination_root: Path) -> Path | None:
        """Move an existing empty destination aside until the move commits.

        :param destination_root: Destination accepted by the move modal.
        :return: Backup path for the original empty directory, if one exists.
        :raises OSError: If the target changed into an unsafe destination.
        """
        if not self._path_exists(destination_root):
            if not destination_root.parent.is_dir():
                raise OSError(
                    "Storage destination parent does not exist or is not a "
                    f"directory: {destination_root.parent}"
                )
            return None
        if not destination_root.is_dir():
            raise OSError(
                f"Storage destination is not a directory: {destination_root}"
            )
        if any(destination_root.iterdir()):
            raise OSError(
                f"Storage destination must be new or empty: {destination_root}"
            )
        backup = self._destination_backup_path(destination_root)
        os.replace(destination_root, backup)
        return backup

    def _destination_backup_path(self, destination_root: Path) -> Path:
        """Choose a private sibling path for an empty destination backup.

        :param destination_root: Destination whose empty directory is parked.
        :return: A currently unused sibling location.
        :raises OSError: If no unused backup name can be found.
        """
        for _ in range(100):
            candidate = destination_root.parent / (
                f".{destination_root.name}.apprc-empty-{uuid4().hex}"
            )
            if not self._path_exists(candidate):
                return candidate
        raise OSError(
            "Could not reserve a temporary location for the empty storage "
            f"destination: {destination_root}"
        )

    @staticmethod
    def _move_requires_copy(
        *,
        source_root: Path,
        destination_root: Path,
    ) -> bool:
        """Return whether a cross-filesystem copy is needed for a move.

        :param source_root: Existing storage directory.
        :param destination_root: New storage directory beneath its parent.
        :return: Whether an atomic rename cannot be used.
        """
        return (
            source_root.stat().st_dev != destination_root.parent.stat().st_dev
        )

    def _copy_storage_directory(
        self,
        *,
        source_root: Path,
        destination_root: Path,
        destination_backup: Path | None,
    ) -> _StorageMoveState:
        """Stage a cross-filesystem copy without removing the source.

        :param source_root: Existing storage directory to copy.
        :param destination_root: Final storage location, currently absent.
        :param destination_backup: Parked original empty destination, if any.
        :return: State describing the staged copy.
        :raises OSError: If staging or promoting the copied directory fails.
        """
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_root.name}.apprc-moving-",
                dir=destination_root.parent,
            )
        )
        try:
            shutil.copytree(
                source_root,
                staging_root,
                dirs_exist_ok=True,
                symlinks=True,
            )
            os.replace(staging_root, destination_root)
        except (OSError, shutil.Error) as exc:
            cleanup_error = self._remove_directory(
                staging_root,
                action="remove incomplete staged storage copy",
            )
            if cleanup_error is not None:
                raise OSError(
                    f"{exc}; also could not remove the incomplete staged "
                    f"copy: {cleanup_error}"
                ) from exc
            raise
        return _StorageMoveState(
            source_root=source_root,
            destination_root=destination_root,
            destination_backup=destination_backup,
            copied_across_filesystems=True,
        )

    def _restore_moved_storage_directory(
        self,
        *,
        move_state: _StorageMoveState,
    ) -> OSError | shutil.Error | None:
        """Attempt to undo a moved directory after a registry write failure.

        :param move_state: Filesystem change created before the registry write.
        :return: Restore error, if the move or original empty destination
            cannot be restored.
        """
        if move_state.copied_across_filesystems:
            remove_error = self._remove_directory(
                move_state.destination_root,
                action="remove copied storage during rollback",
            )
            if remove_error is not None:
                return remove_error
        else:
            try:
                if self._path_exists(move_state.source_root):
                    raise OSError(
                        "Storage source location was recreated before "
                        f"rollback: {move_state.source_root}"
                    )
                if not self._path_exists(move_state.destination_root):
                    raise OSError(
                        "Moved storage directory is missing during rollback: "
                        f"{move_state.destination_root}"
                    )
                os.replace(
                    move_state.destination_root,
                    move_state.source_root,
                )
            except OSError as exc:
                return exc
        return self._restore_destination_backup(
            destination_root=move_state.destination_root,
            destination_backup=move_state.destination_backup,
        )

    def _clean_up_completed_storage_move(
        self,
        *,
        move_state: _StorageMoveState,
    ) -> OSError | shutil.Error | None:
        """Remove superseded files after a registry update commits.

        :param move_state: Filesystem change now reflected in the registry.
        :return: Cleanup error that leaves the new registry root intact.
        """
        errors: list[str] = []
        if move_state.copied_across_filesystems:
            source_error = self._remove_directory(
                move_state.source_root,
                action="remove original storage after cross-filesystem move",
            )
            if source_error is not None:
                errors.append(str(source_error))
        if move_state.destination_backup is not None and self._path_exists(
            move_state.destination_backup
        ):
            try:
                move_state.destination_backup.rmdir()
            except OSError as exc:
                errors.append(
                    "Could not remove the original empty destination "
                    f"backup {move_state.destination_backup}: {exc}"
                )
        if errors:
            return OSError("; ".join(errors))
        return None

    def _restore_destination_backup(
        self,
        *,
        destination_root: Path,
        destination_backup: Path | None,
    ) -> OSError | None:
        """Put an original empty destination back after a failed move.

        :param destination_root: Location that should be empty before restore.
        :param destination_backup: Parked empty directory, if one existed.
        :return: Restore error, or ``None`` when no restore was needed.
        """
        if destination_backup is None:
            return None
        try:
            if self._path_exists(destination_root):
                raise OSError(
                    "Storage destination was recreated before rollback: "
                    f"{destination_root}"
                )
            if not self._path_exists(destination_backup):
                raise OSError(
                    "Original empty storage destination is missing during "
                    f"rollback: {destination_backup}"
                )
            os.replace(destination_backup, destination_root)
        except OSError as exc:
            return exc
        return None

    def _remove_directory(
        self,
        path: Path,
        *,
        action: str,
    ) -> OSError | shutil.Error | None:
        """Remove an expected directory without deleting an unexpected file.

        :param path: Directory produced by this move operation.
        :param action: Human-readable cleanup action for error reporting.
        :return: Cleanup error, or ``None`` after removal or when absent.
        """
        if not self._path_exists(path):
            return None
        if not path.is_dir():
            return OSError(f"Could not {action}; it is not a directory: {path}")
        try:
            shutil.rmtree(path)
        except (OSError, shutil.Error) as exc:
            return exc
        return None
