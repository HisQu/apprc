"""Textual config editor and setup interfaces."""

# ruff: noqa: F401

from apprc.interfaces.tui.editor import (
    ConfigEditorApp,
    ConfigEditorStorageWorkflows,
)
from apprc.interfaces.tui.setup import ConfigSetupApp

__all__ = [
    "ConfigEditorApp",
    "ConfigEditorStorageWorkflows",
    "ConfigSetupApp",
]
