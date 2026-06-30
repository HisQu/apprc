"""State helpers for generated AppRC ``config`` commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

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
from apprc.runtime_config.bootstrap.process_env import selection_env
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
    """Host CLI state fields understood by the generic config app."""

    env_bootstrap: EnvBootstrapResult | None


class StorageConfigCliState(ConfigCliState, Protocol):
    """Host CLI state fields used by storage-capable config commands."""

    storage: str | None


@dataclass(slots=True)
class DefaultConfigCliState:
    """Default host state understood by generated AppRC config commands.

    :param env_bootstrap: Runtime bootstrap result, when bootstrap ran.
    :param storage: Optional host-level ``--storage`` selector.
    """

    env_bootstrap: EnvBootstrapResult | None = None
    storage: str | None = None


DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS = frozenset(
    {
        "app",
        "doctor",
        "edit",
        "paths",
        "set",
        "setup",
        "storage",
    }
)


@dataclass(frozen=True, slots=True)
class ConfigBootstrapPolicy:
    """Runtime-bootstrap skip policy for a generated config command group.

    :param config_group_name: Top-level config command group to inspect.
    :param bootstrapless_actions: Config actions that can run without full
        runtime state.
    :param root_flag_options: Host-level options that consume no values.
    :param root_value_options: Host-level options that consume one following
        value before the config command.
    :param skip_invalid_options: Whether unknown leading options under the
        config group should avoid runtime bootstrap so Typer can report the
        parse error without app config failures.
    """

    config_group_name: str = "config"
    bootstrapless_actions: Collection[str] = (
        DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS
    )
    root_flag_options: Collection[str] = COMMON_ROOT_FLAG_OPTIONS
    root_value_options: Collection[str] = COMMON_ROOT_VALUE_OPTIONS
    skip_invalid_options: bool = True

    def request_skips_runtime_bootstrap(
        self,
        *,
        tokens: Sequence[str] | None = None,
    ) -> bool:
        """Return whether one CLI run can skip runtime bootstrap.

        :param tokens: Optional command tokens without the program name.
        :return: Whether runtime bootstrap should be avoided.
        """
        return config_request_skips_runtime_bootstrap(
            self.config_group_name,
            tokens=tokens,
            root_flag_options=self.root_flag_options,
            root_value_options=self.root_value_options,
            bootstrapless_actions=self.bootstrapless_actions,
            skip_invalid_options=self.skip_invalid_options,
        )


def config_request_skips_runtime_bootstrap(
    command_name: str = "config",
    *,
    tokens: Sequence[str] | None = None,
    root_flag_options: Collection[str] = COMMON_ROOT_FLAG_OPTIONS,
    root_value_options: Collection[str] = COMMON_ROOT_VALUE_OPTIONS,
    bootstrapless_actions: Collection[str] = (
        DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS
    ),
    skip_invalid_options: bool = True,
) -> bool:
    """Return whether one config CLI run avoids runtime bootstrap.

    :param command_name: Top-level config command name to inspect.
    :param tokens: Optional command tokens without the program name.
    :param root_flag_options: Host-level options that consume no values before
        the config action.
    :param root_value_options: Host-level options that consume a following value
        before the config command.
    :param bootstrapless_actions: Config actions that can run before runtime
        setup.
    :param skip_invalid_options: Whether unknown leading options under the
        config group should skip runtime bootstrap so Typer can report the
        parse error directly.
    :return: Whether the config command can run without runtime state.
    """
    args = args_after_command(
        command_name,
        tokens=tokens,
        root_value_options=root_value_options,
    )
    if args is None:
        return False
    if _help_requested_before_separator(
        args,
        value_options=root_value_options,
    ):
        return True
    if args and args[0] == "--":
        return False
    action_args = strip_leading_options(
        args,
        flag_options=root_flag_options,
        value_options=root_value_options,
    )
    if not action_args:
        return True
    if skip_invalid_options and action_args[0].startswith("-"):
        return True
    return action_args[0] in bootstrapless_actions


def _help_requested_before_separator(
    tokens: Sequence[str],
    *,
    value_options: Collection[str],
) -> bool:
    """Return whether a help flag appears before an option separator."""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            return False
        option_name = token.split("=", maxsplit=1)[0]
        if option_name in value_options:
            i += 1 if "=" in token else 2
            continue
        if token in {"--help", "-h"}:
            return True
        i += 1
    return False


def active_storage_root_from_state(
    kit: AppConfigKit,
    state: ConfigCliState,
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the active storage root from generic CLI state.

    :param kit: Application config facade.
    :param state: Host CLI state object.
    :param explicit_values: Parsed values from host-level ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Resolved storage root, or ``None`` when no selector is active.
    """
    if not kit.spec.storage_required():
        return None
    storage_state = cast(StorageConfigCliState, state)
    if (
        storage_state.env_bootstrap is not None
        and storage_state.env_bootstrap.storage_root is not None
    ):
        return storage_state.env_bootstrap.storage_root
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    if storage_state.storage is not None:
        storage_env_key = kit.spec.require_storage_env_key()
        selected_registry = load_runtime_storage_registry_for_selector(
            kit.spec,
            raw_selector=storage_state.storage,
            proc_env=selector_env,
        )
        selection = resolve_storage_selector_value(
            registry=selected_registry,
            raw_value=storage_state.storage,
            storage_env_key=storage_env_key,
            source="--storage",
        )
        return selection.root if selection is not None else None
    return active_storage_root_from_env(
        kit,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )


def active_storage_root_from_env(
    kit: AppConfigKit,
    *,
    registry: StorageRegistry | None = None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the active storage root selected by the current environment.

    :param kit: Application config facade.
    :param registry: Parsed storage table, or ``None`` for single-storage
        path mode.
    :param explicit_values: Parsed values from root ``--env-file`` options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Resolved storage root, or ``None`` when no env selector is set.
    :raises StorageSelectorError: If the env selector cannot be resolved.
    """
    if not kit.spec.storage_required():
        return None
    storage_env_key = kit.spec.require_storage_env_key()
    explicit_selector_values = explicit_values or {}
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    storage_selector = select_storage_selector(
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        app_wide_values=fallback_values.app_wide_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    if storage_selector is None:
        return None
    source, raw_value = storage_selector
    selected_registry = registry
    if selected_registry is None:
        selected_registry = load_runtime_storage_registry_for_selector(
            kit.spec,
            raw_selector=raw_value,
            proc_env=selector_env,
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
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> str | None:
    """Return the storage that should be selected first in editors.

    :param kit: Application config facade.
    :param state: Host CLI state object.
    :param registry: Optional already-loaded storage table.
    :param explicit_values: Parsed values from host-level ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Storage selector to preselect, or ``None``.
    """
    if state.env_bootstrap is not None:
        return state.env_bootstrap.storage_name
    if not kit.spec.storage_required():
        return None
    storage_state = cast(StorageConfigCliState, state)
    if storage_state.storage is not None:
        return storage_state.storage
    storage_env_key = kit.spec.require_storage_env_key()
    fallback_values = read_storage_selector_fallback_values(kit.spec)
    storage_selector = select_storage_selector(
        storage=None,
        storage_env_key=storage_env_key,
        original_env=os.environ,
        explicit_values=explicit_values or {},
        app_wide_values=fallback_values.app_wide_values,
        shared_values=fallback_values.shared_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    if storage_selector is None:
        return None
    _, raw_value = storage_selector
    if registry is not None and raw_value in registry.storages:
        return raw_value
    return None
