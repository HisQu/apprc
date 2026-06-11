"""Build reusable ``config`` Typer command groups.

Applications own their top-level command tree and domain commands. AppRC owns
the repeatable config workflow that every app with ``AppConfigKit`` needs:
show diagnostics, register storage roots, select defaults, write local
overrides, and open the Textual editor.

The factory in this module receives the application kit and a typed root state
object. App-specific commands stay outside this module; only the shared
``<app> config ...`` behavior belongs here.
"""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypeVar, cast

import typer
from rich import print as rich_print

# == Internal ================================
from apprc.cli.doctor import print_config_doctor
from apprc.config.diagnostics import (
    build_config_doctor_payload,
    config_setup_message,
)
from apprc.cli.options import (
    COMMON_ROOT_FLAG_OPTIONS,
    COMMON_ROOT_VALUE_OPTIONS,
)
from apprc.cli.setup import run_config_setup
from apprc.cli.storage_prompts import guard_storage_root_init
from apprc.cli.storage_output import print_storage_list, storage_list_payload
from apprc.cli.typer_utils import (
    dump_json,
    exit_missing_action,
    state_from,
    strip_leading_options,
)
from apprc.config.apprc_toml import ApprcTomlEnvError
from apprc.config.environment import EnvBootstrapResult
from apprc.config.kit import AppConfigKit
from apprc.config.paths import StorageRootPathError
from apprc.config.storage_selector import (
    StorageSelectorError,
    resolve_active_storage_selection,
)
from apprc.config.storage_registry import StorageRegistry
import apprc.config.setup_flow as setup_flow

StateT = TypeVar("StateT")

if TYPE_CHECKING:
    from apprc.config.tui import ConfigEditorApp


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
        "set-default",
        "setup",
    }


def active_storage_root_from_state(
    kit: AppConfigKit,
    state: ConfigCliState,
) -> Path | None:
    """Return the active storage root from generic CLI state."""
    if (
        state.env_bootstrap is not None
        and state.env_bootstrap.storage_root is not None
    ):
        return state.env_bootstrap.storage_root
    env_storage = os.environ.get(kit.spec.storage_env_key, "").strip()
    if env_storage:
        registry = kit.load_registry()
        selection = resolve_active_storage_selection(
            registry=registry,
            storage_name=None,
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
    """Return the storage that should be selected first in editors."""
    if state.env_bootstrap is not None:
        return state.env_bootstrap.storage_name
    if state.storage is not None:
        return state.storage
    env_storage = os.environ.get(kit.spec.storage_env_key, "").strip()
    if registry is not None and env_storage in registry.storages:
        return env_storage
    return None


class _ConfigCommandHandlers:
    """Command implementations for the generated ``config`` Typer group."""

    def __init__(
        self,
        kit: AppConfigKit,
        *,
        state_type: type[Any],
        runtime_payload: Callable[[Any], Mapping[str, Any]] | None,
        active_storage_root: Callable[[Any], Path | None] | None,
        initial_storage: Callable[[Any], str | None] | None,
        editor_app_cls: type[ConfigEditorApp] | None,
        missing_setup: str,
        migration_message: str,
        runtime_error_param_hint: str,
    ) -> None:
        """Store config command dependencies and extension hooks.

        :param kit: Application config facade.
        :param state_type: Application root CLI state type stored on
            ``ctx.obj``.
        :param runtime_payload: Optional serializer for ``config show``.
        :param active_storage_root: Optional active storage resolver.
        :param initial_storage: Optional editor initial-selection resolver.
        :param editor_app_cls: Optional Textual subclass.
        :param missing_setup: Message shown when runtime storage is absent.
        :param migration_message: Message for the deprecated callback
            ``--json`` option.
        :param runtime_error_param_hint: Parameter hint for runtime payload
            validation errors.
        """
        self.kit = kit
        self.state_type = state_type
        self.runtime_payload = runtime_payload
        self.active_storage_root_hook = active_storage_root
        self.initial_storage_hook = initial_storage
        self.editor_app_cls = editor_app_cls
        self.missing_setup = missing_setup
        self.migration_message = migration_message
        self.runtime_error_param_hint = runtime_error_param_hint

    def callback(self, ctx: typer.Context, legacy_json: bool) -> None:
        """Show config help or route removed callback-level options."""
        if ctx.invoked_subcommand is not None:
            return
        if legacy_json:
            typer.echo(self.migration_message, err=True)
            raise typer.Exit(code=2)
        exit_missing_action(ctx)

    def list(self, *, json_output: bool) -> None:
        """List registered storage roots from the user registry."""
        registry = self.load_config_registry()
        payload = storage_list_payload(
            registry,
            local_env_filename=self.kit.spec.local_env_filename,
        )
        if json_output:
            dump_json(payload)
            return
        print_storage_list(payload)

    def show(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show the resolved runtime config available to this invocation."""
        current_state = self.state(ctx)
        if self.active_storage_root(current_state) is None:
            typer.echo(self.missing_setup, err=True)
            raise typer.Exit(code=1)
        try:
            payload = (
                self.runtime_payload(current_state)
                if self.runtime_payload is not None
                else self.default_runtime_payload(current_state)
            )
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.runtime_error_param_hint,
            ) from exc
        if json_output:
            dump_json(payload)
            return
        rich_print(payload)

    def doctor(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Check local storage setup and print suggested fixes."""
        storage = self.root_context_param(ctx, "storage")
        storage_name = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.kit,
            storage_name=storage_name,
        )
        if json_output:
            dump_json(payload)
        else:
            print_config_doctor(self.kit, payload)
        if not payload["ok"]:
            raise typer.Exit(code=1)

    def init(
        self,
        *,
        storage_root: Path,
        name: str,
        make_default: bool,
        assume_yes: bool,
    ) -> None:
        """Register one storage root and create its local env file."""
        try:
            self.kit.apprc_toml_path()
        except ApprcTomlEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.apprc_toml_env_key(),
            ) from exc
        normalized_root = guard_storage_root_init(
            self.kit,
            storage_root,
            storage_name=name,
            make_default=make_default,
            assume_yes=assume_yes,
        )
        try:
            registry = self.kit.register_storage(
                name=name,
                root=normalized_root,
                make_default=make_default,
            )
        except ApprcTomlEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.apprc_toml_env_key(),
            ) from exc
        except StorageRootPathError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="STORAGE_ROOT",
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--name") from exc

        record = registry.selected(name)
        typer.echo(f"registered_storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(
            f"local_env: {record.root / self.kit.spec.local_env_filename}"
        )
        typer.echo(f"apprc_toml_path: {registry.path}")
        typer.echo(f"default_storage: {registry.default_storage}")

    def setup(
        self,
        *,
        assume_yes: bool,
        apprc_dir: Path | None,
        storage_root: Path | None,
        storage_name: str | None,
        existing_action: setup_flow.ExistingSetupAction | None,
    ) -> None:
        """Interactively configure the AppRC TOML and first storage."""
        run_config_setup(
            self.kit,
            assume_yes=assume_yes,
            apprc_dir=apprc_dir,
            storage_root=storage_root,
            storage_name=storage_name,
            existing_action=existing_action,
        )

    def set_default(self, *, name: str) -> None:
        """Set the default storage used by setup and editor flows."""
        try:
            old_default = self.kit.load_registry().default_storage
            registry = self.kit.set_default_storage(name=name)
        except ApprcTomlEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.apprc_toml_env_key(),
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"previous_default_storage: {old_default}")
        typer.echo(f"default_storage: {registry.default_storage}")
        typer.echo(f"apprc_toml_path: {registry.path}")

    def set(self, ctx: typer.Context, *, key: str, value: str) -> None:
        """Write one active storage-local config override."""
        root = self.validate_storage_root_for_write(
            self.required_storage_root(self.state(ctx))
        )
        try:
            update = self.kit.set_local_value(
                storage_root=root,
                reference=key,
                raw_value=value,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"local_env: {update.path}")

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for registered storage-local env files."""
        registry = self.load_config_registry()
        current_state = (
            ctx.obj if isinstance(ctx.obj, self.state_type) else None
        )
        selected_storage = (
            self.initial_storage(current_state, registry=registry)
            if current_state is not None
            else None
        )
        if self.editor_app_cls is not None:
            editor_app = self.editor_app_cls(
                registry=registry,
                initial_storage=selected_storage,
            )
        else:
            editor_app = self.kit.editor_app(
                registry=registry,
                initial_storage=selected_storage,
            )
        editor_app.run()

    def state(self, ctx: typer.Context) -> Any:
        """Return the application root state stored by the parent CLI."""
        return state_from(ctx, self.state_type)

    def active_storage_root(self, state: Any) -> Path | None:
        """Return the selected storage root using app overrides first."""
        try:
            if self.active_storage_root_hook is not None:
                return self.active_storage_root_hook(state)
            return active_storage_root_from_state(
                self.kit,
                cast(ConfigCliState, state),
            )
        except ApprcTomlEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.apprc_toml_env_key(),
            ) from exc
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def initial_storage(
        self,
        state: Any,
        registry: StorageRegistry | None = None,
    ) -> str | None:
        """Return the storage name the editor should select on startup."""
        if self.initial_storage_hook is not None:
            return self.initial_storage_hook(state)
        return initial_storage_from_state(
            self.kit,
            cast(ConfigCliState, state),
            registry=registry,
        )

    def load_config_registry(self) -> StorageRegistry:
        """Load the registry and raise Typer's parse-error shape on failure."""
        try:
            return self.kit.load_registry()
        except ApprcTomlEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.apprc_toml_env_key(),
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.spec.apprc_toml_filename,
            ) from exc

    def required_storage_root(self, state: Any) -> Path:
        """Return an active storage root or raise Typer's CLI error type."""
        storage_root = self.active_storage_root(state)
        if storage_root is not None:
            return storage_root
        raise typer.BadParameter(
            f"No active {self.kit.spec.display_name} storage root. Run "
            f"`{self.kit.spec.config_command_name()} config init "
            "STORAGE_ROOT --name NAME` "
            "or pass --storage.",
            param_hint="--storage",
        )

    def validate_storage_root_for_write(self, storage_root: Path) -> Path:
        """Reject writes when the active storage root no longer exists."""
        root = Path(storage_root).expanduser()
        if not root.is_dir():
            raise typer.BadParameter(
                f"Active storage root does not exist: {root}",
                param_hint="--storage",
            )
        return root

    def root_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        if ctx.parent is None:
            return None
        return ctx.parent.params.get(name)

    def default_runtime_payload(self, state: Any) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        storage_root = self.active_storage_root(state)
        return {
            "app_name": self.kit.spec.app_name,
            "display_name": self.kit.spec.display_name,
            "apprc_toml_path": str(self.kit.apprc_toml_path()),
            "storage_root": str(storage_root) if storage_root else None,
        }


def build_config_typer_app(
    kit: AppConfigKit,
    *,
    state_type: type[StateT],
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_storage_root: Callable[[StateT], Path | None] | None = None,
    initial_storage: Callable[[StateT], str | None] | None = None,
    editor_app_cls: type[ConfigEditorApp] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    legacy_json_migration_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
) -> typer.Typer:
    """Build the reusable ``config`` command group.

    :param kit: Application config facade.
    :param state_type: Application root CLI state type stored on ``ctx.obj``.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_storage_root: Optional active storage resolver.
    :param initial_storage: Optional editor initial-selection resolver.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional command-group help.
    :param setup_message: Optional setup text for missing storage.
    :param legacy_json_migration_message: Optional deprecated callback
        ``--json`` hint.
    :param runtime_error_param_hint: Parameter hint for runtime-payload
        validation errors.
    :return: Configured Typer app.
    """
    app = typer.Typer(
        help=help
        or f"Inspect and initialize {kit.spec.display_name} configuration.",
        invoke_without_command=True,
        no_args_is_help=False,
        pretty_exceptions_show_locals=False,
    )
    handlers = _ConfigCommandHandlers(
        kit,
        state_type=state_type,
        runtime_payload=cast(
            Callable[[Any], Mapping[str, Any]] | None,
            runtime_payload,
        ),
        active_storage_root=cast(
            Callable[[Any], Path | None] | None,
            active_storage_root,
        ),
        initial_storage=cast(
            Callable[[Any], str | None] | None,
            initial_storage,
        ),
        editor_app_cls=editor_app_cls,
        missing_setup=setup_message or config_setup_message(kit),
        migration_message=(
            legacy_json_migration_message
            or f"Use: {kit.spec.config_command_name()} config show --json"
        ),
        runtime_error_param_hint=runtime_error_param_hint,
    )

    @app.callback(invoke_without_command=True)
    def config_cmd(
        ctx: typer.Context,
        legacy_json: Annotated[
            bool,
            typer.Option(
                "--json",
                hidden=True,
                help="Deprecated. Use the show subcommand with --json.",
            ),
        ] = False,
    ) -> None:
        """Show config help or route removed callback-level options."""
        handlers.callback(ctx, legacy_json)

    @app.command("list")
    def config_list_cmd(
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """List registered storage roots from the user registry."""
        handlers.list(json_output=json_output)

    @app.command("show")
    def config_show_cmd(
        ctx: typer.Context,
        json_output: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Emit machine-readable JSON instead of rich output.",
            ),
        ] = False,
    ) -> None:
        """Show the resolved runtime config available to this invocation."""
        handlers.show(ctx, json_output=json_output)

    @app.command("doctor")
    def config_doctor_cmd(
        ctx: typer.Context,
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """Check local storage setup and print suggested fixes."""
        handlers.doctor(ctx, json_output=json_output)

    @app.command("init")
    def config_init_cmd(
        storage_root: Annotated[
            Path,
            typer.Argument(
                help=("Storage root directory to register for runtime data."),
            ),
        ],
        name: Annotated[
            str,
            typer.Option(
                "--name",
                help="Storage selector name written to the registry.",
            ),
        ],
        make_default: Annotated[
            bool,
            typer.Option(
                "--default/--no-default",
                help="Make this storage the default in the registry.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Reuse a non-empty existing storage root without prompting.",
            ),
        ] = False,
    ) -> None:
        """Register one storage root and create its local env file."""
        handlers.init(
            storage_root=storage_root,
            name=name,
            make_default=make_default,
            assume_yes=assume_yes,
        )

    @app.command("setup")
    def config_setup_cmd(
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Run setup non-interactively with the selected values.",
            ),
        ] = False,
        apprc_dir: Annotated[
            Path | None,
            typer.Option(
                "--apprc-dir",
                "-d",
                help="Directory that will contain the AppRC TOML.",
            ),
        ] = None,
        storage_root: Annotated[
            Path | None,
            typer.Option(
                "--storage-root",
                help="Default storage root for non-interactive setup.",
            ),
        ] = None,
        storage_name: Annotated[
            str | None,
            typer.Option(
                "--name",
                help="Default storage selector for non-interactive setup.",
            ),
        ] = None,
        existing_action: Annotated[
            setup_flow.ExistingSetupAction | None,
            typer.Option(
                "--existing-action",
                help="How to handle an existing registry.",
            ),
        ] = None,
    ) -> None:
        """Interactively configure the AppRC TOML and first storage."""
        handlers.setup(
            assume_yes=assume_yes,
            apprc_dir=apprc_dir,
            storage_root=storage_root,
            storage_name=storage_name,
            existing_action=existing_action,
        )

    @app.command("set-default")
    def config_set_default_cmd(
        name: Annotated[
            str,
            typer.Argument(
                help="Existing storage selector to make the default."
            ),
        ],
    ) -> None:
        """Set the default storage used by setup and editor flows."""
        handlers.set_default(name=name)

    @app.command("set")
    def config_set_cmd(
        ctx: typer.Context,
        key: Annotated[
            str,
            typer.Argument(
                help=(
                    "Env key, dotted config path, or unique field name to "
                    "write into the active storage local env."
                ),
            ),
        ],
        value: Annotated[
            str,
            typer.Argument(
                help="Value to validate and store as a local override."
            ),
        ],
    ) -> None:
        """Write one active storage-local config override."""
        handlers.set(ctx, key=key, value=value)

    @app.command("edit")
    def config_edit_cmd(ctx: typer.Context) -> None:
        """Open the Textual editor for registered storage-local env files."""
        handlers.edit(ctx)

    return app
