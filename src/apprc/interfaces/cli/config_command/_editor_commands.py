"""Textual editor generated config command handler."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.user_files.app_home.locations import ConfigHomeError


class EditorConfigCommands(ConfigCommandBase):
    """Textual editor command implementation."""

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        selector_context = self.cli_selector_context(ctx)
        current_state = self.resolved_config_state(ctx)
        try:
            active_storage_root = self.active_storage_root_for_editor(
                current_state,
                selector_context=selector_context,
            )
            try:
                optional_registry = self.load_optional_storage_registry(
                    selector_context=selector_context,
                )
            except typer.BadParameter:
                if (
                    active_storage_root is None
                    and self.kit.spec.named_storage_default()
                ):
                    raise
                optional_registry = None
            self.launch_config_editor(
                current_state=current_state,
                storage_registry=optional_registry,
                active_storage_root=active_storage_root,
                selector_context=selector_context,
            )
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
