from __future__ import annotations

from rich.text import Text

from apprc.config.tui_rendering import (
    FIELD_TABLE_COLUMNS,
    FieldTableRow,
    build_field_table_rows,
    field_type_label,
    possible_values_label,
    value_style,
)
from tests.support_config import DEMO_OWNER, DEMO_OWNERS


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
        owners=DEMO_OWNERS,
        local_values={
            "DEMO_API_TOKEN": "secret",
            "DEMO_RETRY_COUNT": "9",
        },
        hidden_env_keys=frozenset({"DEMO_D_STORAGE"}),
        shell_env={"DEMO_STRATEGY": "WEIGHT"},
    )
    rows_by_key = {row.env_key: row for row in rows if row.env_key is not None}

    assert FIELD_TABLE_COLUMNS == (
        "#",
        "Section",
        "Key",
        "Status",
        "Local",
        "Default",
        "Explanation",
    )
    assert "DEMO_D_STORAGE" not in rows_by_key
    assert str(rows_by_key["DEMO_API_TOKEN"].cells[4]) == "<secret>"
    assert _text_cell(rows_by_key["DEMO_API_TOKEN"], 4).style == "dim italic"
    assert _text_cell(rows_by_key["DEMO_STRATEGY"], 3).plain == "shell"
    assert _text_cell(rows_by_key["DEMO_STRATEGY"], 5).style == "bold cyan"
    assert _text_cell(rows_by_key["DEMO_RETRY_COUNT"], 4).style == "yellow"
    assert _text_cell(rows_by_key["DEMO_CACHE_DIR"], 5).style == "green"


def test_tui_rendering_labels_match_field_metadata() -> None:
    strategy = DEMO_OWNER.field("strategy")
    enabled = DEMO_OWNER.field("enabled")
    cache_dir = DEMO_OWNER.field("cache_dir")

    assert value_style(strategy) == "bold cyan"
    assert field_type_label(cache_dir) == "Path"
    assert possible_values_label(strategy) == "VECTOR, WEIGHT"
    assert (
        possible_values_label(enabled) == "true, false, yes, no, on, off, 1, 0"
    )
    assert possible_values_label(cache_dir) == "filesystem path"
