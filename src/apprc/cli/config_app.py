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
from typing import Annotated, Any, Protocol, TypeVar, cast

# == 3rd Party ===============================
import typer
from rich import print as rich_print

# == Internal ================================
from apprc.cli.doctor import (
    build_config_doctor_payload,
    config_setup_message,
    print_config_doctor,
)
from apprc.cli.typer_utils import dump_json, exit_missing_action, state_from
from apprc.config.environment import EnvBootstrapResult
from apprc.config.kit import AppConfigKit

StateT = TypeVar("StateT")


class ConfigCliState(Protocol):
    """Root CLI state fields understood by the generic config app."""

    env_bootstrap: EnvBootstrapResult | None
    storage: str | None


def config_request_skips_bootstrap(args: list[str]) -> bool:
    """Return whether one config invocation avoids runtime bootstrap.

    :param args: Tokens after the top-level ``config`` command.
    :return: Whether the config command can run without root config state.
    """
    if not args:
        return True
    if args == ["--json"]:
        return True
    return args[0] in {"doctor", "set-default"}


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
    env_storage = os.environ.get(kit.spec.storage_root_env_key)
    if env_storage:
        return Path(env_storage).expanduser()
    return None


def initial_storage_from_state(state: ConfigCliState) -> str | None:
    """Return the storage that should be selected first in editors."""
    if state.env_bootstrap is not None:
        return state.env_bootstrap.storage_name
    return state.storage


def build_config_typer_app(
    kit: AppConfigKit,
    *,
    state_type: type[StateT],
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_storage_root: Callable[[StateT], Path | None] | None = None,
    initial_storage: Callable[[StateT], str | None] | None = None,
    editor_app_cls: type[Any] | None = None,
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
    missing_setup = setup_message or config_setup_message(kit)
    migration_message = (
        legacy_json_migration_message
        or f"Use: {kit.spec.app_name} config show --json"
    )

    def _state(ctx: typer.Context) -> StateT:
        """Return the application root state stored by the parent CLI."""
        return state_from(ctx, state_type)

    def _active_storage_root(state: StateT) -> Path | None:
        """Return the selected storage root using app overrides first."""
        if active_storage_root is not None:
            return active_storage_root(state)
        return active_storage_root_from_state(kit, cast(ConfigCliState, state))

    def _initial_storage(state: StateT) -> str | None:
        """Return the storage name the editor should select on startup."""
        if initial_storage is not None:
            return initial_storage(state)
        return initial_storage_from_state(cast(ConfigCliState, state))

    def _required_storage_root(state: StateT) -> Path:
        """Return an active storage root or raise Typer's CLI error type."""
        storage_root = _active_storage_root(state)
        if storage_root is not None:
            return storage_root
        raise typer.BadParameter(
            f"No active {kit.spec.display_name} storage root. Run "
            f"`{kit.spec.app_name} config init STORAGE_ROOT --name NAME` "
            "or pass --storage.",
            param_hint="--storage",
        )

    def _validate_storage_root_for_write(storage_root: Path) -> Path:
        """Reject writes when the active storage root no longer exists."""
        root = Path(storage_root).expanduser()
        if not root.is_dir():
            raise typer.BadParameter(
                f"Active storage root does not exist: {root}",
                param_hint="--storage",
            )
        return root

    def _root_context_param(ctx: typer.Context, name: str) -> Any:
        """Read one option value from the parent command context."""
        if ctx.parent is None:
            return None
        return ctx.parent.params.get(name)

    def _default_runtime_payload(state: StateT) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        storage_root = _active_storage_root(state)
        return {
            "app_name": kit.spec.app_name,
            "display_name": kit.spec.display_name,
            "registry_path": str(kit.registry_path()),
            "storage_root": str(storage_root) if storage_root else None,
        }

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
        if ctx.invoked_subcommand is not None:
            return
        if legacy_json:
            typer.echo(migration_message, err=True)
            raise typer.Exit(code=2)
        exit_missing_action(ctx)

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
        current_state = _state(ctx)
        if _active_storage_root(current_state) is None:
            typer.echo(missing_setup, err=True)
            raise typer.Exit(code=1)
        try:
            payload = (
                runtime_payload(current_state)
                if runtime_payload is not None
                else _default_runtime_payload(current_state)
            )
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=runtime_error_param_hint,
            ) from exc
        if json_output:
            dump_json(payload)
            return
        rich_print(payload)

    @app.command("doctor")
    def config_doctor_cmd(
        ctx: typer.Context,
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """Check local storage setup and print suggested fixes."""
        storage = _root_context_param(ctx, "storage")
        storage_name = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(kit, storage_name=storage_name)
        if json_output:
            dump_json(payload)
        else:
            print_config_doctor(kit, payload)
        if not payload["ok"]:
            raise typer.Exit(code=1)

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
    ) -> None:
        """Register one storage root and create its local env file."""
        try:
            registry = kit.register_storage(
                name=name,
                root=storage_root,
                make_default=make_default,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--name") from exc

        record = registry.selected(name)
        typer.echo(f"registered_storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(f"local_env: {record.root / kit.spec.local_env_filename}")
        typer.echo(f"registry: {registry.path}")
        typer.echo(f"default_storage: {registry.default_storage}")

    @app.command("set-default")
    def config_set_default_cmd(
        name: Annotated[
            str,
            typer.Argument(
                help="Existing storage selector to make the default."
            ),
        ],
    ) -> None:
        """Set the default storage used when no ``--storage`` is passed."""
        try:
            old_default = kit.load_registry().default_storage
            registry = kit.set_default_storage(name=name)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"previous_default_storage: {old_default}")
        typer.echo(f"default_storage: {registry.default_storage}")
        typer.echo(f"registry: {registry.path}")

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
        root = _validate_storage_root_for_write(
            _required_storage_root(_state(ctx))
        )
        try:
            update = kit.set_local_value(
                storage_root=root,
                reference=key,
                raw_value=value,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"local_env: {update.path}")

    @app.command("edit")
    def config_edit_cmd(ctx: typer.Context) -> None:
        """Open the Textual editor for registered storage-local env files."""
        current_state = _state(ctx)
        try:
            registry = kit.load_registry()
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=kit.spec.registry_filename,
            ) from exc
        if not registry.storages:
            typer.echo(missing_setup, err=True)
            raise typer.Exit(code=2)
        selected_storage = _initial_storage(current_state)
        if editor_app_cls is not None:
            editor_app = editor_app_cls(
                registry=registry,
                initial_storage=selected_storage,
            )
        else:
            editor_app = kit.editor_app(
                registry=registry,
                initial_storage=selected_storage,
            )
        editor_app.run()

    return app
