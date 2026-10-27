from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rich.text import Text

from apprc.interfaces.tui._field_state import EditableConfigValueSource
from apprc.interfaces.tui._rendering import (
    FieldTableRow,
    archived_workspace_title,
    build_field_table_rows,
    field_table_columns,
    field_type_label,
    field_type_style,
    live_workspace_title,
    missing_workspace_title,
    possible_values_label,
    possible_values_style,
    setting_cell,
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
    source_label_text,
    source_value_text,
)
from apprc.user_files.workspace_roots.model import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
)
from tests.support_config import (
    WORKSPACE_EXAMPLE_OWNER,
    example_resolution,
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
        include_user_dotenv=True,
        include_workspace=True,
        hidden_env_keys=frozenset({"APPRC_EXAMPLE_APP_WORKSPACE"}),
        resolved=example_resolution(
            user_dotenv_values={
                "APPRC_EXAMPLE_APP_ACCESS_TOKEN": "secret",
            },
            workspace_values={
                "APPRC_EXAMPLE_APP_RETRY_COUNT": "9",
            },
            defaults_values=None,
            shell_env={"APPRC_EXAMPLE_APP_MODE": "MANUAL"},
        ),
    )
    rows_by_key = {row.env_key: row for row in rows if row.env_key is not None}

    assert "APPRC_EXAMPLE_APP_WORKSPACE" not in rows_by_key
    assert (
        str(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"].cells[3])
        == "<secret>"
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_ACCESS_TOKEN"], 6).style
        == SECRET_STYLE
    )
    assert _text_cell(rows_by_key["APPRC_EXAMPLE_APP_MODE"], 4).plain == "shell"
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_MODE"], 7).style
        == CHOICE_STYLE
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_RETRY_COUNT"], 5).style
        == NUMBER_STYLE
    )
    assert (
        _text_cell(rows_by_key["APPRC_EXAMPLE_APP_CACHE_DIR"], 7).style
        == PATH_STYLE
    )
    assert _text_cell(rows_by_key["APPRC_EXAMPLE_APP_MODE"], 2).plain == (
        "Mode\nAPPRC_EXAMPLE_APP_MODE"
    )


def test_field_table_columns_only_show_declared_sources() -> None:
    base_columns = field_table_columns(
        include_user_dotenv=False,
        include_workspace=False,
    )
    user_columns = field_table_columns(
        include_user_dotenv=True,
        include_workspace=False,
    )
    workspace_columns = field_table_columns(
        include_user_dotenv=False,
        include_workspace=True,
    )
    both_columns = field_table_columns(
        include_user_dotenv=True,
        include_workspace=True,
    )
    assert user_columns == (
        base_columns[:-2] + (both_columns[-3],) + base_columns[-2:]
    )
    assert workspace_columns == (
        base_columns[:-2] + (both_columns[-4],) + base_columns[-2:]
    )
    assert both_columns == (
        workspace_columns[:-2] + (user_columns[-3],) + base_columns[-2:]
    )


def test_config_textual_rendering_labels_match_field_metadata() -> None:
    mode = WORKSPACE_EXAMPLE_OWNER.field("mode")
    enabled = WORKSPACE_EXAMPLE_OWNER.field("enabled")
    cache_dir = WORKSPACE_EXAMPLE_OWNER.field("cache_dir")

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


def test_setting_cell_marks_restart_required_fields() -> None:
    spec = WORKSPACE_EXAMPLE_OWNER.field("profile")
    restart_spec = replace(spec, restart_required=True)

    assert setting_cell(spec, "APPRC_EXAMPLE_APP_PROFILE").plain == (
        "Profile\nAPPRC_EXAMPLE_APP_PROFILE"
    )
    assert (
        setting_cell(
            restart_spec,
            "APPRC_EXAMPLE_APP_PROFILE",
        ).plain
        == "Profile (restart required)\nAPPRC_EXAMPLE_APP_PROFILE"
    )


def test_value_modal_rendering_formats_sources_and_metadata() -> None:
    mode = WORKSPACE_EXAMPLE_OWNER.field("mode")
    access_token = WORKSPACE_EXAMPLE_OWNER.field("access_token")
    effective = EditableConfigValueSource(
        key="effective",
        raw_value="super-secret",
        origin_key="workspace",
    )
    shell = EditableConfigValueSource(key="shell", raw_value=None)
    shell_set = EditableConfigValueSource(key="shell", raw_value="MANUAL")
    workspace = EditableConfigValueSource(
        key="workspace",
        raw_value="super-secret",
    )
    empty_workspace = EditableConfigValueSource(key="workspace", raw_value="")
    shared = EditableConfigValueSource(key="defaults", raw_value=None)

    assert source_label_text(effective).style == EFFECTIVE_SOURCE_STYLE
    assert source_value_text(access_token, effective).plain == "<secret>"
    assert (
        source_value_text(access_token, effective).style
        == EFFECTIVE_SOURCE_STYLE
    )
    assert source_value_text(access_token, workspace).plain == "<secret>"
    assert source_value_text(access_token, workspace).style == SECRET_STYLE
    assert source_value_text(mode, shell).plain == "unset"
    assert source_value_text(mode, shell).style == LABEL_STYLE
    assert source_value_text(mode, shared).plain == "missing"
    assert source_value_text(mode, empty_workspace).plain == "<empty>"
    assert shell_status_text(shell).plain == "unset"
    assert shell_status_text(shell_set).plain == "set"
    assert shell_status_text(shell_set).style == DEFAULT_STYLE
    assert field_type_text(mode).style == TEXT_STYLE
    assert possible_values_text(access_token).style == GENERIC_VALUE_STYLE


def test_workspace_titles_style_paths_and_record_states(tmp_path: Path) -> None:
    root = tmp_path / "demo-workspace"
    workspace_env_path = root / ".env.apprc_example_app"
    archive = tmp_path / "beta.apprc.tar.xz"
    source_root = tmp_path / "beta"
    live = WorkspaceRecord(name="alpha", root=root)
    archived = ArchivedWorkspaceRecord(
        name="beta",
        archive=archive,
        source_root=source_root,
    )

    live_title = live_workspace_title(live, workspace_env_path)
    missing_title = missing_workspace_title(live)
    archived_title = archived_workspace_title(archived)

    assert text_has_span(live_title, str(root), PATH_STYLE)
    assert text_has_span(
        live_title,
        str(workspace_env_path),
        PATH_STYLE,
    )
    assert any(span.style == MISSING_STYLE for span in missing_title.spans)
    assert text_has_span(missing_title, str(root), PATH_STYLE)
    assert any(span.style == ARCHIVE_STYLE for span in archived_title.spans)
    assert text_has_span(archived_title, str(archive), PATH_STYLE)
    assert text_has_span(archived_title, str(source_root), PATH_STYLE)
