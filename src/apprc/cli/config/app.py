"""Build reusable ``config`` Typer command groups.

Applications own their top-level command tree and domain commands. AppRC owns
the repeatable config workflow that every app with ``AppConfigKit`` needs:
show diagnostics, create or register storage roots, write local overrides, and
open the Textual editor.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypeVar, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.cli.config.handlers import ConfigCommandHandlers
from apprc.runtime_config.doctor.payload import config_setup_message
from apprc.runtime_config.kit import AppConfigKit
import apprc.runtime_config.setup.flow as setup_flow

if TYPE_CHECKING:
    from apprc.runtime_config.tui import ConfigEditorApp

StateT = TypeVar("StateT")


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
    handlers = ConfigCommandHandlers(
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
        runtime_error_param_hint=runtime_error_param_hint,
    )

    @app.callback(invoke_without_command=True)
    def config_cmd(
        ctx: typer.Context,
    ) -> None:
        """Show config help when no subcommand was selected."""
        handlers.callback(ctx)

    @app.command("list")
    def config_list_cmd(
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit machine-readable JSON."),
        ] = False,
    ) -> None:
        """List named storage roots from the AppRC TOML file."""
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
        """Check AppRC config readiness and print suggested fixes."""
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
                help="Storage selector name written to the AppRC TOML file.",
            ),
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
        """Register one storage root and create its local env file."""
        handlers.init(
            storage_root=storage_root,
            name=name,
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
                help="Directory that will contain the AppRC TOML file.",
            ),
        ] = None,
        storage_root: Annotated[
            Path | None,
            typer.Option(
                "--storage-root",
                help="Active storage root for non-interactive setup.",
            ),
        ] = None,
        storage_name: Annotated[
            str | None,
            typer.Option(
                "--name",
                help=(
                    "Storage selector for non-interactive multi-storage setup."
                ),
            ),
        ] = None,
        multi_storage: Annotated[
            bool,
            typer.Option(
                "--multi-storage/--single-storage",
                help="Register the active storage for multi-storage management.",
            ),
        ] = False,
        existing_action: Annotated[
            setup_flow.ExistingSetupAction | None,
            typer.Option(
                "--existing-action",
                help="How to handle an existing AppRC TOML file.",
            ),
        ] = None,
    ) -> None:
        """Configure AppRC-managed files and optional storage."""
        handlers.setup(
            assume_yes=assume_yes,
            apprc_dir=apprc_dir,
            storage_root=storage_root,
            storage_name=storage_name,
            multi_storage=multi_storage,
            existing_action=existing_action,
        )

    @app.command("set")
    def config_set_cmd(
        ctx: typer.Context,
        key: Annotated[
            str,
            typer.Argument(
                help=(
                    "Env key, dotted config path, or unique field name to "
                    "write into the active AppRC dotenv override file."
                ),
            ),
        ],
        value: Annotated[
            str,
            typer.Argument(
                help="Value to validate and store as an AppRC override."
            ),
        ],
    ) -> None:
        """Write one active AppRC dotenv config override."""
        handlers.set(ctx, key=key, value=value)

    @app.command("edit")
    def config_edit_cmd(ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        handlers.edit(ctx)

    return app
