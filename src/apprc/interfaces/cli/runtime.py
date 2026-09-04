"""Composable Typer runtime for AppRC config command integration."""

from __future__ import annotations

# == Standard Library ========================
import sys
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command.state import (
    ConfigRuntimePolicy,
    DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS,
    DefaultConfigCliState,
)
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.interfaces.cli.context import (
    CliRuntimeContext,
    CliRuntimeOptionsProtocol,
    prepare_cli_runtime_context,
)
from apprc.interfaces.cli._typer_utils import (
    args_after_cli_command,
    parse_leading_options,
    run_typer_app,
    structural_help_requested,
)
from apprc.runtime.result import BootstrapLogger
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli.setup_command import run_config_setup
from apprc.interfaces.cli._interactive_setup import (
    prompt_storage_registration_name,
    prompt_storage_setup_root,
)
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupFlow
from apprc.user_files.storage_roots._loading import (
    load_optional_runtime_storage_registry,
)
from apprc.user_files.storage_roots._naming import suggested_storage_root
from apprc.user_files.storage_roots.selector import (
    MissingStorageSelectorError,
    StorageNotInitializedError,
)

if TYPE_CHECKING:
    from apprc.interfaces.cli.config_command import ConfigSelectorContext
    from apprc.interfaces.tui import ConfigEditorApp

OptionsT = TypeVar("OptionsT", bound=CliRuntimeOptionsProtocol)
StateT = TypeVar("StateT")

type CliArgvProvider = Callable[[], Sequence[str]]
type MountCliRuntimeStateFactory[StateT] = Callable[
    [CliRuntimeContext[Any]],
    StateT,
]
type CliRuntimeStateFactory[OptionsT: CliRuntimeOptionsProtocol, StateT] = (
    Callable[
        [CliRuntimeContext[OptionsT], OptionsT],
        StateT,
    ]
)

_HELP_OPTIONS = frozenset(("--help", "-h"))


@dataclass(slots=True)
class CliRuntimeSession(Generic[StateT]):
    """Prepared AppRC CLI context plus app-owned runtime state.

    :param apprc_context: AppRC bootstrap context stored on Typer metadata.
    :param state: Application runtime state, or ``None`` when bootstrap was
        intentionally skipped.
    """

    apprc_context: CliRuntimeContext[Any]
    state: StateT | None = None

    @property
    def runtime_setup_skipped(self) -> bool:
        """Return whether app runtime state was intentionally not built."""
        return self.apprc_context.runtime_setup_skipped


@dataclass(frozen=True, slots=True)
class RuntimeIndependentCommand:
    """Declare CLI command actions that can run without app runtime state.

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
        """Return whether child tokens match this runtime-independent command.

        :param args: Tokens after the CLI command group.
        :param flag_options: Options that consume no values.
        :param value_options: Options that consume one following value.
        :return: Whether app runtime setup may be skipped.
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
        """Return whether already-stripped action tokens may skip runtime.

        :param action_tokens: Tokens beginning with the child action or help
            option.
        :return: Whether app runtime setup may be skipped.
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
class CliRuntimePolicy:
    """Skip runtime setup for config and declared CLI command paths.

    :param runtime_independent_commands: CLI command declarations keyed by command
        name.
    :param config_runtime_independent_actions: Generated config actions that can run
        without full runtime state.
    :param config_skip_invalid_options: Whether unknown leading generated
        config options should skip runtime setup so Typer can report the
        parse error directly.
    :param extra_cli_flag_options: App-specific CLI options that consume no
        values.
    :param extra_cli_value_options: App-specific CLI options that consume one
        value.
    """

    runtime_independent_commands: Mapping[str, RuntimeIndependentCommand] = (
        field(default_factory=dict)
    )
    config_runtime_independent_actions: Collection[str] = (
        DEFAULT_CONFIG_RUNTIME_INDEPENDENT_ACTIONS
    )
    config_skip_invalid_options: bool = True
    extra_cli_flag_options: Collection[str] = ()
    extra_cli_value_options: Collection[str] = ()

    def __post_init__(self) -> None:
        """Normalize action and option declarations."""
        object.__setattr__(
            self,
            "runtime_independent_commands",
            MappingProxyType(dict(self.runtime_independent_commands)),
        )
        object.__setattr__(
            self,
            "config_runtime_independent_actions",
            frozenset(self.config_runtime_independent_actions),
        )
        object.__setattr__(
            self,
            "extra_cli_flag_options",
            frozenset(self.extra_cli_flag_options),
        )
        object.__setattr__(
            self,
            "extra_cli_value_options",
            frozenset(self.extra_cli_value_options),
        )

    @property
    def cli_flag_options(self) -> Collection[str]:
        """Return AppRC standard flag options plus app-specific additions."""
        return COMMON_CLI_FLAG_OPTIONS | frozenset(self.extra_cli_flag_options)

    @property
    def cli_value_options(self) -> Collection[str]:
        """Return AppRC standard value options plus app-specific additions."""
        return COMMON_CLI_VALUE_OPTIONS | frozenset(
            self.extra_cli_value_options
        )

    def request_skips_runtime(
        self,
        ctx: typer.Context,
        *,
        tokens: Sequence[str],
        config_group_name: str,
    ) -> bool:
        """Return whether one CLI run can avoid runtime state.

        :param ctx: Active Typer context from the app callback.
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
            ).request_skips_runtime(tokens=tokens)
        args = args_after_cli_command(
            command_name,
            tokens=tokens,
            cli_value_options=self.cli_value_options,
        )
        if args is None:
            return False
        declaration = self.runtime_independent_commands.get(command_name)
        if _is_help_request(args):
            return declaration.skip_help if declaration is not None else True
        if declaration is None:
            return False
        parsed = parse_leading_options(
            args,
            flag_options=self.cli_flag_options,
            value_options=self.cli_value_options,
        )
        if parsed.separator_before_action:
            return False
        return declaration.matches_action_tokens(parsed.action_tokens)

    def _config_policy(self, config_group_name: str) -> ConfigRuntimePolicy:
        """Return a config policy aligned with this CLI command shape."""
        return ConfigRuntimePolicy(
            config_group_name=config_group_name,
            root_flag_options=self.cli_flag_options,
            root_value_options=self.cli_value_options,
            runtime_independent_actions=(
                self.config_runtime_independent_actions
            ),
            skip_invalid_options=self.config_skip_invalid_options,
        )


@dataclass(frozen=True, slots=True)
class CliRuntime(Generic[OptionsT, StateT]):
    """Compose AppRC config CLI behavior into an app-owned Typer callback.

    :param kit: Application config facade.
    :param state_type: Runtime state type expected on ``ctx.obj``.
    :param state_factory: Factory that builds app state after AppRC bootstrap.
    :param config_group_name: Name used for the generated config command group.
    :param runtime_policy: Optional runtime skip policy.
    :param args_provider: Optional command-token provider for tests/forwarders.
    :param runtime_payload: Optional serializer for generated ``config show``.
    :param active_storage_root_with_context: Optional selector-aware resolver.
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
    state_factory: CliRuntimeStateFactory[OptionsT, StateT] | None = None
    config_group_name: str = "config"
    runtime_policy: ConfigRuntimePolicy | CliRuntimePolicy | None = None
    args_provider: CliArgvProvider | None = None
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None
    active_storage_root_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], Path | None] | None
    ) = None
    initial_storage_with_context: (
        Callable[[StateT, "ConfigSelectorContext"], str | None] | None
    ) = None
    editor_app_cls: type["ConfigEditorApp"] | None = None
    help: str | None = None
    setup_message: str | None = None
    runtime_error_param_hint: str = "CONFIG"
    setup_logging: Callable[..., Any] | None = None
    logger: BootstrapLogger | None = None
    _forwarded_args: ContextVar[tuple[str, ...] | None] = field(
        default_factory=lambda: ContextVar(
            "apprc_cli_runtime_forwarded_args",
            default=None,
        ),
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate custom state and direct config policy names."""
        if (
            self.state_factory is None
            and self.state_type is not DefaultConfigCliState
        ):
            raise TypeError(
                "CliRuntime requires state_factory when state_type is "
                "custom. Pass state_factory=... or omit state_type to use "
                "DefaultConfigCliState."
            )
        if (
            isinstance(self.runtime_policy, ConfigRuntimePolicy)
            and self.runtime_policy.config_group_name != self.config_group_name
        ):
            raise ValueError(
                "CliRuntime config_group_name must match "
                "runtime_policy.config_group_name."
            )

    def prepare(
        self,
        ctx: typer.Context,
        options: OptionsT,
    ) -> CliRuntimeSession[StateT]:
        """Prepare AppRC metadata and app runtime state for one CLI run.

        :param ctx: Active Typer context from the app callback.
        :param options: CLI option object carrying AppRC-compatible fields.
        :return: Prepared session metadata and optional app state.
        """
        skip_runtime_setup = self._request_skips_runtime(ctx)
        try:
            apprc_context = prepare_cli_runtime_context(
                ctx,
                self.kit,
                options,
                skip_runtime_setup=skip_runtime_setup,
                setup_logging=self.setup_logging,
                logger=self.logger,
            )
        except MissingStorageSelectorError as exc:
            apprc_context = self._first_run_storage_setup(
                ctx,
                options,
                error=exc,
            )
        except StorageNotInitializedError as exc:
            apprc_context = self._initialize_selected_storage(
                ctx,
                options,
                error=exc,
            )
        apprc_context = self._offer_direct_path_registration(
            ctx,
            options,
            apprc_context=apprc_context,
        )
        if apprc_context.runtime_setup_skipped:
            return CliRuntimeSession(apprc_context=apprc_context)

        state = self._build_state(apprc_context, options)
        if not isinstance(state, self.state_type):
            raise RuntimeError(
                "CliRuntime state_factory returned "
                f"{type(state).__name__}; expected {self.state_type.__name__}."
            )
        ctx.obj = state
        return CliRuntimeSession(apprc_context=apprc_context, state=state)

    def _first_run_storage_setup(
        self,
        ctx: typer.Context,
        options: OptionsT,
        *,
        error: MissingStorageSelectorError,
    ) -> CliRuntimeContext[OptionsT]:
        """Offer the short first-run setup and retry runtime preparation.

        :param ctx: Active Typer context.
        :param options: Parsed host CLI options.
        :param error: Missing selector failure that triggered the prompt.
        :return: Prepared context after accepted setup.
        :raises typer.BadParameter: If prompting is disabled or unavailable.
        :raises typer.Exit: If the user declines setup.
        """
        storage = self.kit.spec.storage
        if storage is None or not sys.stdin.isatty() or not sys.stdout.isatty():
            raise typer.BadParameter(
                str(error),
                param_hint=error.param_hint,
            ) from error
        suggested = suggested_storage_root(self.kit.spec.app_id)
        selected_root = prompt_storage_setup_root(suggested=suggested)
        if selected_root is None:
            typer.echo("No files were changed.", err=True)
            typer.echo(
                "Choose another path with "
                f"`{self.kit.spec.config_command_name()} "
                f"{self.config_group_name} setup --storage-root PATH`.",
                err=True,
            )
            raise typer.Exit(code=1)
        run_config_setup(
            self.kit,
            assume_yes=True,
            storage_root=selected_root,
            config_group_name=self.config_group_name,
        )
        return prepare_cli_runtime_context(
            ctx,
            self.kit,
            options,
            setup_logging=self.setup_logging,
            logger=self.logger,
        )

    def _initialize_selected_storage(
        self,
        ctx: typer.Context,
        options: OptionsT,
        *,
        error: StorageNotInitializedError,
    ) -> CliRuntimeContext[OptionsT]:
        """Offer to initialize the exact storage selected for this run.

        :param ctx: Active Typer context.
        :param options: Parsed host CLI options.
        :param error: Readiness error carrying the selected path.
        :return: Prepared context after accepted setup.
        :raises typer.BadParameter: If prompting is unavailable.
        :raises typer.Exit: If the user declines.
        """
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise typer.BadParameter(
                str(error),
                param_hint=error.param_hint,
            ) from error
        typer.echo(str(error), err=True)
        if not typer.confirm(
            f"Initialize AppRC storage at {error.storage_root}?"
        ):
            typer.echo("No files were changed.", err=True)
            raise typer.Exit(code=1)
        storage_name = error.storage_name or self._suggest_registration_name(
            error.storage_root
        )
        try:
            ConfigSetupFlow(self.kit).run_storage_setup(
                error.storage_root,
                storage_name=storage_name,
            )
        except ConfigSetupError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint or error.param_hint,
            ) from exc
        return prepare_cli_runtime_context(
            ctx,
            self.kit,
            options,
            setup_logging=self.setup_logging,
            logger=self.logger,
        )

    def _offer_direct_path_registration(
        self,
        ctx: typer.Context,
        options: OptionsT,
        *,
        apprc_context: CliRuntimeContext[OptionsT],
    ) -> CliRuntimeContext[OptionsT]:
        """Offer to persist an unregistered interactive path selection.

        Non-interactive callers keep using the initialized directory for this
        process without filesystem writes.

        :param ctx: Active Typer context.
        :param options: Parsed host CLI options.
        :param apprc_context: Successful direct-path bootstrap context.
        :return: Original context or a refreshed named-storage context.
        """
        result = apprc_context.env_bootstrap
        if (
            result is None
            or result.storage_selector_kind != "path"
            or result.storage_name is not None
            or result.storage_root is None
            or not sys.stdin.isatty()
            or not sys.stdout.isatty()
        ):
            return apprc_context
        typer.echo(
            f"Storage path {result.storage_root} is initialized but not "
            "registered in apprc.toml."
        )
        if not typer.confirm("Register this path for future use?"):
            typer.echo("Using the unregistered path for this process only.")
            return apprc_context
        suggestion = self._suggest_registration_name(result.storage_root)
        name = prompt_storage_registration_name(suggested=suggestion)
        if name is None:
            typer.echo("Registration canceled; using the path once.", err=True)
            return apprc_context
        try:
            ConfigSetupFlow(self.kit).run_storage_setup(
                result.storage_root,
                storage_name=name,
            )
        except ConfigSetupError as exc:
            typer.echo(
                f"Could not register storage: {exc}",
                err=True,
            )
            typer.echo("Using the unregistered path for this process only.")
            return apprc_context
        typer.echo(f"Registered storage {name!r} at {result.storage_root}.")
        return prepare_cli_runtime_context(
            ctx,
            self.kit,
            options,
            setup_logging=self.setup_logging,
            logger=self.logger,
        )

    def _suggest_registration_name(self, storage_root: Path) -> str:
        """Return ``default`` for the first row, otherwise the basename.

        :param storage_root: Directly selected storage path.
        :return: Suggested registry name.
        """
        try:
            registry = load_optional_runtime_storage_registry(self.kit.spec)
        except (OSError, ValueError):
            return "default"
        if registry is None or not registry.storages:
            return "default"
        return storage_root.name.strip() or "storage"

    def _build_state(
        self,
        apprc_context: CliRuntimeContext[OptionsT],
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
        """Mount the generated config group on a Typer app.

        :param app: Typer application.
        :return: Mounted config Typer application.
        """
        ensure_config_group_name_available(app, self.config_group_name)
        config_app = self.kit.typer_app(
            state_type=self.state_type,
            runtime_payload=self.runtime_payload,
            active_storage_root_with_context=(
                self.active_storage_root_with_context
            ),
            initial_storage_with_context=self.initial_storage_with_context,
            editor_app_cls=self.editor_app_cls,
            help=self.help,
            setup_message=self.setup_message,
            runtime_error_param_hint=self.runtime_error_param_hint,
            config_group_name=self.config_group_name,
        )
        app.add_typer(config_app, name=self.config_group_name)
        return config_app

    def _request_skips_runtime(self, ctx: typer.Context) -> bool:
        """Return whether this CLI run can avoid app runtime state."""
        if ctx.resilient_parsing:
            return True
        policy = self.runtime_policy or CliRuntimePolicy()
        tokens = self.current_args()
        if isinstance(policy, CliRuntimePolicy):
            return policy.request_skips_runtime(
                ctx,
                tokens=tokens,
                config_group_name=self.config_group_name,
            )
        return policy.request_skips_runtime(tokens=tokens)

    def current_args(self) -> Sequence[str]:
        """Return the command tokens this runtime should inspect.

        :return: Forwarded tokens during ``run_forwarded(...)`` or the app's
            normal argument provider otherwise.
        """
        forwarded_args = self._forwarded_args.get()
        if forwarded_args is not None:
            return forwarded_args
        if self.args_provider is not None:
            return self.args_provider()
        return sys.argv[1:]

    @contextmanager
    def forwarded_args(self, args: Sequence[str]) -> Iterator[None]:
        """Temporarily make this runtime inspect forwarded child tokens.

        :param args: Child app arguments without a program name.
        :return: Context manager that restores the previous argument source.
        """
        token = self._forwarded_args.set(tuple(args))
        try:
            yield
        finally:
            self._forwarded_args.reset(token)

    def run_forwarded(
        self,
        target_app: typer.Typer,
        *,
        args: Sequence[str],
        prog_name: str,
    ) -> None:
        """Run a nested Typer app while preserving AppRC runtime inspection.

        :param target_app: Typer app to execute in this process.
        :param args: Child app arguments without a program name.
        :param prog_name: Display program name for help and errors.
        """
        forwarded_args = tuple(args)
        with self.forwarded_args(forwarded_args):
            run_typer_app(
                target_app,
                args=list(forwarded_args),
                prog_name=prog_name,
            )


def ensure_config_group_name_available(
    app: typer.Typer,
    config_group_name: str,
) -> None:
    """Raise when a Typer app already owns the config group name."""
    if config_group_name not in _registered_typer_names(app):
        return
    raise RuntimeError(
        "CliRuntime cannot mount the generated config group because "
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
            f"RuntimeIndependentCommand {field_name} must not contain empty "
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
