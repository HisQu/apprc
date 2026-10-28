"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
import os
import sys

# == 3rd Party ===============================
import typer
from prompt_toolkit import prompt
from rich.console import Console

# == Internal ================================
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces._setup_text import setup_finish_text
from apprc.interfaces.cli._errors import app_path_bad_parameter
from apprc.public.app_rc import AppRC
from apprc.services.manager import ConfigManager, WriteScope
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupResult


def run_config_setup(
    apprc: AppRC,
    *,
    assume_yes: bool = False,
    adopt: bool = False,
    manager: ConfigManager | None = None,
    allow_interactive_secret_repair: bool = False,
    config_group_name: str = "config",
    show_next_step: bool = False,
) -> None:
    """Initialize the declared config directory and user dotenv.

    Workspace roots are initialized separately by workspace commands; config
    setup never asks the user to choose or create a workspace.

    :param apprc: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to skip setup's optional field prompts.
    :param adopt: Whether to accept an existing unowned config directory.
    :param manager: Invocation-bound manager supplied by the config command.
    :param allow_interactive_secret_repair: Whether to offer confirmed
        permission repair for an unsafe user-secret directory.
    :param config_group_name: Config command group name used in guidance.
    :param show_next_step: Whether to print the declaration's next step.
    :raises typer.BadParameter: If setup inputs or managed files are invalid.
    """
    if not apprc.schema.paths.config:
        raise typer.BadParameter(
            f"{apprc.schema.display_name} declares no configuration directory.",
            param_hint="setup",
        )
    active_manager = manager or apprc.manage(ResolveOptions())
    try:
        result = _run_setup_with_user_secret_repair(
            active_manager,
            assume_yes=assume_yes,
            allow_interactive_secret_repair=allow_interactive_secret_repair,
            adopt=adopt,
        )
    except ConfigSetupError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint,
        ) from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, AppRCDirectoryError):
            raise app_path_bad_parameter(exc) from exc
        raise typer.BadParameter(str(exc), param_hint="setup") from exc
    if not assume_yes:
        _prompt_required_fields(active_manager)
    paths = active_manager.paths
    Console(soft_wrap=True).print(
        setup_finish_text(
            apprc,
            paths=paths,
            user_dotenv=result.user_dotenv,
            config_group_name=config_group_name,
        )
    )
    if show_next_step:
        _print_setup_next_step(apprc)


def _run_setup_with_user_secret_repair(
    manager: ConfigManager,
    *,
    assume_yes: bool,
    allow_interactive_secret_repair: bool,
    adopt: bool,
) -> ConfigSetupResult:
    """Offer one confirmed repair for an unsafe user-secret directory.

    :param manager: Manager bound to the selected AppRC path snapshot.
    :param assume_yes: Whether setup should skip its own prompts.
    :param allow_interactive_secret_repair: Whether an interactive caller
        selected setup inputs before invoking this operation.
    :param adopt: Whether setup may adopt an existing unowned config directory.
    :return: Paths initialized by setup.
    """
    try:
        return manager.setup(adopt=adopt)
    except ConfigSetupError as setup_error:
        if (
            setup_error.param_hint != "config"
            or (assume_yes and not allow_interactive_secret_repair)
            or not sys.stdin.isatty()
            or not sys.stdout.isatty()
            or not manager.schema.uses_user_dotenv()
        ):
            raise
        status = manager.secret_status("user")
        if status.issue != "The parent directory is readable by other users.":
            raise
        allowed_principals = (
            "this user, SYSTEM, and Administrators"
            if os.name == "nt"
            else "the current user"
        )
        if not typer.confirm(
            f"The user secret directory at {status.path.parent} is not "
            "private. Update safety permissions to allow access only to "
            f"{allowed_principals}, then continue setup?"
        ):
            raise
        try:
            repaired = manager.repair_secret_permissions("user")
        except (OSError, ValueError) as exc:
            raise ConfigSetupError(
                f"Could not repair user secret permissions: {exc}",
                param_hint="config",
            ) from exc
        if not repaired.available:
            issue = (
                repaired.issue or "The user secret directory is unavailable."
            )
            raise ConfigSetupError(
                f"Could not repair user secret permissions: {issue}",
                param_hint="config",
            )
        return manager.setup(adopt=adopt)


def _print_setup_next_step(apprc: AppRC) -> None:
    """Print the app-supplied step that follows explicit setup.

    :param apprc: Application declaration that may provide a next step.
    """
    next_step = apprc.schema.setup_next_step
    if next_step:
        typer.echo(f"\nNext step:\n  {next_step}")


def _prompt_required_fields(manager: ConfigManager) -> None:
    """Save active missing values through the same manager as other editors.

    :param manager: Manager bound to the location initialized by setup.
    """
    for item in manager.inspect(include_workspace=False).fields:
        if (
            not item.active
            or item.owner.requires_workspace
            or item.issue is None
            or not item.issue.startswith("Missing required setting:")
            or not item.field.editable
        ):
            continue
        key = item.owner.env_key(item.field.name)
        scopes = manager.writable_scopes(include_workspace=False)
        scope: WriteScope = (
            "workspace"
            if item.owner.requires_workspace and "workspace" in scopes
            else "user"
            if "user" in scopes
            else "workspace"
        )
        typer.echo(item.issue)
        while True:
            try:
                value = prompt(
                    f"{item.field.title or key}: ",
                    is_password=item.field.secret,
                )
            except (EOFError, KeyboardInterrupt) as exc:
                raise typer.Exit(code=1) from exc
            try:
                plan = manager.plan_update(key, value, scope=scope)
                preview = manager.preview_edit(plan)
                current = next(
                    field
                    for field in preview.fields
                    if field.owner.env_key(field.field.name) == key
                )
                if current.issue is not None:
                    typer.echo(current.issue, err=True)
                    continue
                manager.apply_edit(plan)
                break
            except (OSError, ValueError) as exc:
                typer.echo(
                    f"Could not save {key}. Check its value and private file permissions."
                    if item.field.secret
                    else str(exc),
                    err=True,
                )
