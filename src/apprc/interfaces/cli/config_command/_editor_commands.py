"""Textual editor generated config command handler."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.user_files.app_home.locations import AppRCDirectoryError


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
            storage_registry_error: str | None = None
            try:
                optional_registry = (
                    self.load_storage_registry_or_empty(
                        selector_context=selector_context,
                    )
                    if self.kit.spec.uses_storage()
                    else None
                )
            except typer.BadParameter as exc:
                if active_storage_root is None and self.kit.spec.uses_storage():
                    raise
                optional_registry = None
                storage_registry_error = str(exc)
            self.launch_config_editor(
                current_state=current_state,
                storage_registry=optional_registry,
                storage_registry_error=storage_registry_error,
                active_storage_root=active_storage_root,
                selector_context=selector_context,
            )
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
