"""Operations for optional AppRC workspace registries."""

from __future__ import annotations

# == Standard Library ========================
import logging
from dataclasses import replace
from pathlib import Path

from apprc.user_files.env_files.files import ensure_workspace_dotenv_file

# == Internal ================================
from apprc.user_files.workspace_roots._io import (
    load_workspace_registry_or_empty,
    ordered_workspace_names,
    write_workspace_registry,
)
from apprc.user_files.workspace_roots._naming import (
    suggested_workspace_name,
    suggested_workspace_root,
    validate_workspace_name,
)
from apprc.user_files.workspace_roots.model import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from apprc.user_files.workspace_roots.paths import (
    normalize_workspace_root_path,
    resolve_workspace_root_path,
)

LOG = logging.getLogger(__name__)

__all__ = [
    "ArchivedWorkspaceRecord",
    "WorkspaceRecord",
    "WorkspaceRegistry",
    "load_workspace_registry_or_empty",
    "ordered_workspace_names",
    "prune_missing_archived_workspaces",
    "record_archived_workspace",
    "register_workspace",
    "register_restored_workspace",
    "rename_workspace",
    "repoint_workspace",
    "remove_archived_workspace",
    "select_workspace",
    "suggested_workspace_name",
    "suggested_workspace_root",
    "unregister_workspace",
    "write_workspace_registry",
]


def register_workspace(
    *,
    name: str,
    root: Path,
    path: Path,
    workspace_dotenv_filename: str = "apprc.workspace.env",
) -> WorkspaceRegistry:
    """Add one workspace entry and write the registry.

    :param name: New workspace selector.
    :param root: Workspace root directory.
    :param path: AppRC TOML location.
    :param workspace_dotenv_filename: Workspace dotenv filename to create.
    :return: Updated registry.
    """
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    if name in current.workspaces:
        raise ValueError(f"Workspace name {name!r} is already registered.")
    if name in current.archived_workspaces:
        raise ValueError(
            f"Workspace name {name!r} is already used by an archived workspace."
        )
    resolved_root = resolve_workspace_root_path(root, base=current.path.parent)
    _reject_duplicate_workspace_root(
        current,
        root=resolved_root,
        requested_name=name,
    )
    root_existed = resolved_root.exists()
    workspace_dotenv = resolved_root / workspace_dotenv_filename
    workspace_dotenv_existed = workspace_dotenv.exists()

    try:
        resolved_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        ensure_workspace_dotenv_file(
            resolved_root, filename=workspace_dotenv_filename
        )
        updated = replace(
            current,
            workspaces={
                **dict(current.workspaces),
                name: WorkspaceRecord(name=name, root=resolved_root),
            },
            selected_workspace=current.selected_workspace or name,
        )
        write_workspace_registry(updated)
    except Exception as exc:
        _rollback_created_workspace_artifacts(
            root=resolved_root,
            root_existed=root_existed,
            workspace_dotenv=workspace_dotenv,
            workspace_dotenv_existed=workspace_dotenv_existed,
            original_error=exc,
        )
        raise
    return updated


def register_restored_workspace(
    *,
    name: str,
    root: Path,
    path: Path,
    archived_name: str | None = None,
    workspace_dotenv_filename: str = "apprc.workspace.env",
) -> WorkspaceRegistry:
    """Register an extracted archive and clear its archive row atomically.

    The archive extraction layer calls this operation before discarding its
    filesystem backup, so a registry failure restores the previous destination.

    :param name: Name for the restored live workspace.
    :param root: Installed archive destination.
    :param path: AppRC TOML location.
    :param archived_name: Archive row to remove after restoration.
    :param workspace_dotenv_filename: Required workspace marker filename.
    :return: Updated registry.
    """
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    if name in current.workspaces:
        raise ValueError(f"Workspace name {name!r} is already registered.")
    if name in current.archived_workspaces and name != archived_name:
        raise ValueError(
            f"Workspace name {name!r} is already used by another archive."
        )
    resolved_root = resolve_workspace_root_path(root, base=current.path.parent)
    _reject_duplicate_workspace_root(
        current,
        root=resolved_root,
        requested_name=name,
    )
    workspace_dotenv = resolved_root / workspace_dotenv_filename
    if not workspace_dotenv.is_file():
        raise ValueError(
            f"Restored workspace is missing its AppRC marker: {workspace_dotenv}"
        )
    archived_workspaces = dict(current.archived_workspaces)
    if archived_name is not None:
        archived_workspaces.pop(archived_name, None)
    updated = replace(
        current,
        workspaces={
            **dict(current.workspaces),
            name: WorkspaceRecord(name=name, root=resolved_root),
        },
        selected_workspace=current.selected_workspace or name,
        archived_workspaces=archived_workspaces,
    )
    write_workspace_registry(updated)
    return updated


def _update_workspace(
    *,
    current_name: str,
    name: str,
    root: Path | None,
    path: Path,
    reject_duplicate_root: bool = False,
) -> WorkspaceRegistry:
    """Rename or repoint one registered workspace without changing its files.

    The editor uses this operation when changing registry metadata. It keeps
    the workspace directory and dotenv file in place, and moves matching archive
    metadata to the new selector when the name changes. Passing ``None`` for
    ``root`` preserves the stored path spelling for a name-only update.

    :param current_name: Existing live workspace selector to replace.
    :param name: New selector for the workspace record.
    :param root: New workspace root recorded in the registry, or ``None`` to
        preserve the current root exactly.
    :param path: AppRC TOML location.
    :param reject_duplicate_root: Whether this operation changes the root and
        must reject aliases.
    :return: Updated registry after one atomic write.
    :raises ValueError: If the source is missing or the target name is used by
        another live or archived workspace.
    """
    validate_workspace_name(current_name)
    current = load_workspace_registry_or_empty(path)
    current_record = current.selected(current_name)
    validate_workspace_name(name)
    updated_root = (
        current_record.root
        if root is None
        else resolve_workspace_root_path(root, base=current.path.parent)
    )
    current_root = resolve_workspace_root_path(
        current_record.root,
        base=current.path.parent,
    )
    if name == current_name and updated_root == current_root:
        return current
    if reject_duplicate_root:
        _reject_duplicate_workspace_root(
            current,
            root=updated_root,
            requested_name=name,
            excluded_name=current_name,
        )

    if name != current_name:
        if name in current.workspaces:
            raise ValueError(
                f"Workspace name {name!r} is already used by a live workspace."
            )
        if name in current.archived_workspaces:
            raise ValueError(
                f"Workspace name {name!r} is already used by an archived workspace."
            )

    workspaces = dict(current.workspaces)
    workspaces.pop(current_name)
    workspaces[name] = WorkspaceRecord(name=name, root=updated_root)

    archived_workspaces = dict(current.archived_workspaces)
    if name != current_name:
        archived_record = archived_workspaces.pop(current_name, None)
        if archived_record is not None:
            archived_workspaces[name] = replace(archived_record, name=name)

    updated = replace(
        current,
        workspaces=workspaces,
        selected_workspace=(
            name
            if current.selected_workspace == current_name
            else current.selected_workspace
        ),
        archived_workspaces=archived_workspaces,
    )
    write_workspace_registry(updated)
    return updated


def _reject_duplicate_workspace_root(
    registry: WorkspaceRegistry,
    *,
    root: Path,
    requested_name: str,
    excluded_name: str | None = None,
) -> None:
    """Reject a new alias for an already registered resolved root.

    Older registries may contain aliases and remain readable. New writes must
    not add ambiguity because direct-path selection cannot choose one alias
    without inventing user intent.

    :param registry: Current registry state.
    :param root: Proposed resolved root.
    :param requested_name: Name being added or repointed.
    :param excluded_name: Existing row replaced by this operation.
    :return: None.
    :raises ValueError: If another live entry owns the same root.
    """
    for name, record in registry.workspaces.items():
        if name == excluded_name:
            continue
        registered_root = resolve_workspace_root_path(
            record.root,
            base=registry.path.parent,
        )
        if registered_root == root:
            raise ValueError(
                f"Workspace root {root} is already registered as {name!r}; "
                f"cannot also register it as {requested_name!r}."
            )


def rename_workspace(
    *,
    current_name: str,
    name: str,
    path: Path,
) -> WorkspaceRegistry:
    """Rename a workspace without changing its root.

    :param current_name: Registered selector to replace.
    :param name: New selector.
    :param path: AppRC TOML path.
    :return: Updated registry.
    """
    return _update_workspace(
        current_name=current_name,
        name=name,
        root=None,
        path=path,
    )


def repoint_workspace(
    *,
    name: str,
    root: Path,
    path: Path,
) -> WorkspaceRegistry:
    """Change a registry root without moving filesystem data.

    :param name: Registered selector to update.
    :param root: New root, resolved relative to ``apprc.toml``.
    :param path: AppRC TOML path.
    :return: Updated registry.
    """
    return _update_workspace(
        current_name=name,
        name=name,
        root=root,
        path=path,
        reject_duplicate_root=True,
    )


def select_workspace(*, name: str, path: Path) -> WorkspaceRegistry:
    """Persist the selected workspace name.

    :param name: Registered workspace to use when no runtime override exists.
    :param path: AppRC TOML path.
    :return: Updated registry.
    """
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    current.selected(name)
    if current.selected_workspace == name:
        return current
    updated = replace(current, selected_workspace=name)
    write_workspace_registry(updated)
    return updated


def _rollback_created_workspace_artifacts(
    *,
    root: Path,
    root_existed: bool,
    workspace_dotenv: Path,
    workspace_dotenv_existed: bool,
    original_error: Exception,
) -> None:
    """Best-effort removal of empty artifacts from a failed registration.

    :param root: Workspace root that may have been created by registration.
    :param root_existed: Whether the root existed before registration.
    :param workspace_dotenv: Workspace dotenv path that may have been created.
    :param workspace_dotenv_existed: Whether the dotenv file existed beforehand.
    :param original_error: Registration error that receives cleanup notes.
    """
    if not workspace_dotenv_existed:
        try:
            if (
                workspace_dotenv.is_file()
                and workspace_dotenv.stat().st_size == 0
            ):
                workspace_dotenv.unlink()
        except OSError as exc:
            _record_rollback_cleanup_failure(
                original_error=original_error,
                action="remove empty workspace env file",
                path=workspace_dotenv,
                cleanup_error=exc,
            )
    if root_existed:
        return
    try:
        root.rmdir()
    except OSError as exc:
        _record_rollback_cleanup_failure(
            original_error=original_error,
            action="remove created workspace root",
            path=root,
            cleanup_error=exc,
        )


def _record_rollback_cleanup_failure(
    *,
    original_error: Exception,
    action: str,
    path: Path,
    cleanup_error: OSError,
) -> None:
    """Expose one rollback cleanup failure without masking the root cause.

    :param original_error: Registration error that remains the raised error.
    :param action: Human-readable cleanup action that failed.
    :param path: Filesystem path targeted by cleanup.
    :param cleanup_error: Cleanup failure raised by the filesystem.
    """
    message = (
        "Workspace registration rollback could not "
        f"{action} {path}: {cleanup_error}"
    )
    LOG.warning(message)
    original_error.add_note(message)


def unregister_workspace(
    *,
    name: str,
    path: Path,
) -> WorkspaceRegistry:
    """Remove one live workspace entry from the registry.

    :param name: Live workspace selector to remove.
    :param path: AppRC TOML location.
    :return: Updated registry.
    :raises ValueError: If ``name`` is unknown.
    """
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    current.selected(name)
    workspaces = dict(current.workspaces)
    workspaces.pop(name)

    updated = replace(
        current,
        workspaces=workspaces,
        selected_workspace=(
            None
            if current.selected_workspace == name
            else current.selected_workspace
        ),
    )
    write_workspace_registry(updated)
    return updated


def record_archived_workspace(
    *,
    name: str,
    archive: Path,
    source_root: Path,
    path: Path,
) -> WorkspaceRegistry:
    """Remember the last archive path for one workspace selector."""
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    archived_workspaces = dict(current.archived_workspaces)
    archived_workspaces[name] = ArchivedWorkspaceRecord(
        name=name,
        archive=normalize_workspace_root_path(archive).expanduser(),
        source_root=normalize_workspace_root_path(source_root).expanduser(),
    )
    updated = replace(
        current,
        archived_workspaces=archived_workspaces,
    )
    write_workspace_registry(updated)
    return updated


def remove_archived_workspace(
    *,
    name: str,
    path: Path,
) -> WorkspaceRegistry:
    """Remove one stale or restored archive convenience entry."""
    validate_workspace_name(name)
    current = load_workspace_registry_or_empty(path)
    archived_workspaces = dict(current.archived_workspaces)
    archived_workspaces.pop(name, None)
    updated = replace(
        current,
        archived_workspaces=archived_workspaces,
    )
    write_workspace_registry(updated)
    return updated


def prune_missing_archived_workspaces(
    *,
    path: Path,
) -> WorkspaceRegistry:
    """Drop archive records whose last known file no longer exists."""
    current = load_workspace_registry_or_empty(path)
    archived_workspaces = {
        name: record
        for name, record in current.archived_workspaces.items()
        if record.archive.is_file()
    }
    if archived_workspaces == current.archived_workspaces:
        return current
    updated = replace(
        current,
        archived_workspaces=archived_workspaces,
    )
    write_workspace_registry(updated)
    return updated
