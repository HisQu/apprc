"""Shared base for config editor storage workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp


class StorageWorkflowBase:
    """Store the editor whose UI primitives are used by workflows.

    :param editor: Mounted config editor app.
    """

    def __init__(self, editor: "ConfigEditorApp") -> None:
        """Store the editor whose UI primitives are used by workflows."""
        self.editor = editor
