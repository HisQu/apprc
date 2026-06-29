"""Composable Typer bridge for AppRC config command integration."""

from __future__ import annotations

# == Standard Library ========================
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.config.state import (
    ConfigBootstrapPolicy,
)
from apprc.cli.options import (
    COMMON_ROOT_FLAG_OPTIONS,
    COMMON_ROOT_VALUE_OPTIONS,
)
from apprc.cli.context import (
    CliBootstrapContext,
    CliBootstrapOptionsProtocol,
    prepare_typer_context,
)
from apprc.cli.typer_utils import args_after_command, strip_leading_options
from apprc.runtime_config.bootstrap.result import BootstrapLogger
from apprc.runtime_config.kit import AppConfigKit

if TYPE_CHECKING:
    from apprc.cli.config import ConfigSelectorContext
    from apprc.runtime_config.tui import ConfigEditorApp

OptionsT = TypeVar("OptionsT", bound=CliBootstrapOptionsProtocol)
StateT = TypeVar("StateT")

type CliArgvProvider = Callable[[], Sequence[str]]
type CliStateFactory[StateT] = Callable[[CliBootstrapContext], StateT]
type ConfigCliStateFactory[OptionsT, StateT] = Callable[
    [CliBootstrapContext, OptionsT],
    StateT,
]


@dataclass(slots=True)
class ConfigCliSession(Generic[StateT]):
    """Prepared AppRC CLI context plus app-owned runtime state.

    :param apprc_context: AppRC bootstrap context stored on Typer metadata.
    :param state: Application runtime state, or ``None`` when bootstrap was
        intentionally skipped.
    """

    apprc_context: CliBootstrapContext
    state: StateT | None = None

    @property
    def skipped_runtime_bootstrap(self) -> bool:
        """Return whether app runtime state was intentionally not built."""
        return self.apprc_context.skipped_runtime_bootstrap


@dataclass(frozen=True, slots=True)
class BootstraplessCommand:
    """Declare host command actions that can run without app runtime state.

    :param actions: Action-token sequences that do not need runtime state.
    :param skip_empty: Whether a bare command group may skip runtime state.
    """

    actions: Collection[tuple[str, ...]] = ()
    skip_empty: bool = False

    def matches(
        self,
        args: Sequence[str],
        *,
        flag_options: Collection[str],
        value_options: Collection[str],
    ) -> bool:
        """Return whether child tokens match this bootstrapless declaration.

        :param args: Tokens after the host command group.
        :param flag_options: Options that consume no values.
        :param value_options: Options that consume one following value.
        :return: Whether app runtime bootstrap may be skipped.
        """
        action_tokens = strip_leading_options(
            args,
            flag_options=flag_options,
            value_options=value_options,
        )
        if not action_tokens:
            return self.skip_empty
        return tuple(action_tokens) in self.actions


@dataclass(frozen=True, slots=True)
class HostCliBootstrapPolicy:
    """Skip runtime bootstrap for config and declared host command paths.

    :param config_group_name: Generated config command group name.
    :param config_policy: Optional generated config command skip policy.
    :param bootstrapless_commands: Host command declarations keyed by command
        name.
    :param host_flag_options: Host options that consume no values.
    :param host_value_options: Host options that consume one value.
    """

    config_group_name: str = "config"
    config_policy: ConfigBootstrapPolicy | None = None
    bootstrapless_commands: Mapping[str, BootstraplessCommand] = field(
        default_factory=dict
    )
    host_flag_options: Collection[str] = COMMON_ROOT_FLAG_OPTIONS
    host_value_options: Collection[str] = COMMON_ROOT_VALUE_OPTIONS

    def request_skips_runtime_bootstrap(
        self,
        ctx: typer.Context,
        *,
        tokens: Sequence[str],
    ) -> bool:
        """Return whether one host CLI run can avoid runtime state.

        :param ctx: Active Typer context from the host callback.
        :param tokens: Command tokens without the executable name.
        :return: Whether app runtime state can be skipped.
        """
        if _help_requested_before_separator(
            tokens,
            value_options=self.host_value_options,
        ):
            return True
        command_name = ctx.invoked_subcommand
        if command_name is None:
            return False
        args = args_after_command(
            command_name,
            tokens=tokens,
            root_value_options=self.host_value_options,
        )
        if args is None:
            return False
        if _help_requested_before_separator(
            args,
            value_options=self.host_value_options,
        ):
            return True
        if command_name == self.config_group_name:
            return self._config_policy().request_skips_runtime_bootstrap(
                tokens=tokens,
            )
        declaration = self.bootstrapless_commands.get(command_name)
        if declaration is None:
            return False
        return declaration.matches(
            args,
            flag_options=self.host_flag_options,
            value_options=self.host_value_options,
        )

    def _config_policy(self) -> ConfigBootstrapPolicy:
        """Return a config policy aligned with this host command shape."""
        return replace(
            self.config_policy
            or ConfigBootstrapPolicy(config_group_name=self.config_group_name),
            config_group_name=self.config_group_name,
            root_flag_options=self.host_flag_options,
            root_value_options=self.host_value_options,
        )


@dataclass(slots=True)
class ConfigCliBridge(Generic[OptionsT, StateT]):
    """Compose AppRC config CLI behavior into a host-owned Typer callback.

    :param kit: Application config facade.
    :param state_type: Runtime state type expected on ``ctx.obj``.
    :param state_factory: Factory that builds app state after AppRC bootstrap.
    :param config_group_name: Name used for the generated config command group.
    :param bootstrap_policy: Optional bootstrap skip policy.
    :param args_provider: Optional command-token provider for tests/forwarders.
    :param runtime_payload: Optional serializer for generated ``config show``.
    :param active_storage_root: Optional storage-root resolver for app state.
    :param active_storage_root_with_context: Optional selector-aware resolver.
    :param initial_storage: Optional editor initial-selection resolver.
    :param initial_storage_with_context: Optional selector-aware editor resolver.
    :param editor_app_cls: Optional Textual config editor subclass.
    :param help: Optional generated config group help text.
    :param setup_message: Optional setup text for missing storage.
    :param runtime_error_param_hint: Parameter hint for runtime-payload errors.
    :param setup_logging: Optional application logging setup callable.
    :param logger: Optional application logger for bootstrap status.
    """

    kit: AppConfigKit
    state_type: type[StateT]
    state_factory: ConfigCliStateFactory[OptionsT, StateT]
    config_group_name: str = "config"
    bootstrap_policy: ConfigBootstrapPolicy | HostCliBootstrapPolicy | None = (
        None
    )
    args_provider: CliArgvProvider | None = None
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None
    active_storage_root: Callable[[StateT], Path | None] | None = None
    active_storage_root_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], Path | None] | None
    ) = None
    initial_storage: Callable[[StateT], str | None] | None = None
    initial_storage_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], str | None] | None
    ) = None
    editor_app_cls: type["ConfigEditorApp"] | None = None
    help: str | None = None
    setup_message: str | None = None
    runtime_error_param_hint: str = "CONFIG"
    setup_logging: Callable[..., Any] | None = None
    logger: BootstrapLogger | None = None

    def prepare(
        self,
        ctx: typer.Context,
        options: OptionsT,
    ) -> ConfigCliSession[StateT]:
        """Prepare AppRC metadata and app runtime state for one CLI run.

        :param ctx: Active Typer context from the host callback.
        :param options: Host option object carrying AppRC-compatible fields.
        :return: Prepared session metadata and optional app state.
        """
        apprc_context = prepare_typer_context(
            ctx,
            self.kit,
            options,
            skip_bootstrap=self._request_skips_runtime_bootstrap(ctx),
            setup_logging=self.setup_logging,
            logger=self.logger,
        )
        if apprc_context.skipped_runtime_bootstrap:
            ctx.obj = None
            return ConfigCliSession(apprc_context=apprc_context)

        state = self.state_factory(apprc_context, options)
        if not isinstance(state, self.state_type):
            raise RuntimeError(
                "ConfigCliBridge state_factory returned "
                f"{type(state).__name__}; expected {self.state_type.__name__}."
            )
        ctx.obj = state
        return ConfigCliSession(apprc_context=apprc_context, state=state)

    def mount_config_group(self, app: typer.Typer) -> typer.Typer:
        """Mount the generated config group on a host Typer app.

        :param app: Host Typer application.
        :return: Mounted config Typer application.
        """
        config_app = self.kit.typer_app(
            state_type=self.state_type,
            runtime_payload=self.runtime_payload,
            active_storage_root=self.active_storage_root,
            active_storage_root_with_context=(
                self.active_storage_root_with_context
            ),
            initial_storage=self.initial_storage,
            initial_storage_with_context=self.initial_storage_with_context,
            editor_app_cls=self.editor_app_cls,
            help=self.help,
            setup_message=self.setup_message,
            runtime_error_param_hint=self.runtime_error_param_hint,
            config_group_name=self.config_group_name,
        )
        app.add_typer(config_app, name=self.config_group_name)
        return config_app

    def _request_skips_runtime_bootstrap(self, ctx: typer.Context) -> bool:
        """Return whether this CLI run can avoid app runtime state."""
        if ctx.resilient_parsing:
            return True
        policy = self.bootstrap_policy or ConfigBootstrapPolicy(
            config_group_name=self.config_group_name,
        )
        tokens = _provided_args(self.args_provider)
        if isinstance(policy, HostCliBootstrapPolicy):
            return policy.request_skips_runtime_bootstrap(ctx, tokens=tokens)
        return policy.request_skips_runtime_bootstrap(tokens=tokens)


def _provided_args(args_provider: CliArgvProvider | None) -> Sequence[str]:
    """Return command tokens from a provider or this process."""
    if args_provider is not None:
        return args_provider()
    return sys.argv[1:]


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
