"""Composable Typer bridge for AppRC config command integration."""

from __future__ import annotations

# == Standard Library ========================
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command.state import (
    ConfigBootstrapPolicy,
    DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS,
    DefaultConfigCliState,
)
from apprc.interfaces.cli.options import (
    COMMON_HOST_FLAG_OPTIONS,
    COMMON_HOST_VALUE_OPTIONS,
)
from apprc.interfaces.cli.context import (
    CliBootstrapContext,
    CliBootstrapOptionsProtocol,
    prepare_typer_context,
)
from apprc.interfaces.cli._typer_utils import (
    args_after_host_command,
    parse_leading_options,
    structural_help_requested,
)
from apprc.runtime.result import BootstrapLogger
from apprc.definition.app_config.kit import AppConfigKit

if TYPE_CHECKING:
    from apprc.interfaces.cli.config_command import ConfigSelectorContext
    from apprc.interfaces.tui import ConfigEditorApp

OptionsT = TypeVar("OptionsT", bound=CliBootstrapOptionsProtocol)
StateT = TypeVar("StateT")

type CliArgvProvider = Callable[[], Sequence[str]]
type MountConfigCliStateFactory[StateT] = Callable[
    [CliBootstrapContext],
    StateT,
]
type ConfigCliStateFactory[OptionsT, StateT] = Callable[
    [CliBootstrapContext, OptionsT],
    StateT,
]

_HELP_OPTIONS = frozenset(("--help", "-h"))


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

    :param exact_actions: Complete action-token sequences that do not need
        runtime state.
    :param action_prefixes: Action-token prefixes whose whole subtrees do not
        need runtime state.
    :param skip_empty: Whether a bare command group may skip runtime state.
    :param skip_help: Whether help for this command group or its declared
        actions may skip runtime state.
    """

    exact_actions: Collection[tuple[str, ...]] = ()
    action_prefixes: Collection[tuple[str, ...]] = ()
    skip_empty: bool = False
    skip_help: bool = True

    def __post_init__(self) -> None:
        """Normalize action declarations for stable matching."""
        exact_actions = _normalize_action_paths(
            self.exact_actions,
            field_name="exact_actions",
        )
        action_prefixes = _normalize_action_paths(
            self.action_prefixes,
            field_name="action_prefixes",
        )
        object.__setattr__(self, "exact_actions", exact_actions)
        object.__setattr__(
            self,
            "action_prefixes",
            action_prefixes,
        )

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
        parsed = parse_leading_options(
            args,
            flag_options=flag_options,
            value_options=value_options,
        )
        if parsed.separator_before_action:
            return False
        return self.matches_action_tokens(parsed.action_tokens)

    def matches_action_tokens(self, action_tokens: Sequence[str]) -> bool:
        """Return whether already-stripped action tokens may skip bootstrap.

        :param action_tokens: Tokens beginning with the child action or help
            option.
        :return: Whether app runtime bootstrap may be skipped.
        """
        if not action_tokens:
            return self.skip_empty
        if _is_help_request(action_tokens):
            return self.skip_help
        if self._matches_declared_action_help(action_tokens):
            return self.skip_help
        if _matches_any_exact(action_tokens, self.exact_actions):
            return True
        return _matches_any_prefix(action_tokens, self.action_prefixes)

    def _matches_declared_action_help(
        self,
        action_tokens: Sequence[str],
    ) -> bool:
        """Return whether tokens are help for one declared action path."""
        for action in self.exact_actions:
            action_length = len(action)
            if tuple(
                action_tokens[:action_length]
            ) == action and _is_help_request(action_tokens[action_length:]):
                return True
        for prefix in self.action_prefixes:
            prefix_length = len(prefix)
            if tuple(
                action_tokens[:prefix_length]
            ) == prefix and structural_help_requested(
                action_tokens[prefix_length:]
            ):
                return True
        return False


@dataclass(frozen=True, slots=True)
class HostCliBootstrapPolicy:
    """Skip runtime bootstrap for config and declared host command paths.

    :param bootstrapless_commands: Host command declarations keyed by command
        name.
    :param config_bootstrapless_actions: Generated config actions that can run
        without full runtime state.
    :param config_skip_invalid_options: Whether unknown leading generated
        config options should skip runtime bootstrap so Typer can report the
        parse error directly.
    :param extra_host_flag_options: App-specific host options that consume no
        values.
    :param extra_host_value_options: App-specific host options that consume one
        value.
    """

    bootstrapless_commands: Mapping[str, BootstraplessCommand] = field(
        default_factory=dict
    )
    config_bootstrapless_actions: Collection[str] = (
        DEFAULT_CONFIG_BOOTSTRAPLESS_ACTIONS
    )
    config_skip_invalid_options: bool = True
    extra_host_flag_options: Collection[str] = ()
    extra_host_value_options: Collection[str] = ()

    def __post_init__(self) -> None:
        """Normalize action and option declarations."""
        object.__setattr__(
            self,
            "bootstrapless_commands",
            MappingProxyType(dict(self.bootstrapless_commands)),
        )
        object.__setattr__(
            self,
            "config_bootstrapless_actions",
            frozenset(self.config_bootstrapless_actions),
        )
        object.__setattr__(
            self,
            "extra_host_flag_options",
            frozenset(self.extra_host_flag_options),
        )
        object.__setattr__(
            self,
            "extra_host_value_options",
            frozenset(self.extra_host_value_options),
        )

    @property
    def host_flag_options(self) -> Collection[str]:
        """Return AppRC standard flag options plus app-specific additions."""
        return COMMON_HOST_FLAG_OPTIONS | frozenset(
            self.extra_host_flag_options
        )

    @property
    def host_value_options(self) -> Collection[str]:
        """Return AppRC standard value options plus app-specific additions."""
        return COMMON_HOST_VALUE_OPTIONS | frozenset(
            self.extra_host_value_options
        )

    def request_skips_runtime_bootstrap(
        self,
        ctx: typer.Context,
        *,
        tokens: Sequence[str],
        config_group_name: str,
    ) -> bool:
        """Return whether one host CLI run can avoid runtime state.

        :param ctx: Active Typer context from the host callback.
        :param tokens: Command tokens without the executable name.
        :param config_group_name: Generated config command group name.
        :return: Whether app runtime state can be skipped.
        """
        command_name = ctx.invoked_subcommand
        if command_name is None:
            return False
        if command_name == config_group_name:
            return self._config_policy(
                config_group_name,
            ).request_skips_runtime_bootstrap(tokens=tokens)
        args = args_after_host_command(
            command_name,
            tokens=tokens,
            host_value_options=self.host_value_options,
        )
        if args is None:
            return False
        declaration = self.bootstrapless_commands.get(command_name)
        if _is_help_request(args):
            return declaration.skip_help if declaration is not None else True
        if declaration is None:
            return False
        parsed = parse_leading_options(
            args,
            flag_options=self.host_flag_options,
            value_options=self.host_value_options,
        )
        if parsed.separator_before_action:
            return False
        return declaration.matches_action_tokens(parsed.action_tokens)

    def _config_policy(self, config_group_name: str) -> ConfigBootstrapPolicy:
        """Return a config policy aligned with this host command shape."""
        return ConfigBootstrapPolicy(
            config_group_name=config_group_name,
            root_flag_options=self.host_flag_options,
            root_value_options=self.host_value_options,
            bootstrapless_actions=self.config_bootstrapless_actions,
            skip_invalid_options=self.config_skip_invalid_options,
        )


@dataclass(frozen=True, slots=True)
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
    state_type: type[StateT] = field(
        default=cast(type[StateT], DefaultConfigCliState)
    )
    state_factory: ConfigCliStateFactory[OptionsT, StateT] | None = None
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

    def __post_init__(self) -> None:
        """Validate custom state and direct config policy names."""
        if (
            self.state_factory is None
            and self.state_type is not DefaultConfigCliState
        ):
            raise TypeError(
                "ConfigCliBridge requires state_factory when state_type is "
                "custom. Pass state_factory=... or omit state_type to use "
                "DefaultConfigCliState."
            )
        if (
            isinstance(self.bootstrap_policy, ConfigBootstrapPolicy)
            and self.bootstrap_policy.config_group_name
            != self.config_group_name
        ):
            raise ValueError(
                "ConfigCliBridge config_group_name must match "
                "bootstrap_policy.config_group_name."
            )

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
            return ConfigCliSession(apprc_context=apprc_context)

        state = self._build_state(apprc_context, options)
        if not isinstance(state, self.state_type):
            raise RuntimeError(
                "ConfigCliBridge state_factory returned "
                f"{type(state).__name__}; expected {self.state_type.__name__}."
            )
        ctx.obj = state
        return ConfigCliSession(apprc_context=apprc_context, state=state)

    def _build_state(
        self,
        apprc_context: CliBootstrapContext,
        options: OptionsT,
    ) -> StateT:
        """Build app-owned state after runtime bootstrap has completed."""
        if self.state_factory is not None:
            return self.state_factory(apprc_context, options)
        return cast(
            StateT,
            DefaultConfigCliState.from_context(apprc_context),
        )

    def mount_config_group(self, app: typer.Typer) -> typer.Typer:
        """Mount the generated config group on a host Typer app.

        :param app: Host Typer application.
        :return: Mounted config Typer application.
        """
        ensure_config_group_name_available(app, self.config_group_name)
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
        policy = self.bootstrap_policy or HostCliBootstrapPolicy()
        tokens = _provided_args(self.args_provider)
        if isinstance(policy, HostCliBootstrapPolicy):
            return policy.request_skips_runtime_bootstrap(
                ctx,
                tokens=tokens,
                config_group_name=self.config_group_name,
            )
        return policy.request_skips_runtime_bootstrap(tokens=tokens)


def _provided_args(args_provider: CliArgvProvider | None) -> Sequence[str]:
    """Return command tokens from a provider or this process."""
    if args_provider is not None:
        return args_provider()
    return sys.argv[1:]


def ensure_config_group_name_available(
    app: typer.Typer,
    config_group_name: str,
) -> None:
    """Raise when a host Typer app already owns the config group name."""
    if config_group_name not in _registered_typer_names(app):
        return
    raise RuntimeError(
        "ConfigCliBridge cannot mount the generated config group because "
        f"this Typer app already has a command or group named "
        f"{config_group_name!r}."
    )


def _registered_typer_names(app: typer.Typer) -> set[str]:
    """Return explicit and implicit command names registered on ``app``."""
    names: set[str] = set()
    for group in app.registered_groups:
        if group.name is not None:
            names.add(group.name)
    for command in app.registered_commands:
        if command.name is not None:
            names.add(command.name)
            continue
        if command.callback is not None:
            names.add(typer.main.get_command_name(command.callback.__name__))
    return names


def _is_help_request(tokens: Sequence[str]) -> bool:
    """Return whether tokens are exactly one recognized help option."""
    return len(tokens) == 1 and tokens[0] in _HELP_OPTIONS


def _normalize_action_paths(
    paths: Collection[tuple[str, ...]],
    *,
    field_name: str,
) -> frozenset[tuple[str, ...]]:
    """Return immutable non-empty action paths for one declaration field."""
    normalized = frozenset(tuple(path) for path in paths)
    if () in normalized:
        raise ValueError(
            f"BootstraplessCommand {field_name} must not contain empty "
            "action paths. Use skip_empty=True for bare command groups."
        )
    return normalized


def _matches_any_exact(
    tokens: Sequence[str],
    exact_actions: Collection[tuple[str, ...]],
) -> bool:
    """Return whether tokens match one complete action declaration."""
    return tuple(tokens) in exact_actions


def _matches_any_prefix(
    tokens: Sequence[str],
    action_prefixes: Collection[tuple[str, ...]],
) -> bool:
    """Return whether tokens begin with one declared action prefix."""
    for prefix in action_prefixes:
        if prefix and tuple(tokens[: len(prefix)]) == prefix:
            return True
    return False
