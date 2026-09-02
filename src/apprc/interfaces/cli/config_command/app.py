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
from apprc.runtime.diagnostics.messages import config_setup_message
from apprc.definition.app_config.kit import AppConfigKit

if TYPE_CHECKING:
    from apprc.interfaces.tui import ConfigEditorApp

StateT = TypeVar("StateT")


def build_config_typer_app(
    kit: AppConfigKit,
    *,
    state_type: type[StateT] | None = None,
    runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
    active_storage_root_with_context: (
        Callable[[StateT, ConfigSelectorContext], Path | None] | None
    ) = None,
    initial_storage_with_context: (
        Callable[[StateT, ConfigSelectorContext], str | None] | None
    ) = None,
    editor_app_cls: type[ConfigEditorApp] | None = None,
    help: str | None = None,
    setup_message: str | None = None,
    runtime_error_param_hint: str = "CONFIG",
    config_group_name: str = "config",
) -> typer.Typer:
    """Build the reusable ``config`` command group.

    :param kit: Application config facade.
    :param state_type: Application CLI state type stored on ``ctx.obj``.
        When omitted, AppRC uses its default config state.
    :param runtime_payload: Optional serializer for ``config show``.
    :param active_storage_root_with_context: Optional active storage resolver
        that receives explicit env-file selector context.
    :param initial_storage_with_context: Optional editor initial-selection
        resolver that receives explicit env-file selector context.
    :param editor_app_cls: Optional Textual subclass.
    :param help: Optional command-group help.
    :param setup_message: Optional setup text for missing storage.
    :param runtime_error_param_hint: Parameter hint for runtime-payload
        validation errors.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Configured Typer app.
    """
    options = ConfigGroupOptions(
        state_type=state_type or DefaultConfigCliState,
        runtime_payload=runtime_payload,
        active_storage_root_with_context=active_storage_root_with_context,
        initial_storage_with_context=initial_storage_with_context,
        editor_app_cls=editor_app_cls,
        help=help,
        setup_message=setup_message,
        runtime_error_param_hint=runtime_error_param_hint,
        config_group_name=config_group_name,
    )
    return build_config_typer_app_from_options(kit, options=options)


def build_config_typer_app_from_options(
    kit: AppConfigKit,
    *,
    options: ConfigGroupOptions,
) -> typer.Typer:
    """Build the reusable ``config`` command group from internal options.

    :param kit: Application config facade.
    :param options: Internal generated config command option bundle.
    :return: Configured Typer app.
    """
    app = typer.Typer(
        help=options.help
        or f"Inspect and initialize {kit.spec.display_name} configuration.",
        invoke_without_command=True,
        no_args_is_help=False,
        pretty_exceptions_show_locals=False,
    )
    app_group = typer.Typer(help="Manage per-user app config.")
    storage_group = typer.Typer(help="Manage named storages.")
    if kit.spec.app_env_enabled():
        app.add_typer(app_group, name="app")
    if kit.spec.named_storage_enabled():
        app.add_typer(storage_group, name="storage")

    handlers = ConfigCommandHandlers(
        kit,
        options=options,
        missing_setup=options.setup_message
        or config_setup_message(
            kit,
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
            Path | None,
            typer.Option(
                "--storage-root",
                help="Storage directory. Shell path completion is enabled.",
            ),
        ] = None,
    ) -> None:
        """Configure the files required by this AppRC declaration."""
        handlers.setup(
            assume_yes=assume_yes,
            storage_root=storage_root,
        )

    @app.command("migrate")
    def config_migrate_cmd(
        ctx: typer.Context,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show legacy file moves without changing files.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Apply all conflict-free moves without prompting.",
            ),
        ] = False,
    ) -> None:
        """Move legacy AppRC files to their current filenames."""
        handlers.migrate(
            ctx,
            dry_run=dry_run,
            assume_yes=assume_yes,
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
        """Create the per-user app dotenv file."""
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
