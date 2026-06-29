"""Build reusable ``config`` Typer command groups."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypeVar, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.config.handlers import ConfigCommandHandlers
from apprc.cli.config.handlers import ConfigSelectorContext
from apprc.cli.config.state import DefaultConfigCliState
from apprc.runtime_config.doctor.payload import config_setup_message
from apprc.runtime_config.kit import AppConfigKit

if TYPE_CHECKING:
    from apprc.runtime_config.tui import ConfigEditorApp

StateT = TypeVar("StateT")


def build_config_typer_app(
    kit: AppConfigKit,
    *,
    state_type: type[StateT] | None = None,
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_storage_root: Callable[[StateT], Path | None] | None = None,
    active_storage_root_with_context: (
        Callable[[StateT, ConfigSelectorContext], Path | None] | None
    ) = None,
    initial_storage: Callable[[StateT], str | None] | None = None,
    initial_storage_with_context: (
        Callable[[StateT, ConfigSelectorContext], str | None] | None
    ) = None,
    editor_app_cls: type[ConfigEditorApp] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    command_name: str = "config",
) -> typer.Typer:
    """Build the reusable ``config`` command group.

    :param kit: Application config facade.
    :param state_type: Application root CLI state type stored on ``ctx.obj``.
        When omitted, AppRC uses its default config state.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_storage_root: Optional active storage resolver.
    :param active_storage_root_with_context: Optional active storage resolver
        that can inspect skipped-bootstrap selector context.
    :param initial_storage: Optional editor initial-selection resolver.
    :param initial_storage_with_context: Optional editor initial-selection
        resolver that can inspect skipped-bootstrap selector context.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional command-group help.
    :param setup_message: Optional setup text for missing storage.
    :param runtime_error_param_hint: Parameter hint for runtime-payload
        validation errors.
    :param command_name: Host command group name used in generated guidance.
    :return: Configured Typer app.
    """
    resolved_state_type = state_type or DefaultConfigCliState
    app = typer.Typer(
        help=help
        or f"Inspect and initialize {kit.spec.display_name} configuration.",
        invoke_without_command=True,
        no_args_is_help=False,
        pretty_exceptions_show_locals=False,
    )
    app_group = typer.Typer(help="Manage the app-wide dotenv layer.")
    storage_group = typer.Typer(help="Manage the named-storage index.")
    if kit.spec.app_wide_allowed():
        app.add_typer(app_group, name="app")
    if kit.spec.named_storage_allowed():
        app.add_typer(storage_group, name="storage")

    handlers = ConfigCommandHandlers(
        kit,
        state_type=resolved_state_type,
        runtime_payload=cast(
            Callable[[Any], Mapping[str, Any]] | None,
            runtime_payload,
        ),
        active_storage_root=cast(
            Callable[[Any], Path | None] | None,
            active_storage_root,
        ),
        active_storage_root_with_context=cast(
            Callable[[Any, ConfigSelectorContext], Path | None] | None,
            active_storage_root_with_context,
        ),
        initial_storage=cast(
            Callable[[Any], str | None] | None,
            initial_storage,
        ),
        initial_storage_with_context=cast(
            Callable[[Any, ConfigSelectorContext], str | None] | None,
            initial_storage_with_context,
        ),
        editor_app_cls=editor_app_cls,
        missing_setup=setup_message
        or config_setup_message(kit, command_name=command_name),
        runtime_error_param_hint=runtime_error_param_hint,
        command_name=command_name,
    )

    @app.callback(invoke_without_command=True)
    def config_cmd(
        ctx: typer.Context,
    ) -> None:
        """Show config help when no subcommand was selected."""
        handlers.callback(ctx)

    @app.command("paths")
    def config_paths_cmd(
        ctx: typer.Context,
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """Show declared and active config paths without writing files."""
        handlers.paths(ctx, json_output=json_output)

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
        """Check AppRC config readiness and print suggested fixes."""
        handlers.doctor(ctx, json_output=json_output)

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
        storage_root: Annotated[
            str | None,
            typer.Option(
                "--storage-root",
                help="Active storage root for non-interactive setup.",
            ),
        ] = None,
    ) -> None:
        """Configure files for the declared AppRC capability layers."""
        handlers.setup(
            assume_yes=assume_yes,
            storage_root=storage_root,
        )

    @app.command("set")
    def config_set_cmd(
        ctx: typer.Context,
        key: Annotated[
            str,
            typer.Argument(
                help=(
                    "Env key, dotted config path, or unique field name to "
                    "write into an active AppRC dotenv override file."
                ),
            ),
        ],
        value: Annotated[
            str,
            typer.Argument(
                help="Value to validate and store as an AppRC override."
            ),
        ],
        scope: Annotated[
            str | None,
            typer.Option(
                "--scope",
                help="Writable layer to update: app or storage.",
            ),
        ] = None,
    ) -> None:
        """Write one active AppRC dotenv config override."""
        handlers.set(ctx, key=key, value=value, scope=scope)

    @app.command("edit")
    def config_edit_cmd(ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        handlers.edit(ctx)

    @app_group.command("init")
    def config_app_init_cmd() -> None:
        """Create the app-wide dotenv file."""
        handlers.app_init()

    @storage_group.command("add")
    def config_storage_add_cmd(
        ctx: typer.Context,
        name: Annotated[
            str,
            typer.Argument(help="Storage selector name to create or update."),
        ],
        path: Annotated[
            Path,
            typer.Argument(help="Storage root directory for this name."),
        ],
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Reuse a non-empty existing storage root without prompting.",
            ),
        ] = False,
    ) -> None:
        """Create or update one named storage entry."""
        handlers.storage_add(
            ctx,
            name=name,
            path=path,
            assume_yes=assume_yes,
        )

    @storage_group.command("list")
    def config_storage_list_cmd(
        ctx: typer.Context,
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """List named storage entries."""
        handlers.storage_list(ctx, json_output=json_output)

    @storage_group.command("remove")
    def config_storage_remove_cmd(
        ctx: typer.Context,
        name: Annotated[
            str,
            typer.Argument(help="Storage selector name to remove."),
        ],
    ) -> None:
        """Remove one named storage entry."""
        handlers.storage_remove(ctx, name=name)

    return app
