"""Storage-list helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == Internal ================================
from apprc.config.storage.archive import (
    is_storage_archive_path,
    storage_root_name_from_archive,
)
from apprc.config.storage.registry import (
    StorageRegistry,
    ordered_storage_names,
)

StorageEntryKind = Literal["live", "missing", "archived"]


@dataclass(frozen=True, slots=True)
class StorageListEntry:
    """One selectable row in the editor storage list."""

    kind: StorageEntryKind
    name: str


def ordered_storage_entries(
    registry: StorageRegistry,
) -> list[StorageListEntry]:
    """Return registered storages followed by archived restore rows.

    :param registry: User storage registry to render.
    :return: Storage rows in the order shown by the editor.
    """
    entries = [
        StorageListEntry(
            kind=storage_entry_kind(registry, name),
            name=name,
        )
        for name in ordered_storage_names(registry)
    ]
    live_names = {entry.name for entry in entries}
    entries.extend(
        StorageListEntry(kind="archived", name=name)
        for name in sorted(registry.archived_storages)
        if name not in live_names
    )
    return entries


def ordered_existing_storage_names(registry: StorageRegistry) -> list[str]:
    """Return registered storages whose roots are existing directories.

    :param registry: User storage registry to inspect.
    :return: Default-first storage names with existing roots.
    """
    return [
        name
        for name in ordered_storage_names(registry)
        if registry.selected(name).root.is_dir()
    ]


def storage_entry_kind(
    registry: StorageRegistry,
    name: str,
) -> StorageEntryKind:
    """Return whether one registered storage root can be edited.

    :param registry: User storage registry to inspect.
    :param name: Registry selector to inspect.
    :return: ``live`` when the root is a directory, otherwise ``missing``.
    """
    record = registry.selected(name)
    return "live" if record.root.is_dir() else "missing"


def storage_entry_index(
    entries: list[StorageListEntry],
    name: str | None,
) -> int | None:
    """Return the first list index for a storage name.

    :param entries: Storage entries currently shown by the editor.
    :param name: Storage selector to find.
    :return: Matching index, or ``None`` when no row matches.
    """
    if name is None:
        return None
    for index, entry in enumerate(entries):
        if entry.name == name:
            return index
    return None


def storage_entry_label(
    registry: StorageRegistry,
    entry: StorageListEntry,
) -> str:
    """Return a readable storage-list label.

    :param registry: User storage registry containing ``entry``.
    :param entry: Storage row to render.
    :return: Two-line label for Textual's storage list.
    """
    if entry.kind in {"live", "missing"}:
        record = registry.selected(entry.name)
        default = (
            " [default]" if record.name == registry.default_storage else ""
        )
        missing = " [missing]" if entry.kind == "missing" else ""
        return f"{record.name}{default}{missing}\n{record.root}"
    record = registry.archived_storages[entry.name]
    return f"{record.name} [Last Archived]\n{record.archive}"


def suggest_storage_name(
    path: Path,
    *,
    fallback_name: str,
) -> str:
    """Return a simple registry-name suggestion from a path.

    :param path: Directory or archive path entered by the user.
    :param fallback_name: Selector used when no readable path name exists.
    :return: Registry-safe selector suggestion.
    """
    name = path.name or fallback_name
    if is_storage_archive_path(path):
        name = storage_root_name_from_archive(path)
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
    return normalized or fallback_name
