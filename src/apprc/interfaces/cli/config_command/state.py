"""State helpers for generated AppRC ``config`` commands."""

from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

# == Standard Library ========================
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

# == Internal ================================
from apprc.interfaces.cli.context import CliRuntimeContext
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.interfaces.cli._typer_utils import (
    args_after_cli_command,
    help_requested_before_separator,
    parse_leading_options,
)
from apprc.runtime.resolution import ResolvedConfig
from apprc.runtime._selection import selection_env
from apprc.public.app_rc import AppRC
from apprc.user_files.storage_roots._loading import (
    load_optional_runtime_storage_registry,
)
from apprc.user_files.storage_roots.registry import StorageRegistry
from apprc.user_files.storage_roots.selector import (
    resolve_active_storage_selection,
)


class ConfigCliState(Protocol):
    """Host CLI state fields understood by the generic config app."""

    resolved: ResolvedConfig | None


class StorageConfigCliState(ConfigCliState, Protocol):
    """Host CLI state fields used by storage-capable config commands."""

    storage: str | None


@dataclass(slots=True, kw_only=True)
class DefaultConfigCliState:
    """Default CLI state understood by generated AppRC config commands.

    :param resolved: Runtime resolution result, when resolution ran.
    :param storage: Optional CLI ``--storage`` selector.
    """

    resolved: ResolvedConfig | None = None
    storage: str | None = None

    @classmethod
    def from_context(
        cls,
        context: CliRuntimeContext,
    ) -> DefaultConfigCliState:
        """Build generic config state from stored AppRC resolution metadata.

        :param context: AppRC resolution context stored on Typer metadata.
        :return: Generic state for generated config commands.
        """
        return cls(
            resolved=context.resolved,
            storage=context.runtime_options.storage,
        )


DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS = frozenset(
    {
        "doctor",
        "edit",
        "migrate",
        "paths",
        "set",
        "secrets",
        "setup",
        "storage",
    }
)


@dataclass(frozen=True, slots=True)
class ConfigRuntimePolicy:
    """Runtime skip policy for a generated config command group.

    :param config_group_name: Top-level config command group to inspect.
    :param runtime_independent_actions: Config actions that can run without
        full runtime state.
    :param root_flag_options: CLI options that consume no values.
    :param root_value_options: CLI options that consume one following
        value before the config command.
    :param skip_invalid_options: Whether unknown leading options under the
        config group should avoid runtime resolution so Typer can report the
        parse error without user-dotenv or runtime failures.
    """

    config_group_name: str = "config"
    runtime_independent_actions: Collection[str] = (
        DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS
    )
    root_flag_options: Collection[str] = COMMON_CLI_FLAG_OPTIONS
    root_value_options: Collection[str] = COMMON_CLI_VALUE_OPTIONS
    skip_invalid_options: bool = True

    def request_skips_runtime(
        self,
        *,
        tokens: Sequence[str] | None = None,
    ) -> bool:
        """Return whether one CLI run can skip runtime resolution.

        :param tokens: Optional command tokens without the program name.
        :return: Whether runtime resolution should be avoided.
        """
        return config_request_skips_runtime(
            self.config_group_name,
            tokens=tokens,
            root_flag_options=self.root_flag_options,
            root_value_options=self.root_value_options,
            runtime_independent_actions=self.runtime_independent_actions,
            skip_invalid_options=self.skip_invalid_options,
        )


def config_request_skips_runtime(
    command_name: str = "config",
    *,
    tokens: Sequence[str] | None = None,
    root_flag_options: Collection[str] = COMMON_CLI_FLAG_OPTIONS,
    root_value_options: Collection[str] = COMMON_CLI_VALUE_OPTIONS,
    runtime_independent_actions: Collection[str] = (
        DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS
    ),
    skip_invalid_options: bool = True,
) -> bool:
    """Return whether one config CLI run avoids runtime resolution.

    :param command_name: Top-level config command name to inspect.
    :param tokens: Optional command tokens without the program name.
    :param root_flag_options: CLI options that consume no values before
        the config action.
    :param root_value_options: CLI options that consume a following value
        before the config command.
    :param runtime_independent_actions: Config actions that can run before
        runtime setup.
    :param skip_invalid_options: Whether unknown leading options under the
        config group should skip runtime resolution so Typer can report the
        parse error directly.
    :return: Whether the config command can run without runtime state.
    """
    args = args_after_cli_command(
        command_name,
        tokens=tokens,
        cli_value_options=root_value_options,
    )
    if args is None:
        return False
    if help_requested_before_separator(
        args,
        value_options=root_value_options,
    ):
        return True
    parsed = parse_leading_options(
        args,
        flag_options=root_flag_options,
        value_options=root_value_options,
    )
    if parsed.separator_before_action:
        return False
    action_args = parsed.action_tokens
    if not action_args:
        return True
    if skip_invalid_options and action_args[0].startswith("-"):
        return True
    return action_args[0] in runtime_independent_actions


def active_storage_root_from_state(
    apprc: AppRC,
    state: ConfigCliState,
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the active storage root from generic CLI state.

    :param apprc: Application config facade.
    :param state: Host CLI state object.
    :param explicit_values: Parsed values from CLI ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Resolved storage root, or ``None`` when no selector is active.
    """
    if not apprc.schema.uses_storage():
        return None
    storage_state = cast(StorageConfigCliState, state)
    if storage_state.resolved is not None:
        selection = storage_state.resolved.selection
        return selection.root if selection is not None else None
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    registry = load_optional_runtime_storage_registry(
        apprc.schema,
        proc_env=selector_env,
    )
    selection = resolve_active_storage_selection(
        registry=registry,
        apprc_toml_path=AppFiles(apprc.schema).preferred_apprc_toml_path(
            selector_env
        ),
        storage=storage_state.storage,
        storage_selector_env_key=apprc.schema.require_storage_selector_env_key(),
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    return selection.root if selection is not None else None


def active_storage_root_from_env(
    apprc: AppRC,
    *,
    registry: StorageRegistry | None = None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the active storage root selected by the current environment.

    :param apprc: Application config facade.
    :param registry: Parsed storage registry, if already loaded.
    :param explicit_values: Parsed values from CLI ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Resolved storage root, or ``None`` when no env selector is set.
    :raises StorageSelectorError: If the env selector cannot be resolved.
    """
    if not apprc.schema.uses_storage():
        return None
    storage_selector_env_key = apprc.schema.require_storage_selector_env_key()
    explicit_selector_values = explicit_values or {}
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    selected_registry = registry
    if selected_registry is None:
        selected_registry = load_optional_runtime_storage_registry(
            apprc.schema,
            proc_env=selector_env,
        )
    selection = resolve_active_storage_selection(
        registry=selected_registry,
        apprc_toml_path=AppFiles(apprc.schema).preferred_apprc_toml_path(
            selector_env
        ),
        storage=None,
        storage_selector_env_key=storage_selector_env_key,
        original_env=os.environ,
        explicit_values=explicit_selector_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    return selection.root if selection is not None else None


def initial_storage_from_state(
    apprc: AppRC,
    state: ConfigCliState,
    registry: StorageRegistry | None = None,
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> str | None:
    """Return the storage that should be selected first in editors.

    :param apprc: Application config facade.
    :param state: Host CLI state object.
    :param registry: Optional already-loaded storage table.
    :param explicit_values: Parsed values from CLI ``--env-file``
        options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during selector resolution.
    :return: Storage selector to preselect, or ``None``.
    """
    if state.resolved is not None:
        return (
            state.resolved.selection.storage_name
            if state.resolved.selection is not None
            else None
        )
    if not apprc.schema.uses_storage():
        return None
    storage_state = cast(StorageConfigCliState, state)
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    selected_registry = registry
    if selected_registry is None:
        selected_registry = load_optional_runtime_storage_registry(
            apprc.schema,
            proc_env=selector_env,
        )
    selection = resolve_active_storage_selection(
        registry=selected_registry,
        apprc_toml_path=AppFiles(apprc.schema).preferred_apprc_toml_path(
            selector_env
        ),
        storage=storage_state.storage,
        storage_selector_env_key=apprc.schema.require_storage_selector_env_key(),
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    return selection.storage_name if selection is not None else None
