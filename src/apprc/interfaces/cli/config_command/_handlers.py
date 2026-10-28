"""Composition layer for generated AppRC ``config`` command handlers."""

from __future__ import annotations

# == Standard Library ========================
# == 3rd Party ===============================
import typer

from apprc.interfaces.cli._typer_utils import exit_missing_action

# == Internal ================================
from apprc.interfaces.cli.config_command._editor_commands import (
    EditorConfigCommands,
)
from apprc.interfaces.cli.config_command._runtime_commands import (
    RuntimeConfigCommands,
)
from apprc.interfaces.cli.setup_command import run_config_setup


class ConfigCommandHandlers(
    RuntimeConfigCommands,
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
        ctx: typer.Context,
        *,
        assume_yes: bool,
        adopt: bool,
    ) -> None:
        """Initialize declared config files without creating a workspace."""
        run_config_setup(
            self.apprc,
            assume_yes=assume_yes,
            adopt=adopt,
            manager=self.manager(ctx),
            config_group_name=self.config_group_name,
            show_next_step=True,
        )
