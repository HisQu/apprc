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
from apprc.config.environment import EnvBootstrapResult
from apprc.config.kit import AppConfigKit
from apprc.config.storage.registry import StorageRegistry
from apprc.config.storage.selector import resolve_active_storage_selection


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
    if (
        state.env_bootstrap is not None
        and state.env_bootstrap.storage_root is not None
    ):
        return state.env_bootstrap.storage_root
    if not os.environ.get(kit.spec.storage_env_key, "").strip():
        return None
    registry = kit.load_configured_registry()
    return active_storage_root_from_env(kit, registry=registry)


def active_storage_root_from_env(
    kit: AppConfigKit,
    *,
    registry: StorageRegistry | None,
) -> Path | None:
    """Return the active storage root selected by the current environment.

    :param kit: Application config facade.
    :param registry: Parsed AppRC TOML storage registry, or ``None`` for
        single-storage path mode.
    :return: Resolved storage root, or ``None`` when no env selector is set.
    :raises StorageSelectorError: If the env selector cannot be resolved.
    """
    env_storage = os.environ.get(kit.spec.storage_env_key, "").strip()
    if not env_storage:
        return None
    selection = resolve_active_storage_selection(
        registry=registry,
        storage=None,
        storage_env_key=kit.spec.storage_env_key,
        original_env=os.environ,
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
    :param registry: Optional already-loaded registry.
    :return: Storage selector to preselect, or ``None``.
    """
    if state.env_bootstrap is not None:
        return state.env_bootstrap.storage_name
    if state.storage is not None:
        return state.storage
    env_storage = os.environ.get(kit.spec.storage_env_key, "").strip()
    if registry is not None and env_storage in registry.storages:
        return env_storage
    return None
