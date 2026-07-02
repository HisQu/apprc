"""Internal option bundle for generated config command groups."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apprc.interfaces.cli.config_command._selector_context import (
        ConfigSelectorContext,
    )
    from apprc.interfaces.tui import ConfigEditorApp


@dataclass(frozen=True, slots=True)
class ConfigGroupOptions:
    """Carry generated config command hooks through internal layers.

    :param state_type: Application CLI state type stored on ``ctx.obj``.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_storage_root: Optional storage-root resolver.
    :param active_storage_root_with_context: Optional storage-root resolver that
        can inspect explicit env-file selector context.
    :param initial_storage: Optional editor initial-selection resolver.
    :param initial_storage_with_context: Optional editor initial-selection
        resolver that can inspect explicit env-file selector context.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional command-group help.
    :param setup_message: Optional setup text for missing storage.
    :param runtime_error_param_hint: Parameter hint for runtime-payload
        validation errors.
    :param config_group_name: Config command group name used in generated
        guidance.
    """

    state_type: type[Any]
    runtime_payload: Callable[[Any], Mapping[str, Any]] | None = None
    active_storage_root: Callable[[Any], Path | None] | None = None
    active_storage_root_with_context: (
        Callable[[Any, "ConfigSelectorContext"], Path | None] | None
    ) = None
    initial_storage: Callable[[Any], str | None] | None = None
    initial_storage_with_context: (
        Callable[[Any, "ConfigSelectorContext"], str | None] | None
    ) = None
    editor_app_cls: type["ConfigEditorApp"] | None = None
    help: str | None = None
    setup_message: str | None = None
    runtime_error_param_hint: str = "CONFIG"
    config_group_name: str = "config"
