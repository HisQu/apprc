"""Textual setup guidance for AppRC-managed files."""

from __future__ import annotations

from typing import TYPE_CHECKING

# == 3rd Party ===============================
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

# == Internal ================================
from apprc.user_files.setup.text import setup_overview_text

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit


class ConfigSetupApp(App[None]):
    """Small setup guidance screen for AppRC-managed files."""

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, *, kit: AppConfigKit) -> None:
        """Store the kit whose setup route should be described."""
        super().__init__()
        self.kit = kit

    def compose(self) -> ComposeResult:
        """Compose a read-only setup guidance screen."""
        yield Header()
        yield Static(setup_overview_text(self.kit))
        yield Footer()
