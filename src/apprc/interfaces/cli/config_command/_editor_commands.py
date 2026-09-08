"""Textual editor generated config command handler."""

from __future__ import annotations

# == Standard Library ========================
import os

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.storage_roots.registry import StorageRegistry
from apprc.user_files.storage_roots.selector import (
    StorageSelectorIssue,
    select_storage_selector_input,
)


class EditorConfigCommands(ConfigCommandBase):
    """Textual editor command implementation."""

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        selector_context = self.cli_selector_context(ctx)
        current_state = self.resolved_config_state(ctx)
        try:
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
                optional_registry = None
                storage_registry_error = str(exc)

            selector_issue: StorageSelectorIssue | None = None
            try:
                active_storage_root = self.active_storage_root_for_editor(
                    current_state,
                    selector_context=selector_context,
                )
            except typer.BadParameter as exc:
                active_storage_root = (
                    self.best_effort_active_storage_root_from_env(
                        storage_registry=optional_registry,
                        selector_context=selector_context,
                    )
                )
                selector_issue = self._storage_selector_issue(
                    ctx,
                    registry=optional_registry,
                    message=str(exc),
                )
            self.launch_config_editor(
                current_state=current_state,
                storage_registry=optional_registry,
                storage_registry_error=storage_registry_error,
                active_storage_root=active_storage_root,
                storage_selector_issue=selector_issue,
                selector_context=selector_context,
            )
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc

    def _storage_selector_issue(
        self,
        ctx: typer.Context,
        *,
        registry: StorageRegistry | None,
        message: str,
    ) -> StorageSelectorIssue:
        """Retain the selector layer that prevented editor startup.

        :param ctx: Active generated config command context.
        :param registry: Readable registry, when one exists.
        :param message: Selector-resolution failure.
        :return: Structured issue for the Textual editor.
        """
        selector_context = self.cli_selector_context(ctx)
        selector_key = self.kit.spec.require_storage_selector_env_key()
        raw_storage = self.cli_context_param(ctx, "storage")
        selector = select_storage_selector_input(
            storage=raw_storage if isinstance(raw_storage, str) else None,
            original_env=os.environ,
            explicit_values=selector_context.explicit_values,
            env_file_overrides_os_environ=(
                selector_context.env_file_overrides_os_environ
            ),
            storage_selector_env_key=selector_key,
            selected_storage=(
                registry.selected_storage if registry is not None else None
            ),
        )
        return StorageSelectorIssue(
            selector=selector,
            message=message,
            configured_storage=(
                registry.selected_storage if registry is not None else None
            ),
        )
