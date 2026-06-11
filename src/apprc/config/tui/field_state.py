"""Pure field-state helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# == 3rd Party ===============================
from rich.text import Text

# == Internal ================================
from apprc.config.schema import (
    ConfigField,
    ConfigOwner,
    find_field_by_env_key,
)
from apprc.config.storage.registry import ArchivedStorageRecord, StorageRecord
from apprc.config.tui.styles import (
    ARCHIVE_STYLE,
    MISSING_STYLE,
    label_value_text,
    lines_text,
    path_text,
    storage_name_text,
)


@dataclass(frozen=True, slots=True)
class SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


def selected_field_for_row(
    *,
    owners: Iterable[ConfigOwner],
    row_env_keys: Sequence[str | None],
    row_index: int | None,
) -> SelectedField | None:
    """Return the config field represented by one table row.

    Separator rows and out-of-range indices have no editable field attached.

    :param owners: Declared config sections shown in the table.
    :param row_env_keys: Env key per table row, with ``None`` for separators.
    :param row_index: Current table cursor row.
    :return: Selected field metadata, or ``None`` for non-field rows.
    """
    if row_index is None or row_index < 0 or row_index >= len(row_env_keys):
        return None
    env_key = row_env_keys[row_index]
    if env_key is None:
        return None
    found = find_field_by_env_key(owners, env_key)
    if found is None:
        return None
    owner, spec = found
    return SelectedField(owner=owner, spec=spec)


def live_storage_title(record: StorageRecord, local_env: Path) -> Text:
    """Return the title shown for one editable live storage.

    :param record: Registry storage record.
    :param local_env: Storage-local dotenv path.
    :return: Multi-line title for the selected storage.
    """
    title = storage_name_text(record.name)
    title.append(": ")
    title.append_text(path_text(record.root))
    return lines_text(title, path_text(local_env))


def missing_storage_title(record: StorageRecord) -> Text:
    """Return the title shown when a registered storage root is missing.

    :param record: Registry storage record whose root is unavailable.
    :return: Multi-line title explaining the missing root.
    """
    title = storage_name_text(record.name)
    title.append(": ")
    title.append("Missing storage root", style=MISSING_STYLE)
    return lines_text(
        title,
        label_value_text("Root", path_text(record.root)),
        "No storage-local env file is available.",
    )


def archived_storage_title(record: ArchivedStorageRecord) -> Text:
    """Return the title shown for an archived storage record.

    :param record: Archived storage metadata from the registry.
    :return: Multi-line title with archive and last source paths.
    """
    title = storage_name_text(record.name)
    title.append(": ")
    title.append("Last Archived", style=ARCHIVE_STYLE)
    return lines_text(
        title,
        label_value_text("Archive", path_text(record.archive)),
        label_value_text("Last source", path_text(record.source_root)),
    )
