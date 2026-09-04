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
    storage_group = typer.Typer(help="Manage named storages.")
    if kit.spec.uses_storage():
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

    if kit.spec.uses_storage():

        @app.command("setup")
        def config_storage_setup_cmd(
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
            """Create the user dotenv and initial named storage."""
            handlers.setup(
                assume_yes=assume_yes,
                storage_root=storage_root,
            )

    else:

        @app.command("setup")
        def config_user_setup_cmd(
            assume_yes: Annotated[
                bool,
                typer.Option(
                    "--yes",
                    "-y",
                    help="Create the user dotenv without prompting.",
                ),
            ] = False,
        ) -> None:
            """Create the empty per-user dotenv file."""
            handlers.setup(assume_yes=assume_yes, storage_root=None)

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

    @app.command("purge")
    def config_purge_cmd(
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show exact removal targets without changing files.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Remove the listed AppRC-managed targets without prompting.",
            ),
        ] = False,
    ) -> None:
        """Remove AppRC files that package uninstall leaves behind."""
        handlers.purge(dry_run=dry_run, assume_yes=assume_yes)

    if kit.spec.uses_storage():

        @app.command("set")
        def config_storage_set_cmd(
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
                    help="Writable layer to update: user or storage.",
                ),
            ] = None,
        ) -> None:
            """Write one user or storage dotenv override."""
            handlers.set(ctx, key=key, value=value, scope=scope)

    else:

        @app.command("set")
        def config_user_set_cmd(
            ctx: typer.Context,
            key: Annotated[
                str,
                typer.Argument(
                    help=(
                        "Env key, dotted config path, or unique field name to "
                        "write into the user dotenv override file."
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
                    help="Writable layer to update: user.",
                ),
            ] = None,
        ) -> None:
            """Write one user dotenv override."""
            handlers.set(ctx, key=key, value=value, scope=scope)

    @app.command("edit")
    def config_edit_cmd(ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        handlers.edit(ctx)

    @storage_group.command("add")
    def config_storage_add_cmd(
        ctx: typer.Context,
        name: Annotated[
            str,
            typer.Argument(help="New storage selector name."),
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
        """Create one named storage entry."""
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

    @storage_group.command("select")
    def config_storage_select_cmd(
        ctx: typer.Context,
        name: Annotated[
            str,
            typer.Argument(help="Registered storage name to select."),
        ],
    ) -> None:
        """Persist the selected storage name."""
        handlers.storage_select(ctx, name=name)

    @storage_group.command("rename")
    def config_storage_rename_cmd(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="Current storage name.")],
        new_name: Annotated[str, typer.Argument(help="New storage name.")],
    ) -> None:
        """Rename a registered storage without moving data."""
        handlers.storage_rename(ctx, name=name, new_name=new_name)

    @storage_group.command("repoint")
    def config_storage_repoint_cmd(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="Registered storage name.")],
        root: Annotated[
            Path,
            typer.Argument(help="New existing root; no data is moved."),
        ],
    ) -> None:
        """Change only the registered root path."""
        handlers.storage_repoint(ctx, name=name, root=root)

    @storage_group.command("move")
    def config_storage_move_cmd(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="Registered storage name.")],
        destination: Annotated[
            Path,
            typer.Argument(help="New or empty destination directory."),
        ],
        assume_yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Move without confirmation."),
        ] = False,
    ) -> None:
        """Move the complete storage directory and update the registry."""
        handlers.storage_move(
            ctx,
            name=name,
            destination=destination,
            assume_yes=assume_yes,
        )

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
