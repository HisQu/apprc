"""Build reusable ``config`` Typer command groups."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._handlers import ConfigCommandHandlers
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
)
from apprc.interfaces.cli.config_command.group_options import ConfigGroupOptions
from apprc.interfaces.cli.config_command.state import DefaultConfigCliState
from apprc.interfaces.cli.diagnostics.messages import config_setup_message
from apprc.public.app_rc import AppRC

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp

StateT = TypeVar("StateT")


def build_config_typer_app(
    apprc: AppRC,
    *,
    state_type: type[StateT] | None = None,
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_workspace_root_with_context: (
        Callable[[StateT, ConfigSelectorContext], Path | None] | None
    ) = None,
    initial_workspace_with_context: (
        Callable[[StateT, ConfigSelectorContext], str | None] | None
    ) = None,
    editor_app_cls: type[ConfigEditorApp] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    config_group_name: str = "config",
) -> typer.Typer:
    """Build the reusable ``config`` command group.

    :param apprc: Application config facade.
    :param state_type: Application CLI state type stored on ``ctx.obj``.
        When omitted, AppRC uses its default config state.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_workspace_root_with_context: Optional workspace-root resolver
        that receives explicit env-file selector context.
    :param initial_workspace_with_context: Optional editor initial-selection
        resolver that receives explicit env-file selector context.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional command-group help.
    :param setup_message: Optional setup text for missing config.
    :param runtime_error_param_hint: Parameter hint for runtime-payload
        validation errors.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Configured Typer app.
    """
    options = ConfigGroupOptions(
        state_type=state_type or DefaultConfigCliState,
        runtime_payload=runtime_payload,
        active_workspace_root_with_context=active_workspace_root_with_context,
        initial_workspace_with_context=initial_workspace_with_context,
        editor_app_cls=editor_app_cls,
        help=help,
        setup_message=setup_message,
        runtime_error_param_hint=runtime_error_param_hint,
        config_group_name=config_group_name,
    )
    return build_config_typer_app_from_options(apprc, options=options)


def build_config_typer_app_from_options(
    apprc: AppRC,
    *,
    options: ConfigGroupOptions,
) -> typer.Typer:
    """Build the reusable ``config`` command group from internal options.

    :param apprc: Application config facade.
    :param options: Internal generated config command option bundle.
    :return: Configured Typer app.
    """
    app = typer.Typer(
        help=options.help
        or f"Inspect and initialize {apprc.schema.display_name} configuration.",
        invoke_without_command=True,
        no_args_is_help=False,
        pretty_exceptions_show_locals=False,
    )
    secrets_group = typer.Typer(
        help="Inspect and repair saved secret files, or migrate secret fields."
    )
    config_enabled = apprc.schema.paths.config
    user_dotenv_enabled = apprc.schema.uses_user_dotenv()
    has_secret_fields = any(
        field.secret for owner in apprc.schema.owners for field in owner.fields
    )
    if (
        config_enabled
        and has_secret_fields
        and (user_dotenv_enabled or apprc.schema.uses_workspaces())
    ):
        app.add_typer(secrets_group, name="secrets")
    handlers = ConfigCommandHandlers(
        apprc,
        options=options,
        missing_setup=options.setup_message
        or config_setup_message(
            apprc,
            config_group_name=options.config_group_name,
        ),
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
        """Show the resolved runtime config available to this CLI run."""
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

    if (
        config_enabled
        and has_secret_fields
        and (user_dotenv_enabled or apprc.schema.uses_workspaces())
    ):

        @secrets_group.command("migrate")
        def config_secrets_migrate_cmd(
            ctx: typer.Context,
            scope: Annotated[
                str,
                typer.Option(
                    "--scope", help="Migrate user or workspace secrets."
                ),
            ],
            assume_yes: Annotated[
                bool,
                typer.Option(
                    "--yes", "-y", help="Apply the reviewed migration."
                ),
            ] = False,
        ) -> None:
            """Move secret field assignments into the private secret companion."""
            handlers.secrets_migrate(ctx, scope=scope, assume_yes=assume_yes)

        @secrets_group.command("repair")
        def config_secrets_repair_cmd(
            ctx: typer.Context,
            scope: Annotated[
                str,
                typer.Option(
                    "--scope", help="Repair user or workspace secrets."
                ),
            ],
            assume_yes: Annotated[
                bool,
                typer.Option("--yes", "-y", help="Apply the shown repair."),
            ] = False,
        ) -> None:
            """Restrict a selected layer and its secret companion."""
            handlers.secrets_repair(ctx, scope=scope, assume_yes=assume_yes)

    if config_enabled:

        @app.command("init")
        def config_init_cmd(
            ctx: typer.Context,
            adopt: Annotated[
                bool,
                typer.Option(
                    "--adopt",
                    help="Accept an existing unowned config directory.",
                ),
            ] = False,
        ) -> None:
            """Initialize the enabled config directory."""
            handlers.setup(ctx, assume_yes=True, adopt=adopt)

    if user_dotenv_enabled:

        @app.command("setup")
        def config_setup_cmd(
            ctx: typer.Context,
            assume_yes: Annotated[
                bool,
                typer.Option(
                    "--yes", "-y", help="Run setup without interactive prompts."
                ),
            ] = False,
            adopt: Annotated[
                bool,
                typer.Option(
                    "--adopt",
                    help="Accept an existing unowned config directory.",
                ),
            ] = False,
        ) -> None:
            """Initialize the declared user configuration files."""
            handlers.setup(ctx, assume_yes=assume_yes, adopt=adopt)

    if apprc.schema.owners:

        @app.command("set")
        def config_set_cmd(
            ctx: typer.Context,
            key: Annotated[
                str,
                typer.Argument(
                    help=(
                        "Env key, dotted config path, or unique field name to "
                        "write into a declared AppRC dotenv file."
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
                    help=(
                        "Writable layer to update. Available values depend on "
                        "the application declaration."
                    ),
                ),
            ] = None,
        ) -> None:
            """Write one override into a declared and initialized dotenv."""
            handlers.set(ctx, key=key, value=value, scope=scope)

        @app.command("edit")
        def config_edit_cmd(ctx: typer.Context) -> None:
            """Open the Textual editor for declared dotenv files."""
            handlers.edit(ctx)

    return app
