"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

import sys

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces._setup_text import setup_finish_text
from apprc.interfaces.cli._errors import app_path_bad_parameter
from apprc.public.app_rc import AppRC
from apprc.services.manager import ConfigManager
from apprc.services.inspection import FieldInspection
from apprc.user_files.app_home.locations import AppRCDirectoryError


def run_config_setup(
    apprc: AppRC,
    *,
    assume_yes: bool = False,
    adopt: bool = False,
    offer_missing: bool = False,
    manager: ConfigManager | None = None,
    config_group_name: str = "config",
    maintenance_group_name: str = "app",
    show_next_step: bool = False,
    ctx: typer.Context | None = None,
) -> None:
    """Initialize the declared config directory and user dotenv.

    Workspace roots are initialized separately by workspace commands; config
    setup never asks the user to choose or create a workspace.

    :param apprc: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to skip setup's optional field prompts.
    :param adopt: Whether to accept an existing unowned config directory.
    :param offer_missing: Offer setup only for missing required user settings.
    :param manager: Invocation-bound manager supplied by the config command.
    :param config_group_name: Config command group name used in guidance.
    :param maintenance_group_name: Mounted maintenance group used in guidance.
    :param show_next_step: Whether to print the declaration's next step.
    :param ctx: Color context when invoked through a mounted command.
    :raises typer.BadParameter: If setup inputs or managed files are invalid.
    """
    if not apprc.schema.paths.config:
        raise typer.BadParameter(
            f"{apprc.schema.display_name} declares no configuration directory.",
            param_hint="setup",
        )
    active_manager = manager or apprc.manage(ResolveOptions())
    if offer_missing:
        if assume_yes or not sys.stdin.isatty():
            return
        if not _missing_required_fields(active_manager):
            return
        if not typer.confirm(
            "Set up missing required settings now?", default=False
        ):
            return
    from apprc.interfaces._terminal_console import (
        cli_console,
        cli_line,
        human_report,
    )
    from apprc.interfaces._terminal_styles import (
        PATH_STYLE,
        SUCCESS_STYLE,
        style_literals,
    )

    if human_report():
        cli_line(ctx, "1. Initializing Configuration", style="stage")
    try:
        result = active_manager.setup(adopt=adopt)
    except (OSError, ValueError) as exc:
        if isinstance(exc, AppRCDirectoryError):
            raise app_path_bad_parameter(exc) from exc
        raise typer.BadParameter(str(exc), param_hint="setup") from exc
    if not assume_yes:
        _prompt_required_fields(active_manager, ctx=ctx)
    paths = active_manager.paths
    message = setup_finish_text(
        apprc,
        paths=paths,
        user_dotenv=result.user_dotenv,
        config_group_name=config_group_name,
        maintenance_group_name=maintenance_group_name,
    )
    completion = message.split("\n", 1)[0]
    styled = {completion: SUCCESS_STYLE}
    for path in (paths.config_dir, result.user_dotenv):
        if path is not None:
            styled[str(path)] = PATH_STYLE
    cli_console(ctx).print(style_literals(message, styled))
    if show_next_step:
        _print_setup_next_step(apprc)


def _print_setup_next_step(apprc: AppRC) -> None:
    """Print the app-supplied step that follows explicit setup.

    :param apprc: Application declaration that may provide a next step.
    """
    next_step = apprc.schema.setup_next_step
    if next_step:
        typer.echo(f"\nNext step:\n  {next_step}")


def _missing_required_fields(
    manager: ConfigManager,
) -> tuple[FieldInspection, ...]:
    """Select missing user values that the shared setup implementation can save.

    :param manager: Invocation-bound configuration manager.
    :return: Active editable required fields without a supplied value or fallback.
    """
    if "user" not in manager.writable_scopes(include_workspace=False):
        return ()
    return tuple(
        item
        for item in manager.inspect(include_workspace=False).fields
        if item.active
        and not item.owner.requires_workspace
        and item.reason == "missing"
        and item.field.editable
        and item.field.required
        and not item.field.has_default()
    )


def _prompt_required_fields(
    manager: ConfigManager, *, ctx: typer.Context | None = None
) -> None:
    """Save active missing values through the same manager as other editors.

    :param manager: Manager bound to the location initialized by setup.
    """
    fields = _missing_required_fields(manager)
    if not fields:
        return
    from prompt_toolkit import prompt

    from apprc.interfaces._terminal_console import cli_line, human_report

    if human_report():
        cli_line(ctx, "2. Saving Required Settings", style="stage")
    for item in fields:
        key = item.owner.env_key(item.field.name)
        cli_line(ctx, item.issue or "", style="warning")
        while True:
            try:
                value = prompt(
                    f"{item.field.title or key}: ",
                    is_password=item.field.secret,
                )
            except (EOFError, KeyboardInterrupt) as exc:
                raise typer.Exit(code=1) from exc
            try:
                plan = manager.plan_update(key, value, scope="user")
                preview = manager.preview_edit(plan)
                current = next(
                    field
                    for field in preview.fields
                    if field.owner.env_key(field.field.name) == key
                )
                if current.issue is not None:
                    cli_line(ctx, current.issue, style="error", error=True)
                    continue
                manager.apply_edit(plan)
                break
            except (OSError, ValueError) as exc:
                cli_line(
                    ctx,
                    f"Could not save {key}. Check its value and private file permissions."
                    if item.field.secret
                    else str(exc),
                    style="error",
                    error=True,
                )
