"""Workspace registry and filesystem operations for application callers."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths
from apprc.definition.resolution import ResolveOptions
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.layouts import resolve_app_paths
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import (
    ensure_owned_path,
    inspect_ownership,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import managed_write_lock
from apprc.user_files.env_files.files import ensure_workspace_dotenv_file
from apprc.user_files.env_files.secrets import (
    ensure_secret_file,
    secret_companion_path,
)
from apprc.user_files.workspace_roots import registry as workspace_registry
from apprc.user_files.workspace_roots._loading import (
    WorkspaceRegistryInspection,
    inspect_workspace_registry,
)
from apprc.user_files.workspace_roots.archive import (
    WorkspaceArchiveProgress,
    archive_workspace_directory,
    extract_workspace_archive,
)
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.move import (
    WorkspaceMoveResult,
    move_workspace,
)
from apprc.user_files.workspace_roots.paths import resolve_workspace_root_path


class WorkspaceManager:
    """Coordinate named workspace roots and their archive lifecycle.

    :param spec: Application declaration that enables workspace selection.
    :param options: Invocation options used to resolve managed application paths.
    :param environment: Captured environment, or the current process environment.
    :param app_paths: Previously resolved application paths for this invocation.
    """

    def __init__(
        self,
        spec: AppConfigSpec,
        *,
        options: ResolveOptions | None = None,
        environment: Mapping[str, str] | None = None,
        app_paths: AppPaths | None = None,
    ) -> None:
        spec.require_workspaces()
        self.spec = spec
        self.options = options or ResolveOptions()
        self.environment = MappingProxyType(
            dict(os.environ if environment is None else environment)
        )
        self.app_paths = app_paths or resolve_app_paths(
            spec, self.options, self.environment
        )
        self._files = AppFiles(spec, self.app_paths)

    def _require_registry(self) -> None:
        """Reject persistent registry operations for direct-only declarations."""
        if not self.spec.require_workspaces().registry:
            raise ValueError(
                "This application uses direct workspace paths, not a registry."
            )

    def registry_path(self) -> Path:
        """Return the fixed workspace registry path without creating it."""
        self._require_registry()
        return self._files.config_file()

    def registry(self) -> WorkspaceRegistry:
        """Read the current registry or return its empty missing-file state."""
        self._require_registry()
        return workspace_registry.load_workspace_registry_or_empty(
            self.registry_path()
        )

    def inspect_registry(self) -> WorkspaceRegistryInspection:
        """Inspect registry readiness without creating files."""
        self._require_registry()
        return inspect_workspace_registry(self.spec, app_paths=self.app_paths)

    def initialize_workspace(self, root: Path) -> Path:
        """Create a direct-only workspace and its ordinary dotenv file.

        This explicit setup operation never reads or writes workspace registry
        state. Existing workspace contents and permissions are left untouched.

        :param root: Workspace directory path, resolved against the current directory when relative.
        :return: Absolute workspace root.
        :raises ValueError: If this declaration uses a registry, the path is
            unsafe, or it overlaps an application-managed root.
        """
        if self.spec.require_workspaces().registry:
            raise ValueError(
                "Direct workspace initialization is only available without a registry."
            )
        resolved = resolve_workspace_root_path(root, base=Path.cwd())
        assert_no_links(resolved)
        self._reject_managed_overlap(resolved)
        create_private_directory_if_missing(resolved)
        assert_no_links(resolved / self.spec.workspace_dotenv_filename)
        with managed_write_lock(resolved):
            ensure_workspace_dotenv_file(
                resolved, filename=self.spec.workspace_dotenv_filename
            )
        return resolved

    def register_workspace(self, name: str, root: Path) -> WorkspaceRegistry:
        """Register and initialize a workspace's local dotenv files."""
        self._require_registry()
        registry_path = self.registry_path()
        base = registry_path.parent
        resolved = resolve_workspace_root_path(root, base=base)
        assert_no_links(resolved)
        self._reject_managed_overlap(resolved)
        with managed_write_lock(base, resolved, private_directories=(base,)):
            ensure_owned_path(self.spec, self.app_paths, "config")
            current = workspace_registry.register_workspace(
                name=name,
                root=resolved,
                path=registry_path,
                workspace_dotenv_filename=self.spec.workspace_dotenv_filename,
            )
            ensure_secret_file(
                self._files.workspace_secret_dotenv_path(
                    current.workspaces[name].root
                )
            )
            return current

    def select_workspace(self, name: str) -> WorkspaceRegistry | Path:
        """Select a registered name, or return an explicit direct-only path.

        Direct-only declarations accept an explicit path and never read or write
        the registry. Bare names are rejected because they could be mistaken for
        an unregistered registry selector.
        """
        if not self.spec.require_workspaces().registry:
            if not Path(name).is_absolute() and (
                "/" not in name
                and "\\" not in name
                and not name.startswith(".")
            ):
                raise ValueError("Named workspaces require a registry.")
            candidate = resolve_workspace_root_path(name, base=Path.cwd())
            if not candidate.is_dir():
                raise ValueError(
                    f"Direct workspace is not an existing directory: {candidate}"
                )
            assert_no_links(candidate)
            self._reject_managed_overlap(candidate)
            return candidate
        registry_path = self.registry_path()
        with managed_write_lock(
            registry_path.parent, private_directories=(registry_path.parent,)
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            return workspace_registry.select_workspace(
                name=name, path=registry_path
            )

    def rename_workspace(self, old: str, new: str) -> WorkspaceRegistry:
        """Rename a registry entry without moving workspace data."""
        self._require_registry()
        path = self.registry_path()
        with managed_write_lock(
            path.parent, private_directories=(path.parent,)
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            return workspace_registry.rename_workspace(
                current_name=old, name=new, path=path
            )

    def repoint_workspace(self, name: str, root: Path) -> WorkspaceRegistry:
        """Attach an existing root and initialize its ordinary workspace config."""
        self._require_registry()
        registry_path = self.registry_path()
        resolved = resolve_workspace_root_path(root, base=registry_path.parent)
        assert_no_links(resolved)
        self._reject_managed_overlap(resolved)
        if not resolved.is_dir():
            raise ValueError(
                f"Workspace root is not an existing directory: {resolved}"
            )
        with managed_write_lock(
            registry_path.parent,
            resolved,
            private_directories=(registry_path.parent,),
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            workspace_registry.load_workspace_registry_or_empty(
                registry_path
            ).selected(name)
            ensure_workspace_dotenv_file(
                resolved, filename=self.spec.workspace_dotenv_filename
            )
            return workspace_registry.repoint_workspace(
                name=name, root=resolved, path=registry_path
            )

    def remove_workspace(self, name: str) -> WorkspaceRegistry:
        """Unregister a workspace while leaving its directory untouched."""
        self._require_registry()
        registry_path = self.registry_path()
        current = workspace_registry.load_workspace_registry_or_empty(
            registry_path
        )
        root = current.selected(name).root
        with managed_write_lock(
            registry_path.parent,
            root,
            private_directories=(registry_path.parent,),
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            return workspace_registry.unregister_workspace(
                name=name, path=registry_path
            )

    def remove_archive_record(self, name: str) -> WorkspaceRegistry:
        """Forget archive metadata without deleting the archive file."""
        self._require_registry()
        registry_path = self.registry_path()
        with managed_write_lock(
            registry_path.parent, private_directories=(registry_path.parent,)
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            return workspace_registry.remove_archived_workspace(
                name=name, path=registry_path
            )

    def move_workspace(self, name: str, root: Path) -> WorkspaceMoveResult:
        """Move a registered root using the root package's transactional move."""
        self._require_registry()
        registry_path = self.registry_path()
        current = workspace_registry.load_workspace_registry_or_empty(
            registry_path
        )
        source = current.selected(name).root
        destination = resolve_workspace_root_path(
            root, base=registry_path.parent
        )
        assert_no_links(destination)
        self._reject_managed_overlap(destination)
        assert_no_links(source)
        self._reject_managed_overlap(source)
        with managed_write_lock(registry_path.parent, source, destination):
            ensure_owned_path(self.spec, self.app_paths, "config")
            return move_workspace(
                name=name, destination=destination, path=registry_path
            )

    def archive_workspace(
        self,
        name: str,
        destination: Path,
        *,
        progress: Callable[[WorkspaceArchiveProgress], None] | None = None,
    ) -> Path:
        """Create an archive of a workspace, excluding its private secret file."""
        self._require_registry()
        registry_path = self.registry_path()
        record = workspace_registry.load_workspace_registry_or_empty(
            registry_path
        ).selected(name)
        root = record.root
        archive = Path(destination).expanduser().absolute()
        assert_no_links(root)
        assert_no_links(archive.parent)
        self._reject_managed_overlap(root)
        self._reject_managed_overlap(archive)
        assert_no_links(archive)
        if (
            archive == root
            or archive.is_relative_to(root)
            or root.is_relative_to(archive)
        ):
            raise ValueError(
                "Workspace archive destination and root must not overlap."
            )
        with managed_write_lock(registry_path.parent, root, archive.parent):
            ensure_owned_path(self.spec, self.app_paths, "config")
            result = archive_workspace_directory(
                source_root=root,
                archive_path=archive,
                progress=progress,
                excluded_names=(
                    secret_companion_path(
                        self._files.workspace_dotenv_path(root)
                    ).name,
                ),
            )
            workspace_registry.record_archived_workspace(
                name=name, archive=result, source_root=root, path=registry_path
            )
            return result

    def restore_workspace(
        self,
        name: str,
        destination: Path,
        *,
        archive: Path | None = None,
        archived_name: str | None = None,
        replace_existing: bool = False,
        progress: Callable[[WorkspaceArchiveProgress], None] | None = None,
    ) -> Path:
        """Stage and install an archive, rolling back if registry commit fails."""
        self._require_registry()
        registry_path = self.registry_path()
        current = workspace_registry.load_workspace_registry_or_empty(
            registry_path
        )
        archive_record = current.archived_workspaces.get(name)
        archive_path = (
            archive
            if archive is not None
            else (
                archive_record.archive if archive_record is not None else None
            )
        )
        if archive_path is None:
            raise ValueError(f"No archive is available for workspace {name!r}.")
        assert_no_links(archive_path)
        resolved = resolve_workspace_root_path(
            destination, base=registry_path.parent
        )
        self._reject_managed_overlap(resolved)
        if (
            archive_path == resolved
            or archive_path.is_relative_to(resolved)
            or resolved.is_relative_to(archive_path)
        ):
            raise ValueError(
                "Workspace archive and restore destination must not overlap."
            )

        def register(root: Path) -> None:
            """Commit the workspace record before discarding extraction rollback."""
            workspace_registry.register_restored_workspace(
                name=name,
                root=root,
                path=registry_path,
                archived_name=archived_name or name,
                workspace_dotenv_filename=self.spec.workspace_dotenv_filename,
            )

        with managed_write_lock(
            registry_path.parent,
            resolved,
            private_directories=(registry_path.parent,),
        ):
            ensure_owned_path(self.spec, self.app_paths, "config")
            result = extract_workspace_archive(
                archive_path=archive_path,
                destination_root=resolved,
                replace_existing=replace_existing,
                progress=progress,
                after_install=register,
            )
            ensure_secret_file(self._files.workspace_secret_dotenv_path(result))
            return result

    def _reject_managed_overlap(self, root: Path) -> None:
        """Reject roots nested with any declared application-managed location."""
        candidate = root.expanduser().absolute()
        for kind, managed in (
            ("config", self.app_paths.config_dir),
            ("appdata", self.app_paths.appdata_dir),
            ("cache", self.app_paths.cache_dir),
            ("state", self.app_paths.state_dir),
            ("logs", self.app_paths.logs_dir),
        ):
            if managed is None:
                continue
            managed = managed.expanduser().absolute()
            if (
                candidate == managed
                or candidate in managed.parents
                or managed in candidate.parents
            ):
                raise ValueError(
                    f"Workspace root overlaps managed {kind} directory: {candidate}"
                )
            if kind == "appdata":
                inspect_ownership(managed, self.spec.app_id, "appdata")
            elif kind == "cache":
                inspect_ownership(managed, self.spec.app_id, "cache")
            elif kind in {"state", "logs"}:
                inspect_ownership(managed, self.spec.app_id, "state")
