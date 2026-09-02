"""Composition layer for generated AppRC ``config`` command handlers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._app_commands import (
    AppConfigCommands,
)
from apprc.interfaces.cli.config_command._editor_commands import (
    EditorConfigCommands,
)
from apprc.interfaces.cli.config_command._runtime_commands import (
    RuntimeConfigCommands,
)
from apprc.interfaces.cli.config_command._storage_commands import (
    StorageConfigCommands,
)
from apprc.interfaces.cli.setup_command import run_config_setup
from apprc.interfaces.cli._typer_utils import exit_missing_action


class ConfigCommandHandlers(
    RuntimeConfigCommands,
    StorageConfigCommands,
    AppConfigCommands,
    EditorConfigCommands,
):
    """Command implementations for the generated ``config`` Typer group."""

    def callback(self, ctx: typer.Context) -> None:
        """Show config help when no subcommand was selected."""
        if ctx.invoked_subcommand is not None:
            return
        exit_missing_action(ctx)

    def setup(
        self,
        *,
        assume_yes: bool,
        storage_root: str | Path | None,
    ) -> None:
        """Configure the files required by this AppRC declaration."""
        run_config_setup(
            self.kit,
            assume_yes=assume_yes,
            storage_root=storage_root,
            config_group_name=self.config_group_name,
        )
