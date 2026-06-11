"""Storage workflow orchestration for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.config.local_env import read_local_env
from apprc.config.paths import normalize_storage_root_path
from apprc.config.storage.archive import (
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
    is_storage_archive_path,
    storage_archive_default_path,
    storage_root_name_from_archive,
)
from apprc.config.tui.modals import (
    ArchiveOptionsScreen,
    DefaultPathScreen,
    ProgressScreen,
)
from apprc.config.tui.primitives import (
    ButtonVariant,
    ConfirmScreen,
    PathInputScreen,
    StorageNameScreen,
)
from apprc.config.tui.storage.entries import ordered_existing_storage_names

if TYPE_CHECKING:
    from apprc.config.tui import ConfigEditorApp


@dataclass(frozen=True, slots=True)
class RemovalDefaultChoice:
    """Default replacement chosen before removing a live storage.

    :param replacement_name: Existing storage to promote to default.
    :param create_default_path: New storage root to create as default.
    """

    replacement_name: str | None = None
    create_default_path: Path | None = None


class ConfigEditorStorageWorkflows:
    """Run storage-management workflows for :class:`ConfigEditorApp`.

    The editor owns widgets, selection, and field-table rendering. This helper
    owns multi-step storage flows that mutate the registry or filesystem, then
    asks the editor to refresh its visible state.

    :param editor: Mounted config editor app.
    """

    def __init__(self, editor: "ConfigEditorApp") -> None:
        """Store the editor whose UI primitives are used by workflows."""
        self.editor = editor

    async def open_new_storage_flow(self) -> None:
        """Prompt for a new directory or archive path and register it."""
        if self.editor._require_kit() is None:
            return
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="New storage",
                message=(
                    "Enter path to a directory or an archived *.apprc.tar.xz."
                ),
                placeholder="Directory or *.apprc.tar.xz archive",
            )
        )
        if result is None:
            return
        path = result.path.expanduser()
        if is_storage_archive_path(path):
            await self.open_archive_import_flow(path)
            return
        await self.register_storage_directory_flow(
            path,
            default_name=self.editor._suggest_storage_name(path),
        )

    async def open_archive_import_flow(
        self,
        archive_path: Path,
        *,
        default_name: str | None = None,
        default_destination: Path | None = None,
    ) -> None:
        """Restore an archive path, then register the destination.

        :param archive_path: Archive selected by the user or registry.
        :param default_name: Optional restored storage name.
        :param default_destination: Optional restored storage root path.
        """
        archive = archive_path.expanduser()
        if not archive.is_file():
            self.editor.notify(
                f"Storage archive does not exist: {archive}",
                severity="error",
            )
            return
        restored_name = default_name or storage_root_name_from_archive(archive)
        destination = default_destination or archive.parent / restored_name
        result = await self.editor.push_screen_wait(
            PathInputScreen(
                title="Restore archived storage",
                message="Enter destination directory for the restored storage.",
                placeholder="Destination directory",
                value=str(destination),
            )
        )
        if result is None:
            return
        destination_root = result.path.expanduser()
        try:
            normalized_destination = normalize_storage_root_path(
                destination_root
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return
        if normalized_destination.exists() and any(
            normalized_destination.iterdir()
        ):
            action = await self.editor.push_screen_wait(
                ConfirmScreen(
                    title="Destination is not empty",
                    message=(
                        "Extracting the archive may overwrite files in:\n"
                        f"{normalized_destination}\n\nProceed?"
                    ),
                    actions=(("confirm", "Proceed", "warning"),),
                )
            )
            if action != "confirm":
                return
        try:
            await self.run_extract_progress(
                archive_path=archive,
                destination_root=normalized_destination,
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return
        await self.register_storage_directory_flow(
            normalized_destination,
            default_name=self.editor._suggest_storage_name(Path(restored_name)),
        )

    async def register_storage_directory_flow(
        self,
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        """Prompt for confirmation and register one live storage root.

        :param storage_root: Directory selected by the user.
        :param default_name: Suggested registry selector.
        """
        kit = self.editor._require_kit()
        if kit is None:
            return
        guarded_root = await self.guard_storage_directory(storage_root)
        if guarded_root is None:
            return
        name_result = await self.editor.push_screen_wait(
            StorageNameScreen(
                default_name=default_name,
                message="Choose the registry name used by --storage.",
            )
        )
        if name_result is None:
            return
        name = name_result.name
        if name in self.editor.registry.storages:
            existing = self.editor.registry.selected(name)
            action = await self.editor.push_screen_wait(
                ConfirmScreen(
                    title="Replace storage entry?",
                    message=(
                        f"{name!r} is already registered at:\n"
                        f"{existing.root}\n\nReplace it with:\n"
                        f"{guarded_root}"
                    ),
                    actions=(("replace", "Replace", "warning"),),
                )
            )
            if action != "replace":
                return
        try:
            self.editor.registry = kit.register_storage(
                name=name,
                root=guarded_root,
                make_default=self.editor.registry.default_storage is None,
            )
        except (TypeError, ValueError) as exc:
            self.editor.notify(str(exc), severity="error")
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
            self.editor.notify(str(exc), severity="error")
            return None
        if not root.exists():
            parent = root.parent
            if parent.exists():
                action = await self.editor.push_screen_wait(
                    ConfirmScreen(
                        title="Directory does not exist",
                        message=(
                            "Directory does not exist, create new directory "
                            f"inside {parent}?"
                        ),
                        actions=(("create", "Create", "primary"),),
                    )
                )
                return root if action == "create" else None
            self.editor.notify(f"Path not found! {parent}", severity="error")
            return None
        resolved_root = root.resolve()
        if not resolved_root.is_dir():
            self.editor.notify(
                f"Storage path exists but is not a directory: {resolved_root}",
                severity="error",
            )
            return None
        if not any(resolved_root.iterdir()):
            return resolved_root

        env_path = resolved_root / self.editor.local_env_filename
        if env_path.is_file():
            keys = list(read_local_env(env_path))[:10]
            preview = ", ".join(keys) if keys else "<none>"
            message = (
                f"Storage not empty, found {self.editor.local_env_filename} "
                f"with these env vars: {preview}.\n"
                "All these local env vars will be exported on runtime. "
                "Proceed?"
            )
        else:
            message = (
                "Storage not empty, but no "
                f"{self.editor.local_env_filename} found, initialize with "
                f"empty {self.editor.local_env_filename}?\n{resolved_root}"
            )
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Confirm storage directory",
                message=message,
                actions=(("proceed", "Proceed", "warning"),),
            )
        )
        return resolved_root if action == "proceed" else None

    async def set_current_as_default(self) -> None:
        """Set the selected live storage as the registry default."""
        kit = self.editor._require_kit()
        if kit is None or self.editor.current_storage_name is None:
            return
        if self.editor.current_storage_kind != "live":
            self.editor.notify(
                "Select a live storage first.",
                severity="warning",
            )
            return
        if self.editor.registry.default_storage == (
            self.editor.current_storage_name
        ):
            self.editor.notify(
                f"{self.editor.current_storage_name!r} is already the "
                "setup/editor default."
            )
            return
        try:
            self.editor.registry = kit.set_default_storage(
                name=self.editor.current_storage_name
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return
        await self.editor._refresh_storage_list(
            select_name=self.editor.current_storage_name
        )
        self.editor.notify(
            "Setup/editor default storage set to "
            f"{self.editor.current_storage_name!r}"
        )

    async def open_delete_storage_flow(self) -> None:
        """Prompt for unregister/delete behavior for the current storage."""
        if (
            self.editor.current_storage_kind not in {"live", "missing"}
            or self.editor.current_storage_name is None
        ):
            return
        record = self.editor._current_storage()
        can_delete_content = record.root.is_dir()
        message = (
            f"Storage: {record.name}\nRoot: {record.root}\n\n"
            "Choose whether to only unregister it or delete the "
            "directory contents too."
            if can_delete_content
            else (
                f"Storage: {record.name}\nRoot: {record.root}\n\n"
                "The storage root is missing or is not a directory. "
                "Only the registry entry will be removed."
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

    async def open_archive_storage_flow(self) -> None:
        """Prompt for archive options and compress the selected storage."""
        kit = self.editor._require_kit()
        if (
            kit is None
            or self.editor.current_storage_kind != "live"
            or self.editor.current_storage_name is None
        ):
            return
        record = self.editor._current_storage()
        options = await self.editor.push_screen_wait(
            ArchiveOptionsScreen(
                storage_name=record.name,
                source_root=record.root,
                default_archive=storage_archive_default_path(record.root),
            )
        )
        if options is None:
            return
        try:
            archive_path = await self.run_archive_progress(
                source_root=record.root,
                archive_path=options.archive_path,
            )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return
        self.editor.registry = kit.record_archived_storage(
            name=record.name,
            archive=archive_path,
            source_root=record.root,
        )
        if options.delete_source:
            removed = await self.remove_live_storage(
                record.name,
                delete_content=True,
            )
            if not removed:
                await self.editor._refresh_storage_list(select_name=record.name)
                self.editor.notify(
                    f"Archived {record.name!r}; source deletion was canceled.",
                    severity="warning",
                )
                return
        else:
            await self.editor._refresh_storage_list(select_name=record.name)
        self.editor.notify(
            f"Archived storage {record.name!r} to {archive_path}"
        )

    async def remove_live_storage(
        self,
        name: str,
        *,
        delete_content: bool,
    ) -> bool:
        """Remove one live storage and repair the default if needed.

        :param name: Storage registry selector to remove.
        :param delete_content: Whether to delete the storage directory too.
        :return: Whether the removal completed.
        """
        kit = self.editor._require_kit()
        if kit is None:
            return False
        try:
            record = self.editor.registry.selected(name)
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return False
        replacement = await self.default_choice_before_removal(name)
        if replacement is None:
            return False
        if delete_content and record.root.exists():
            try:
                shutil.rmtree(record.root)
            except OSError as exc:
                self.editor.notify(str(exc), severity="error")
                return False
        try:
            self.editor.registry = kit.unregister_storage(
                name=name,
                replacement_default=replacement.replacement_name,
            )
            if replacement.create_default_path is not None:
                replacement_name = kit.default_storage_name()
                self.editor.registry = kit.register_storage(
                    name=replacement_name,
                    root=replacement.create_default_path,
                    make_default=True,
                )
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error")
            return False
        select_name = replacement.replacement_name
        if select_name is None and replacement.create_default_path is not None:
            select_name = kit.default_storage_name()
        await self.editor._refresh_storage_list(select_name=select_name)
        self.editor.notify(f"Removed storage {name!r}")
        return True

    async def default_choice_before_removal(
        self,
        removed_name: str,
    ) -> RemovalDefaultChoice | None:
        """Return how the default should look after removing a storage.

        :param removed_name: Storage selector about to be removed.
        :return: Default repair decision, or ``None`` when canceled.
        """
        if self.editor.registry.default_storage != removed_name:
            return RemovalDefaultChoice()
        remaining = [
            name
            for name in ordered_existing_storage_names(self.editor.registry)
            if name != removed_name
        ]
        if remaining:
            actions: list[tuple[str, str, ButtonVariant]] = []
            for index, name in enumerate(remaining):
                variant: ButtonVariant = "primary" if index == 0 else "default"
                actions.append((f"default-{name}", name, variant))
            action = await self.editor.push_screen_wait(
                ConfirmScreen(
                    title="Choose setup/editor default",
                    message=(
                        f"{removed_name!r} is the setup/editor default "
                        "storage. "
                        "Choose the new setup/editor default before "
                        "removing it."
                    ),
                    actions=tuple(actions),
                )
            )
            if action is None or not action.startswith("default-"):
                return None
            return RemovalDefaultChoice(
                replacement_name=action.removeprefix("default-")
            )

        kit = self.editor._require_kit()
        if kit is None:
            return None
        result = await self.editor.push_screen_wait(
            DefaultPathScreen(
                default_path=kit.default_storage_data_root(),
                display_name=kit.spec.display_name,
            )
        )
        if result is None:
            return None
        if result.action == "leave":
            return RemovalDefaultChoice()
        return RemovalDefaultChoice(create_default_path=result.path)

    async def restore_or_prune_archived_storage(self, name: str) -> None:
        """Restore an archived row or delete it when its file is gone.

        :param name: Archived storage selector.
        """
        kit = self.editor._require_kit()
        if kit is None:
            return
        record = self.editor.registry.archived_storages.get(name)
        if record is None:
            return
        if not record.archive.is_file():
            self.editor.registry = kit.remove_archived_storage(name=name)
            await self.editor._refresh_storage_list()
            self.editor.notify(
                f"Removed stale archive entry {name!r}; file was not found.",
                severity="warning",
            )
            return
        await self.open_archive_import_flow(
            record.archive,
            default_name=record.name,
            default_destination=record.source_root,
        )

    async def run_archive_progress(
        self,
        *,
        source_root: Path,
        archive_path: Path,
    ) -> Path:
        """Run archive compression with a progress modal.

        :param source_root: Storage root to compress.
        :param archive_path: Archive path to write.
        :return: Written archive path.
        """
        return await self.run_storage_progress(
            title="Compressing storage",
            operation=lambda progress: archive_directory(
                source_root=source_root,
                archive_path=archive_path,
                progress=progress,
            ),
        )

    async def run_extract_progress(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
    ) -> Path:
        """Run archive extraction with a progress modal.

        :param archive_path: Existing archive to extract.
        :param destination_root: Directory that receives archive contents.
        :return: Destination directory.
        """
        return await self.run_storage_progress(
            title="Decompressing storage",
            operation=lambda progress: extract_archive(
                archive_path=archive_path,
                destination_root=destination_root,
                progress=progress,
            ),
        )

    async def run_storage_progress(
        self,
        *,
        title: str,
        operation: Callable[[Callable[[StorageArchiveProgress], None]], Path],
    ) -> Path:
        """Run one storage archive operation with a progress modal.

        :param title: Modal title shown above the progress bar.
        :param operation: Blocking storage operation that accepts progress
            callbacks and returns the final path.
        :return: Path returned by the storage operation.
        """
        progress_screen = ProgressScreen(title=title)
        await self.editor.push_screen(progress_screen)

        def progress(progress_update: StorageArchiveProgress) -> None:
            self.editor.call_from_thread(
                progress_screen.update_progress,
                progress_update,
            )

        worker = self.editor.run_worker(
            lambda: operation(progress),
            thread=True,
            exit_on_error=False,
        )
        try:
            return await worker.wait()
        finally:
            progress_screen.dismiss(None)
