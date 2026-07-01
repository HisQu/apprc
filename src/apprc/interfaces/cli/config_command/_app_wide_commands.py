"""App-wide generated config command handlers."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.user_files.app_home.locations import ConfigHomeError


class AppWideConfigCommands(ConfigCommandBase):
    """App-wide config command implementations."""

    def app_init(self) -> None:
        """Create the app-wide dotenv file explicitly."""
        if not self.kit.spec.app_wide_allowed():
            raise typer.BadParameter(
                f"{self.kit.spec.display_name} does not enable app-wide config.",
                param_hint="app",
            )
        try:
            path = self.kit.spec.ensure_app_wide_env()
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        typer.echo(f"app_wide_env: {path}")
