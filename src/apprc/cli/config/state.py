"""State helpers for generated AppRC ``config`` commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Protocol

# == Internal ================================
from apprc.cli.options import (
    COMMON_ROOT_FLAG_OPTIONS,
    COMMON_ROOT_VALUE_OPTIONS,
)
from apprc.cli.typer_utils import args_after_command, strip_leading_options
from apprc.runtime_config.bootstrap.result import EnvBootstrapResult
from apprc.runtime_config.bootstrap.dotenv_layers import (
    read_storage_selector_fallback_values,
)
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.loading import (
    load_runtime_storage_registry_for_selector,
)
from apprc.runtime_config.storage.registry import StorageRegistry
from apprc.runtime_config.storage.selector import (
    resolve_storage_selector_value,
    select_storage_selector,
)


class ConfigCliState(Protocol):
    """Root CLI state fields understood by the generic config app."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None


def config_request_skips_runtime_bootstrap(
    command_name: str = "config",
    *,
    tokens: Sequence[str] | None = None,
    root_value_options: Collection[str] = COMMON_ROOT_VALUE_OPTIONS,
) -> bool:
    """Return whether one config invocation avoids runtime bootstrap.

    :param command_name: Top-level config command name to inspect.
    :param tokens: Optional command tokens without the program name.
    :param root_value_options: Root options that consume a following value
        before the config command.
    :return: Whether the config command can run without root config state.
    """
    args = args_after_command(
        command_name,
        tokens=tokens,
        root_value_options=root_value_options,
    )
    if args is None:
        return False
    action_args = strip_leading_options(
        args,
        flag_options=COMMON_ROOT_FLAG_OPTIONS,
        value_options=COMMON_ROOT_VALUE_OPTIONS,
    )
    if not action_args:
        return True
    return action_args[0] in {
        "app",
        "doctor",
        "edit",
        "paths",
        "set",
        "setup",
        "storage",
    }


def active_storage_root_from_state(
    kit: AppConfigKit,
    state: ConfigCliState,
) -> Path | None:
    """Return the active storage root from generic CLI state.

    :param kit: Application config facade.
    :param state: Root CLI state object.
    :return: Resolved storage root, or ``None`` when no selector is active.
    """
    if not kit.spec.storage_required():
        return None
    if (
        state.env_bootstrap is not None
        and state.env_bootstrap.storage_root is not None
    ):
        return state.env_bootstrap.storage_root
    if state.storage is not None:
        storage_env_key = kit.spec.require_storage_env_key()
        selected_registry = load_runtime_storage_registry_for_selector(
            kit.spec,
            raw_selector=state.storage,
        )
        selection = resolve_storage_selector_value(
            registry=selected_registry,
            raw_value=state.storage,
            storage_env_key=storage_env_key,
            source="--storage",
        )
        return selection.root if selection is not None else None
    return active_storage_root_from_env(kit)


def active_storage_root_from_env(
    kit: AppConfigKit,
    *,
    registry: StorageRegistry | None = None,
) -> Path | None:
    """Return the active storage root selected by the current environment.

    :param kit: Application config facade.
    :param registry: Parsed storage table, or ``None`` for single-storage
        path mode.
    :return: Resolved storage root, or ``None`` when no env selector is set.
    :raises StorageSelectorError: If the env selector cannot be resolved.
    """
    if not kit.spec.storage_required():
        return None
    storage_env_key = kit.spec.require_storage_env_key()
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    storage_selector = select_storage_selector(
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values={},
        app_wide_values=fallback_values.app_wide_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=False,
    )
    if storage_selector is None:
        return None
    source, raw_value = storage_selector
    selected_registry = registry
    if selected_registry is None:
        selected_registry = load_runtime_storage_registry_for_selector(
            kit.spec,
            raw_selector=raw_value,
        )
    selection = resolve_storage_selector_value(
        registry=selected_registry,
        raw_value=raw_value,
        storage_env_key=storage_env_key,
        source=source,
    )
    return selection.root if selection is not None else None


def initial_storage_from_state(
    kit: AppConfigKit,
    state: ConfigCliState,
    registry: StorageRegistry | None = None,
) -> str | None:
    """Return the storage that should be selected first in editors.

    :param kit: Application config facade.
    :param state: Root CLI state object.
    :param registry: Optional already-loaded storage table.
    :return: Storage selector to preselect, or ``None``.
    """
    if state.env_bootstrap is not None:
        return state.env_bootstrap.storage_name
    if state.storage is not None:
        return state.storage
    if not kit.spec.storage_required():
        return None
    storage_env_key = kit.spec.require_storage_env_key()
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    storage_selector = select_storage_selector(
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values={},
        app_wide_values=fallback_values.app_wide_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=False,
    )
    if storage_selector is None:
        return None
    _, raw_value = storage_selector
    if registry is not None and raw_value in registry.storages:
        return raw_value
    return None
