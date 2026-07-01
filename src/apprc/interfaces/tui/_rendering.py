"""Render config field metadata for the Textual editor.

The interactive editor in :mod:`apprc.interfaces.tui` has two jobs: react to
Textual events and show a readable table of declared config fields. Keeping
the table cells in this module makes the visual policy easy to find and easy
to test without starting a terminal UI.

Applications do not normally import this module directly. They declare
``ConfigField`` and ``ConfigOwner`` objects, then ``ConfigEditorApp`` calls
these helpers to turn that metadata into Rich renderables.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

# == 3rd Party ===============================
from rich.text import Text

# == Internal ================================
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.env_config.sentinels import CONFIG_MISSING
from apprc.user_files.storage_roots.registry import (
    ArchivedStorageRecord,
    StorageRecord,
)
from apprc.interfaces.tui._styles import (
    ARCHIVE_STYLE,
    BOOL_STYLE,
    CHOICE_STYLE,
    DEFAULT_STYLE,
    GENERIC_VALUE_STYLE,
    LABEL_STYLE,
    MISSING_STYLE,
    NUMBER_STYLE,
    PATH_STYLE,
    REQUIRED_STYLE,
    SECRET_STYLE,
    TEXT_STYLE,
    label_value_text,
    lines_text,
    path_text,
    storage_name_text,
)

FIELD_TABLE_COLUMNS = (
    "#",
    "Section",
    "Key",
    "Effective",
    "Shell",
    "App-wide",
    "Storage",
    "Default",
    "Explanation",
)
_SEPARATOR_CELL_WIDTHS = (3, 14, 22, 12, 10, 14, 14, 14, 32)

type FieldTableCell = str | Text


@dataclass(frozen=True, slots=True)
class FieldTableRow:
    """One DataTable row plus the env key it represents.

    Separator rows have ``env_key=None`` so the editor can ignore clicks on
    visual dividers while still keeping table indices aligned.

    :param env_key: Full env key for editable rows, or ``None`` for separators.
    :param cells: Rich/Textual renderables passed to ``DataTable.add_row``.
    :param height: Optional row height override for visual separators.
    """

    env_key: str | None
    cells: tuple[FieldTableCell, ...]
    height: int | None = None


def build_field_table_rows(
    *,
    owners: Iterable[ConfigOwner],
    app_values: Mapping[str, str],
    storage_values: Mapping[str, str],
    shared_values: Mapping[str, str] | None,
    include_app: bool,
    include_storage: bool,
    hidden_env_keys: set[str] | frozenset[str],
    shell_env: Mapping[str, str],
) -> tuple[FieldTableRow, ...]:
    """Return all editor table rows in declaration order.

    The function owns table-only decisions: row numbering, section separators,
    source cells, effective values, defaults, and compact explanations.
    The Textual app owns widget lifecycle and persistence.

    :param owners: Declared config sections to show.
    :param app_values: Parsed app-wide dotenv values.
    :param storage_values: Parsed storage dotenv values.
    :param shared_values: Parsed packaged shared dotenv values, when known.
    :param include_app: Whether to show the app-wide source column as active.
    :param include_storage: Whether to show the storage source column as active.
    :param hidden_env_keys: Full env keys omitted from the editable key list.
    :param shell_env: Current shell/process environment mapping.
    :return: Rows ready for ``DataTable.add_row``.
    """
    rows: list[FieldTableRow] = []
    row_number = 1
    rendered_section = False
    for owner in owners:
        visible_specs = [
            spec
            for spec in owner.fields
            if owner.env_key(spec.name) not in hidden_env_keys
        ]
        if not visible_specs:
            continue
        if rendered_section:
            rows.append(section_separator_row())
        rendered_section = True
        for spec in visible_specs:
            env_key = owner.env_key(spec.name)
            app_value = app_values.get(env_key) if include_app else None
            storage_value = (
                storage_values.get(env_key) if include_storage else None
            )
            shell_value = shell_env.get(env_key)
            shared_value = shared_source_value(
                spec=spec,
                env_key=env_key,
                shared_values=shared_values,
            )
            env_is_set = env_key in shell_env
            effective_value = first_effective_value(
                shell_value=shell_value,
                storage_value=storage_value,
                app_value=app_value,
                shared_value=shared_value,
            )
            rows.append(
                FieldTableRow(
                    env_key=env_key,
                    cells=(
                        str(row_number),
                        Text(owner.title, style="bold"),
                        env_key,
                        source_value_cell(spec, effective_value),
                        shell_status_cell(env_is_set),
                        source_value_cell(spec, app_value),
                        source_value_cell(spec, storage_value),
                        default_value_cell(
                            spec,
                            app_value=app_value,
                            storage_value=storage_value,
                            env_is_set=env_is_set,
                            shared_value=shared_value,
                        ),
                        Text(short_explanation(spec), style=LABEL_STYLE),
                    ),
                )
            )
            row_number += 1
    return tuple(rows)


def default_value_cell(
    spec: ConfigField,
    *,
    app_value: str | None,
    storage_value: str | None,
    env_is_set: bool,
    shared_value: str | None,
) -> FieldTableCell:
    """Return the table value for packaged/default config.

    Required fields only show the red ``<required>`` marker when no layer that
    beats the default column provides a value. Otherwise the empty default is
    visually quiet because the value is satisfied elsewhere.

    :param spec: Field declaration that describes type and fallback.
    :param app_value: App-wide value currently shown in the row.
    :param storage_value: Storage value currently shown in the row.
    :param env_is_set: Whether the process environment sets this env key.
    :param shared_value: Packaged or declared default value.
    :return: Empty text, required marker, or styled default value.
    """
    if shared_value is None:
        if app_value is None and storage_value is None and not env_is_set:
            return Text("<required>", style=REQUIRED_STYLE)
        return ""
    return Text(shared_value, style=value_style(spec))


def source_value_cell(spec: ConfigField, value: str | None) -> FieldTableCell:
    """Return one table source value with redaction and type color.

    Missing and empty values remain visually quiet so unset overrides do not
    compete with defaults. Secret values show only a placeholder.

    :param spec: Field declaration that describes type and secrecy.
    :param value: Parsed dotenv string from one source.
    :return: Empty text or a styled visible placeholder/value.
    """
    if value is None or value == "":
        return ""
    if spec.secret:
        return Text("<secret>", style=value_style(spec))
    return Text(value, style=value_style(spec))


def first_effective_value(
    *,
    shell_value: str | None,
    storage_value: str | None,
    app_value: str | None,
    shared_value: str | None,
) -> str | None:
    """Return the effective editor-visible value by runtime precedence."""
    for value in (shell_value, storage_value, app_value, shared_value):
        if value is not None:
            return value
    return None


def shared_source_value(
    *,
    spec: ConfigField,
    env_key: str,
    shared_values: Mapping[str, str] | None,
) -> str | None:
    """Return the packaged or declared shared value for one field."""
    if shared_values is not None and env_key in shared_values:
        return shared_values[env_key]
    value = spec.shared_env_value()
    if value is CONFIG_MISSING:
        return None
    return str(value)


def value_style(spec: ConfigField) -> str:
    """Return the Rich style used for declared values of one field.

    The style follows the declared config contract instead of parsing the
    string in the dotenv file. That keeps colors stable even before the value
    is converted by ``typed-settings``.

    :param spec: Field declaration that owns type and choices.
    :return: Rich style string.
    """
    if spec.secret:
        return SECRET_STYLE
    if spec.choices:
        return CHOICE_STYLE
    return field_type_style(spec)


def field_type_style(spec: ConfigField) -> str:
    """Return the Rich style used for one declared Python type.

    Unlike :func:`value_style`, this helper ignores choices and secret
    redaction because it describes the type itself, not a concrete value.

    :param spec: Field declaration that owns the Python type.
    :return: Rich style string for the type metadata.
    """
    if spec.python_type is bool:
        return BOOL_STYLE
    if spec.python_type in {int, float}:
        return NUMBER_STYLE
    if spec.python_type is Path:
        return PATH_STYLE
    return TEXT_STYLE


def possible_values_style(spec: ConfigField) -> str:
    """Return the Rich style used for accepted-value metadata.

    :param spec: Field declaration whose accepted values are displayed.
    :return: Choice styling for explicit choices, otherwise generic styling.
    """
    if spec.choices:
        return CHOICE_STYLE
    return GENERIC_VALUE_STYLE


def section_separator_row() -> FieldTableRow:
    """Return a non-editable visual divider between config sections."""
    return FieldTableRow(
        env_key=None,
        cells=tuple(
            Text("─" * width, style=LABEL_STYLE)
            for width in _SEPARATOR_CELL_WIDTHS
        ),
        height=1,
    )


def shell_status_cell(env_is_set: bool) -> Text:
    """Return whether the process environment currently sets a field."""
    if env_is_set:
        return Text("shell", style=DEFAULT_STYLE)
    return Text("unset", style=LABEL_STYLE)


def short_explanation(spec: ConfigField) -> str:
    """Return the compact explanation used in the rightmost table column."""
    return spec.explanation_short or spec.explanation_long


def field_type_label(spec: ConfigField) -> str:
    """Return a reader-facing type label for the edit modal."""
    type_name = getattr(spec.python_type, "__name__", None)
    if isinstance(type_name, str):
        return type_name
    return str(spec.python_type)


def possible_values_label(spec: ConfigField) -> str:
    """Return accepted values for the edit modal metadata block."""
    if spec.choices:
        return ", ".join(spec.choices)
    if spec.python_type is bool:
        return "true, false, yes, no, on, off, 1, 0"
    if spec.python_type is int:
        return "integer"
    if spec.python_type is float:
        return "number"
    if spec.python_type is Path:
        return "filesystem path"
    return "free text"


def live_storage_title(record: StorageRecord, storage_env: Path) -> Text:
    """Return the title shown for one editable live storage.

    :param record: Registry storage record.
    :param storage_env: Storage dotenv path.
    :return: Multi-line title for the selected storage.
    """
    title = storage_name_text(record.name)
    title.append(": ")
    title.append_text(path_text(record.root))
    return lines_text(title, path_text(storage_env))


def active_storage_title(storage_root: Path, storage_env: Path) -> Text:
    """Return the title shown for an unregistered active storage path.

    :param storage_root: Active storage root selected by ``<APP>_STORAGE``.
    :param storage_env: Storage dotenv path.
    :return: Multi-line title for the selected path.
    """
    title = Text("Active storage", style="bold")
    title.append(": ")
    title.append_text(path_text(storage_root))
    return lines_text(title, path_text(storage_env))


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
        "No storage env file is available.",
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
