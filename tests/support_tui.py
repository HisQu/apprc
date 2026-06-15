"""Shared assertions for Textual/Rich rendering tests."""

from __future__ import annotations

# == Standard Library ========================
from typing import TYPE_CHECKING

# == 3rd Party ===============================
from rich.text import Text
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import DataTable, Static

if TYPE_CHECKING:
    from apprc.config.tui.editor import ConfigEditorApp


async def open_field_editor(
    editor: "ConfigEditorApp",
    env_key: str,
    pilot: Pilot[None],
) -> None:
    """Open a field editor modal by environment key.

    :param editor: Running config editor app.
    :param env_key: Full environment key represented by a field-table row.
    :param pilot: Textual test pilot used to let the modal mount.
    """
    table = editor.query_one("#field-table", DataTable)
    table.cursor_coordinate = Coordinate(editor.row_env_keys.index(env_key), 0)
    editor._open_selected_field_editor()
    await pilot.pause()


def static_text(static: Static) -> Text:
    """Return Rich text content from a Static after narrowing its type.

    :param static: Textual widget expected to contain styled Rich text.
    :return: Styled Rich text content.
    """
    content = static.content
    assert isinstance(content, Text)
    return content


def region_bottom(widget: Widget) -> int:
    """Return the bottom terminal row occupied by a widget.

    :param widget: Textual widget with a screen region.
    :return: First row after the widget.
    """
    return widget.region.y + widget.region.height


def region_right(widget: Widget) -> int:
    """Return the right terminal column occupied by a widget.

    :param widget: Textual widget with a screen region.
    :return: First column after the widget.
    """
    return widget.region.x + widget.region.width


def text_has_span(text: Text, literal: str, style: str) -> bool:
    """Return whether a literal has the expected style span.

    :param text: Rich text to inspect.
    :param literal: Plain substring expected inside ``text``.
    :param style: Rich style name expected for the substring.
    :return: Whether any span covers the whole literal.
    """
    start = text.plain.index(literal)
    end = start + len(literal)
    return any(
        span.start <= start and end <= span.end and span.style == style
        for span in text.spans
    )
