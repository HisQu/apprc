"""State helpers for generated AppRC ``config`` commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# == Internal ================================
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli._typer_utils import (
    args_after_cli_command,
    help_requested_before_separator,
    parse_leading_options,
)
from apprc.interfaces.cli.context import CliRuntimeContext
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.public.app_rc import AppRC
from apprc.runtime._selection import selection_env
from apprc.runtime.resolution import ResolvedConfig


class ConfigCliState(Protocol):
    """Host CLI state fields understood by the generic config app."""

    resolved: ResolvedConfig | None
    workspace: str | None


@dataclass(slots=True, kw_only=True)
class DefaultConfigCliState:
    """Default CLI state understood by generated AppRC config commands.

    :param resolved: Runtime resolution result, when resolution ran.
    :param workspace: Optional CLI ``--workspace`` selector.
    """

    resolved: ResolvedConfig | None = None
    workspace: str | None = None

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
            workspace=context.runtime_options.workspace,
        )


DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS = frozenset(
    {
        "doctor",
        "edit",
        "init",
        "paths",
        "secrets",
        "set",
        "setup",
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


def active_workspace_root_from_state(
    apprc: AppRC,
    state: ConfigCliState,
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the active workspace root from generic CLI state.

    :param apprc: Application config facade.
    :param state: Host CLI state object.
    :param explicit_values: Parsed values from CLI ``--env-file`` options.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        process env values during workspace selection.
    :return: Resolved workspace root, or ``None`` when no workspace is active.
    """
    if not apprc.schema.uses_workspaces():
        return None
    if state.resolved is not None:
        workspace = state.resolved.workspace
        return workspace.root if workspace is not None else None
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    resolved = apprc.manage(
        ResolveOptions(
            workspace=state.workspace,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        ),
        environment=selector_env,
    ).resolve()
    return resolved.workspace.root if resolved.workspace is not None else None


def active_workspace_root_from_env(
    apprc: AppRC,
    *,
    workspace: str | None = None,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> Path | None:
    """Return the workspace root selected by the current environment."""
    if not apprc.schema.uses_workspaces():
        return None
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    resolved = apprc.manage(
        ResolveOptions(
            workspace=workspace,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        ),
        environment=selector_env,
    ).resolve()
    return resolved.workspace.root if resolved.workspace is not None else None


def initial_workspace_from_state(
    apprc: AppRC,
    state: ConfigCliState,
    *,
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> str | None:
    """Return the workspace name selected first in config editors."""
    if not apprc.schema.uses_workspaces():
        return None
    if state.resolved is not None:
        workspace = state.resolved.workspace
        return workspace.workspace_name if workspace is not None else None
    selector_env = selection_env(
        original_env=os.environ,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    resolved = apprc.manage(
        ResolveOptions(
            workspace=state.workspace,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        ),
        environment=selector_env,
    ).resolve()
    return (
        resolved.workspace.workspace_name
        if resolved.workspace is not None
        else None
    )
