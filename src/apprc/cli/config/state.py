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
from apprc.runtime_config.app_spec import StorageMode
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.loading import (
    load_optional_runtime_storage_registry,
)
from apprc.runtime_config.storage.registry import StorageRegistry
from apprc.runtime_config.storage.selector import (
    resolve_active_storage_selection,
    select_storage_selector,
)
from apprc.runtime_config.storage.selector_fallbacks import (
    read_storage_selector_fallback_values,
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
        "doctor",
        "edit",
        "init",
        "list",
        "setup",
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
    if kit.spec.storage_mode == StorageMode.DISABLED:
        return None
    if (
        state.env_bootstrap is not None
        and state.env_bootstrap.storage_root is not None
    ):
        return state.env_bootstrap.storage_root
    kit.spec.ensure_config_home()
    registry = load_optional_runtime_storage_registry(kit.spec)
    return active_storage_root_from_env(kit, registry=registry)


def active_storage_root_from_env(
    kit: AppConfigKit,
    *,
    registry: StorageRegistry | None,
) -> Path | None:
    """Return the active storage root selected by the current environment.

    :param kit: Application config facade.
    :param registry: Parsed storage table, or ``None`` for single-storage
        path mode.
    :return: Resolved storage root, or ``None`` when no env selector is set.
    :raises StorageSelectorError: If the env selector cannot be resolved.
    """
    if kit.spec.storage_mode == StorageMode.DISABLED:
        return None
    storage_env_key = kit.spec.require_storage_env_key()
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    selection = resolve_active_storage_selection(
        registry=registry,
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        global_values=fallback_values.global_values,
        shared_values=fallback_values.shared_values,
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
    if kit.spec.storage_mode == StorageMode.DISABLED:
        return None
    storage_env_key = kit.spec.require_storage_env_key()
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    storage_selector = select_storage_selector(
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values={},
        global_values=fallback_values.global_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=False,
    )
    if storage_selector is None:
        return None
    _, raw_value = storage_selector
    if registry is not None and raw_value in registry.storages:
        return raw_value
    return None
