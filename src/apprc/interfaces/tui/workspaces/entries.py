"""Workspace-list helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == 3rd Party ===============================
from rich.text import Text

from apprc.interfaces.tui._styles import (
    ARCHIVE_STYLE,
    MISSING_STYLE,
    path_text,
    workspace_name_text,
)

# == Internal ================================
from apprc.user_files.workspace_roots.archive import (
    is_workspace_archive_path,
    workspace_root_name_from_archive,
)
from apprc.user_files.workspace_roots.registry import (
    WorkspaceRegistry,
    ordered_workspace_names,
)

WorkspaceEntryKind = Literal["live", "missing", "archived"]


@dataclass(frozen=True, slots=True)
class WorkspaceListEntry:
    """One selectable row in the editor workspace list."""

    kind: WorkspaceEntryKind
    name: str


def ordered_workspace_entries(
    registry: WorkspaceRegistry,
) -> list[WorkspaceListEntry]:
    """Return registered workspaces followed by archived restore rows.

    :param registry: User workspace registry to render.
    :return: Workspace rows in the order shown by the editor.
    """
    entries = [
        WorkspaceListEntry(
            kind=workspace_entry_kind(registry, name),
            name=name,
        )
        for name in ordered_workspace_names(registry)
    ]
    live_names = {entry.name for entry in entries}
    entries.extend(
        WorkspaceListEntry(kind="archived", name=name)
        for name in sorted(registry.archived_workspaces)
        if name not in live_names
    )
    return entries


def workspace_entry_kind(
    registry: WorkspaceRegistry,
    name: str,
) -> WorkspaceEntryKind:
    """Return whether one registered workspace root can be edited.

    :param registry: User workspace registry to inspect.
    :param name: Registry selector to inspect.
    :return: ``live`` when the root is a directory, otherwise ``missing``.
    """
    record = registry.selected(name)
    return "live" if record.root.is_dir() else "missing"


def workspace_entry_index(
    entries: list[WorkspaceListEntry],
    name: str | None,
) -> int | None:
    """Return the first list index for a workspace name.

    :param entries: Workspace entries currently shown by the editor.
    :param name: Workspace selector to find.
    :return: Matching index, or ``None`` when no row matches.
    """
    if name is None:
        return None
    for index, entry in enumerate(entries):
        if entry.name == name:
            return index
    return None


def workspace_entry_label(
    registry: WorkspaceRegistry,
    entry: WorkspaceListEntry,
) -> Text:
    """Return a readable workspace-list label.

    :param registry: Workspace registry containing ``entry``.
    :param entry: Workspace row to render.
    :return: Two-line label for Textual's workspace list.
    """
    if entry.kind in {"live", "missing"}:
        record = registry.selected(entry.name)
        label = workspace_name_text(record.name)
        if entry.kind == "missing":
            label.append(" [missing]", style=MISSING_STYLE)
        label.append("\n")
        label.append_text(path_text(record.root))
        return label
    record = registry.archived_workspaces[entry.name]
    label = workspace_name_text(record.name)
    label.append(" [Last Archived]", style=ARCHIVE_STYLE)
    label.append("\n")
    label.append_text(path_text(record.archive))
    return label


def suggest_workspace_name(
    path: Path,
    *,
    fallback_name: str,
) -> str:
    """Return a simple workspace-name suggestion from a path.

    :param path: Directory or archive path entered by the user.
    :param fallback_name: Selector used when no readable path name exists.
    :return: Workspace selector suggestion.
    """
    name = path.name or fallback_name
    if is_workspace_archive_path(path):
        name = workspace_root_name_from_archive(path)
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
    return normalized or fallback_name
