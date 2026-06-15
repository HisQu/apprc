"""State helpers for generated AppRC ``config`` commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path
from typing import Protocol

# == Internal ================================
from apprc.cli.options import (
    COMMON_ROOT_FLAG_OPTIONS,
    COMMON_ROOT_VALUE_OPTIONS,
)
from apprc.cli.typer_utils import strip_leading_options
from apprc.config.environment import EnvBootstrapResult
from apprc.config.kit import AppConfigKit
from apprc.config.storage.registry import StorageRegistry
from apprc.config.storage.selector import resolve_active_storage_selection


class ConfigCliState(Protocol):
    """Root CLI state fields understood by the generic config app."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None


def config_request_skips_bootstrap(args: list[str]) -> bool:
    """Return whether one config invocation avoids runtime bootstrap.

    :param args: Tokens after the top-level ``config`` command.
    :return: Whether the config command can run without root config state.
    """
    action_args = strip_leading_options(
        args,
        flag_options=COMMON_ROOT_FLAG_OPTIONS,
        value_options=COMMON_ROOT_VALUE_OPTIONS,
    )
    if not action_args:
        return True
    if action_args == ["--json"]:
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
    env_storage = os.environ.get(kit.spec.storage_env_key, "").strip()
    if env_storage:
        active_registry_path = kit.optional_apprc_toml_path()
        registry = (
            kit.load_existing_registry()
            if active_registry_path is not None
            else None
        )
        selection = resolve_active_storage_selection(
            registry=registry,
            storage=None,
            storage_env_key=kit.spec.storage_env_key,
            original_env=os.environ,
        )
        return selection.root if selection is not None else None
    return None


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
