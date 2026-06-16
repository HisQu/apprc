"""Editor launch helpers for generated config commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from apprc.cli.config.state import ConfigCliState, initial_storage_from_state
from apprc.config.kit import AppConfigKit
from apprc.config.storage.registry import StorageRegistry

if TYPE_CHECKING:
    from apprc.config.tui import ConfigEditorApp


def launch_config_editor(
    kit: AppConfigKit,
    *,
    current_state: Any | None,
    editor_app_cls: type[ConfigEditorApp] | None,
    initial_storage_hook: Callable[[Any], str | None] | None,
    registry: StorageRegistry | None,
    active_storage_root: Path | None,
) -> None:
    """Create and run the Textual config editor.

    :param kit: Application config facade.
    :param current_state: Optional application root CLI state.
    :param editor_app_cls: Optional Textual subclass.
    :param initial_storage_hook: Optional app-provided initial selector.
    :param registry: Optional multi-storage registry.
    :param active_storage_root: Best-effort active storage path.
    """
    selected_storage = (
        initial_storage_for_editor(
            kit,
            current_state,
            initial_storage_hook=initial_storage_hook,
            registry=registry,
        )
        if current_state is not None
        else None
    )
    if editor_app_cls is not None:
        editor_app = editor_app_cls(
            kit=kit,
            registry=registry,
            initial_storage=selected_storage,
            active_storage_root=active_storage_root,
        )
    else:
        from apprc.config.tui import ConfigEditorApp

        editor_app = ConfigEditorApp(
            kit=kit,
            registry=registry,
            initial_storage=selected_storage,
            active_storage_root=active_storage_root,
        )
    editor_app.run()


def initial_storage_for_editor(
    kit: AppConfigKit,
    state: Any,
    *,
    initial_storage_hook: Callable[[Any], str | None] | None,
    registry: StorageRegistry | None,
) -> str | None:
    """Return the storage name the editor should select on startup.

    :param kit: Application config facade.
    :param state: Application root CLI state.
    :param initial_storage_hook: Optional app-provided resolver.
    :param registry: Optional already-loaded registry.
    :return: Storage selector to preselect, or ``None``.
    """
    if initial_storage_hook is not None:
        return initial_storage_hook(state)
    return initial_storage_from_state(
        kit,
        cast(ConfigCliState, state),
        registry=registry,
    )
