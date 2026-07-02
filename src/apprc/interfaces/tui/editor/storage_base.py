"""Shared base for config editor storage workflows."""

from __future__ import annotations

from pathlib import Path
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

    async def register_storage_directory_flow(
        self,
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        """Register one storage root in subclasses that support it."""
        raise NotImplementedError

    async def remove_live_storage(
        self,
        name: str,
        *,
        delete_content: bool,
    ) -> bool:
        """Remove one live storage root in subclasses that support it."""
        raise NotImplementedError
