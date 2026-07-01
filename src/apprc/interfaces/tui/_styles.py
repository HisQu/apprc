"""Shared semantic styles for AppRC Textual screens."""

from __future__ import annotations

# == Internal ================================
from apprc.interfaces._terminal_styles import (
    ARCHIVE_STYLE,
    BOOL_STYLE,
    CHOICE_STYLE,
    DEFAULT_STYLE,
    EFFECTIVE_SOURCE_STYLE,
    ENV_KEY_STYLE,
    ERROR_STYLE,
    GENERIC_VALUE_STYLE,
    LABEL_STYLE,
    MISSING_STYLE,
    NUMBER_STYLE,
    PATH_STYLE,
    REQUIRED_STYLE,
    SECRET_STYLE,
    STORAGE_NAME_STYLE,
    TEXT_STYLE,
    env_key_text,
    label_value_text,
    lines_text,
    path_markup,
    path_text,
    storage_name_text,
    style_literals,
)

__all__ = [
    "ARCHIVE_STYLE",
    "BOOL_STYLE",
    "CHOICE_STYLE",
    "DEFAULT_STYLE",
    "EFFECTIVE_SOURCE_STYLE",
    "ENV_KEY_STYLE",
    "ERROR_STYLE",
    "GENERIC_VALUE_STYLE",
    "LABEL_STYLE",
    "MISSING_STYLE",
    "MODAL_DIALOG_CLASS",
    "MODAL_DIALOG_CSS",
    "NUMBER_STYLE",
    "PATH_INPUT_CLASS",
    "PATH_INPUT_CSS",
    "PATH_STYLE",
    "REQUIRED_STYLE",
    "SECRET_STYLE",
    "STORAGE_NAME_STYLE",
    "TEXT_STYLE",
    "env_key_text",
    "label_value_text",
    "lines_text",
    "path_markup",
    "path_text",
    "storage_name_text",
    "style_literals",
]

PATH_INPUT_CLASS = "path-input"
MODAL_DIALOG_CLASS = "modal-dialog"

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
