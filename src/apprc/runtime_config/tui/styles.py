"""Shared semantic styles for AppRC Textual screens."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping
from pathlib import Path

# == 3rd Party ===============================
from rich.markup import escape
from rich.text import Text

PATH_INPUT_CLASS = "path-input"
MODAL_DIALOG_CLASS = "modal-dialog"

PATH_STYLE = "cyan"
STORAGE_NAME_STYLE = "bold"
ENV_KEY_STYLE = "bold blue"
LABEL_STYLE = "dim"
DEFAULT_STYLE = "green"
MISSING_STYLE = "yellow"
ARCHIVE_STYLE = "magenta"
ERROR_STYLE = "red"
EFFECTIVE_SOURCE_STYLE = f"bold {ERROR_STYLE}"
GENERIC_VALUE_STYLE = "dim italic"
SECRET_STYLE = "dim italic"
REQUIRED_STYLE = "bold white on red"
BOOL_STYLE = "bold magenta"
NUMBER_STYLE = "yellow"
CHOICE_STYLE = "bold cyan"
TEXT_STYLE = "white"

MODAL_DIALOG_CSS = f"""
.{MODAL_DIALOG_CLASS} {{
    max-width: 95%;
    border: thick $primary;
    background: $surface;
    padding: 1 2;
}}
"""

PATH_INPUT_CSS = f"""
Input.{PATH_INPUT_CLASS} {{
    color: {PATH_STYLE};
}}
"""


def path_text(path: str | Path) -> Text:
    """Return a filesystem path with the canonical TUI path color.

    :param path: Filesystem path or already-rendered path text.
    :return: Styled Rich text.
    """
    return Text(str(path), style=PATH_STYLE)


def path_markup(path: str | Path) -> str:
    """Return escaped Rich markup for a known filesystem path.

    Textual notifications accept strings with markup enabled instead of Rich
    renderables, so known path values need explicit escaping before styling.

    :param path: Filesystem path or already-rendered path text.
    :return: Markup string with the canonical path style.
    """
    return f"[{PATH_STYLE}]{escape(str(path))}[/]"


def storage_name_text(name: str) -> Text:
    """Return a storage selector with the canonical name style.

    :param name: Registry selector shown to the user.
    :return: Styled Rich text.
    """
    return Text(name, style=STORAGE_NAME_STYLE)


def env_key_text(env_key: str) -> Text:
    """Return an environment variable name with the canonical key style.

    :param env_key: Environment variable name.
    :return: Styled Rich text.
    """
    return Text(env_key, style=ENV_KEY_STYLE)


def label_value_text(label: str, value: str | Text) -> Text:
    """Return a dim label followed by a plain or styled value.

    :param label: Reader-facing label without the trailing colon.
    :param value: Plain text or Rich text value.
    :return: Styled label/value line.
    """
    rendered = Text.assemble((label, LABEL_STYLE), ": ")
    if isinstance(value, Text):
        rendered.append_text(value)
    else:
        rendered.append(str(value))
    return rendered


def lines_text(*lines: str | Text) -> Text:
    """Join plain or Rich text lines while preserving span styles.

    :param lines: Lines to join with newline separators.
    :return: One Rich text block.
    """
    rendered = Text()
    for index, line in enumerate(lines):
        if index:
            rendered.append("\n")
        if isinstance(line, Text):
            rendered.append_text(line)
        else:
            rendered.append(str(line))
    return rendered


def style_literals(text: str, styles: Mapping[str, str]) -> Text:
    """Style exact literal substrings inside plain text.

    This helper intentionally avoids path guessing. Callers provide the exact
    env keys, storage roots, or TOML paths they know came from structured
    state, and the helper colors only those literal occurrences.

    :param text: Plain source text.
    :param styles: Literal text mapped to Rich style names.
    :return: Rich text with matching literal spans styled.
    """
    rendered = Text(text)
    for literal, style in sorted(
        styles.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if literal == "":
            continue
        start = 0
        while True:
            index = text.find(literal, start)
            if index == -1:
                break
            end = index + len(literal)
            rendered.stylize(style, index, end)
            start = end
    return rendered
