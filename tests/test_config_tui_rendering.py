from __future__ import annotations

from pathlib import Path

from rich.text import Text

from apprc.user_files.storage_roots.registry import (
    ArchivedStorageRecord,
    StorageRecord,
)
from apprc.interfaces.tui._field_state import EditableConfigValueSource
from apprc.interfaces.tui._rendering import (
    FIELD_TABLE_COLUMNS,
    FieldTableRow,
    archived_storage_title,
    build_field_table_rows,
    field_type_label,
    field_type_style,
    live_storage_title,
    missing_storage_title,
    possible_values_label,
    possible_values_style,
    value_style,
)
from apprc.interfaces.tui._styles import (
    ARCHIVE_STYLE,
    CHOICE_STYLE,
    DEFAULT_STYLE,
    EFFECTIVE_SOURCE_STYLE,
    GENERIC_VALUE_STYLE,
    LABEL_STYLE,
    MISSING_STYLE,
    NUMBER_STYLE,
    PATH_STYLE,
    SECRET_STYLE,
    TEXT_STYLE,
)
from apprc.interfaces.tui._value_modal_rendering import (
    field_type_text,
    possible_values_text,
    shell_status_text,
    source_label,
    source_label_text,
    source_origin_text,
    source_value_text,
)
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNER,
    APPRC_EXAMPLE_APP_OWNERS,
)
from tests.support_tui import text_has_span


def _text_cell(row: FieldTableRow, index: int) -> Text:
    """Return one table cell after proving it is rich text.

    :param row: Rendered table row to inspect.
    :param index: Cell index within the row.
    :return: Rich text cell.
    """
    cell = row.cells[index]
    assert isinstance(cell, Text)
    return cell


def test_build_field_table_rows_hides_keys_and_styles_declared_types() -> None:
    rows = build_field_table_rows(
        owners=APPRC_EXAMPLE_APP_OWNERS,
        user_dotenv_values={
            "APPRC_EXAMPLE_APP_ACCESS_TOKEN": "secret",
        },
        storage_values={
            "APPRC_EXAMPLE_APP_RETRY_COUNT": "9",
        },
        defaults_values=None,
        include_user_dotenv=True,
        include_storage=True,
        hidden_env_keys=frozenset({"APPRC_EXAMPLE_APP_STORAGE"}),
        shell_env={"APPRC_EXAMPLE_APP_MODE": "MANUAL"},
    )
    rows_by_key = {row.env_key: row for row in rows if row.env_key is not None}

    assert FIELD_TABLE_COLUMNS == (
        "#",
        "Section",
        "Key",
        "Effective",
        "Shell",
        "User",
        "Storage",
        "Default",
        "Explanation",
    )
    assert "APPRC_EXAMPLE_APP_STORAGE" not in rows_by_key
    assert (
        str(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"].cells[3])
        == "<secret>"
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"], 5).style
        == SECRET_STYLE
    )
    assert _text_cell(rows_by_key["APPRC_EXAMPLE_APP_MODE"], 4).plain == "shell"
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_MODE"], 7).style
        == CHOICE_STYLE
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"], 6).style
        == NUMBER_STYLE
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_CACHE_DIR"], 7).style
        == PATH_STYLE
    )


def test_config_textual_rendering_labels_match_field_metadata() -> None:
    mode = APPRC_EXAMPLE_APP_OWNER.field("mode")
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")
    cache_dir = APPRC_EXAMPLE_APP_OWNER.field("cache_dir")

    assert value_style(mode) == CHOICE_STYLE
    assert value_style(cache_dir) == PATH_STYLE
    assert field_type_style(mode) == TEXT_STYLE
    assert field_type_style(cache_dir) == PATH_STYLE
    assert possible_values_style(mode) == CHOICE_STYLE
    assert possible_values_style(cache_dir) == GENERIC_VALUE_STYLE
    assert field_type_label(cache_dir) == "Path"
    assert possible_values_label(mode) == "AUTO, MANUAL"
    assert (
        possible_values_label(enabled) == "true, false, yes, no, on, off, 1, 0"
    )
    assert possible_values_label(cache_dir) == "filesystem path"


def test_value_modal_rendering_formats_sources_and_metadata() -> None:
    mode = APPRC_EXAMPLE_APP_OWNER.field("mode")
    access_token = APPRC_EXAMPLE_APP_OWNER.field("access_token")
    effective = EditableConfigValueSource(
        key="effective",
        raw_value="super-secret",
        origin_key="storage",
    )
    shell = EditableConfigValueSource(key="shell", raw_value=None)
    shell_set = EditableConfigValueSource(key="shell", raw_value="MANUAL")
    storage = EditableConfigValueSource(
        key="storage",
        raw_value="super-secret",
    )
    empty_storage = EditableConfigValueSource(key="storage", raw_value="")
    shared = EditableConfigValueSource(key="defaults", raw_value=None)

    assert source_label(effective) == "Effective"
    assert source_label_text(effective).style == EFFECTIVE_SOURCE_STYLE
    assert source_origin_text(effective).plain == "from Storage"
    assert source_value_text(access_token, effective).plain == "<secret>"
    assert (
        source_value_text(access_token, effective).style
        == EFFECTIVE_SOURCE_STYLE
    )
    assert source_value_text(access_token, storage).plain == "<secret>"
    assert source_value_text(access_token, storage).style == SECRET_STYLE
    assert source_value_text(mode, shell).plain == "unset"
    assert source_value_text(mode, shell).style == LABEL_STYLE
    assert source_value_text(mode, shared).plain == "missing"
    assert source_value_text(mode, empty_storage).plain == "<empty>"
    assert shell_status_text(shell).plain == "unset"
    assert shell_status_text(shell_set).plain == "set"
    assert shell_status_text(shell_set).style == DEFAULT_STYLE
    assert field_type_text(mode).style == TEXT_STYLE
    assert possible_values_text(access_token).style == GENERIC_VALUE_STYLE


def test_storage_titles_match_editor_text(tmp_path: Path) -> None:
    root = tmp_path / "demo-storage"
    storage_env_path = root / ".env.apprc_example_app"
    archive = tmp_path / "beta.apprc.tar.xz"
    source_root = tmp_path / "beta"
    live = StorageRecord(name="alpha", root=root)
    archived = ArchivedStorageRecord(
        name="beta",
        archive=archive,
        source_root=source_root,
    )

    live_title = live_storage_title(live, storage_env_path)
    missing_title = missing_storage_title(live)
    archived_title = archived_storage_title(archived)

    assert live_title.plain == f"alpha: {root}\n{storage_env_path}"
    assert missing_title.plain == (
        "alpha: Missing storage root\n"
        f"Root: {root}\n"
        "No storage env file is available."
    )
    assert archived_title.plain == (
        f"beta: Last Archived\nArchive: {archive}\nLast source: {source_root}"
    )
    assert text_has_span(live_title, str(root), PATH_STYLE)
    assert text_has_span(
        live_title,
        str(storage_env_path),
        PATH_STYLE,
    )
    assert text_has_span(missing_title, "Missing storage root", MISSING_STYLE)
    assert text_has_span(missing_title, str(root), PATH_STYLE)
    assert text_has_span(archived_title, "Last Archived", ARCHIVE_STYLE)
    assert text_has_span(archived_title, str(archive), PATH_STYLE)
    assert text_has_span(archived_title, str(source_root), PATH_STYLE)
