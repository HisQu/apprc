"""Config editor launch helpers for generated config commands."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
    ResolvedConfigState,
    _empty_selector_context,
)
from apprc.interfaces.cli.config_command.state import (
    ConfigCliState,
    initial_storage_from_state,
)
from apprc.user_files.storage_roots.registry import StorageRegistry

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp


@dataclass(slots=True)
class ConfigEditorLauncher:
    """Resolve editor startup state and launch the Textual editor.

    :param kit: Application config facade.
    :param editor_app_cls: Optional app-provided editor subclass.
    :param config_group_name: Generated config command group name.
    :param initial_storage_hook: Optional app state based initial selection.
    :param initial_storage_with_context_hook: Optional selector-aware initial
        selection.
    """

    kit: AppConfigKit
    editor_app_cls: type["ConfigEditorApp"] | None
    config_group_name: str
    initial_storage_hook: Callable[[Any], str | None] | None
    initial_storage_with_context_hook: (
        Callable[[Any, ConfigSelectorContext], str | None] | None
    )

    def launch(
        self,
        *,
        current_state: ResolvedConfigState | None,
        storage_registry: StorageRegistry | None,
        active_storage_root: Path | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> None:
        """Create and run the Textual config editor."""
        selected_storage = (
            self.initial_storage(
                current_state,
                storage_registry=storage_registry,
                selector_context=selector_context,
            )
            if current_state is not None
            else None
        )
        if self.editor_app_cls is not None:
            editor_app = self.editor_app_cls(
                kit=self.kit,
                storage_registry=storage_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
            )
        else:
            from apprc.interfaces.tui import ConfigEditorApp

            editor_app = ConfigEditorApp(
                kit=self.kit,
                storage_registry=storage_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
                config_group_name=self.config_group_name,
            )
        editor_app.run()

    def initial_storage(
        self,
        resolved_state: ResolvedConfigState,
        *,
        storage_registry: StorageRegistry | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> str | None:
        """Return the storage name the editor should select on startup."""
        context = selector_context or _empty_selector_context()
        state = resolved_state.state
        if (
            resolved_state.app_owned
            and self.initial_storage_with_context_hook is not None
        ):
            return self.initial_storage_with_context_hook(state, context)
        if resolved_state.app_owned and self.initial_storage_hook is not None:
            return self.initial_storage_hook(state)
        return initial_storage_from_state(
            self.kit,
            cast(ConfigCliState, state),
            registry=storage_registry,
            explicit_values=context.explicit_values,
            env_file_overrides_os_environ=(
                context.env_file_overrides_os_environ
            ),
        )
