"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console
from rich.text import Text

# == Internal ================================
from apprc.cli.doctor import print_config_doctor
from apprc.config.diagnostics import build_config_doctor_payload
from apprc.config.kit import AppConfigKit
import apprc.config.setup.flow as setup_flow
import apprc.config.setup.text as setup_text
from apprc.config.tui.setup import ConfigSetupApp
from apprc.config.tui.styles import (
    ENV_KEY_STYLE,
    MISSING_STYLE,
    PATH_STYLE,
    style_literals,
)


def run_config_setup(
    kit: AppConfigKit,
    *,
    assume_yes: bool = False,
    apprc_dir: Path | None = None,
    storage_root: Path | None = None,
    storage_name: str | None = None,
    multi_storage: bool = False,
    existing_action: setup_flow.ExistingSetupAction | None = None,
) -> None:
    """Run the Textual setup wizard or a non-interactive setup command.

    :param kit: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to run without opening the Textual wizard.
    :param apprc_dir: Optional AppRC directory for non-interactive setup.
    :param storage_root: Optional active storage root.
    :param storage_name: Optional selector for multi-storage registration.
    :param multi_storage: Whether setup should register the active storage.
    :param existing_action: Optional action for an existing registry.
    :raises typer.Exit: If the user cancels or setup diagnostics fail.
    :raises typer.BadParameter: If setup inputs are invalid.
    """
    has_setup_options = any(
        option is not None
        for option in (
            apprc_dir,
            storage_root,
            storage_name,
            existing_action,
        )
    )
    if (has_setup_options or multi_storage) and not assume_yes:
        raise typer.BadParameter(
            "Setup options run non-interactively and require --yes.",
            param_hint="--yes",
        )
    if storage_name is not None and not multi_storage:
        raise typer.BadParameter(
            "--name is only used with --multi-storage.",
            param_hint="--multi-storage",
        )
    if apprc_dir is not None and not multi_storage:
        raise typer.BadParameter(
            "--apprc-dir is only used with --multi-storage.",
            param_hint="--multi-storage",
        )
    if existing_action is not None and not multi_storage:
        raise typer.BadParameter(
            "--existing-action is only used with --multi-storage.",
            param_hint="--multi-storage",
        )

    if not assume_yes:
        result = ConfigSetupApp(kit=kit).run()
        if result is None:
            raise typer.Exit(code=1)
        _raise_if_doctor_failed(kit, result)
        return

    try:
        if multi_storage:
            setup_result = setup_flow.prepare_setup_registry(
                kit,
                apprc_dir=apprc_dir,
                existing_action=existing_action,
                replace_existing_file=True,
            )
            result = setup_flow.ensure_registered_storage(
                kit,
                setup_result.registry,
                storage_root=storage_root,
                storage_name=storage_name,
                allow_non_empty_storage=True,
            )
        else:
            result = setup_flow.ensure_single_storage(
                kit,
                storage_root=storage_root,
                allow_non_empty_storage=True,
            )
    except setup_flow.ConfigSetupError as exc:
        _raise_setup_error(exc)
    _print_setup_finish(kit, result)


def _print_setup_finish(
    kit: AppConfigKit,
    result: setup_flow.ConfigSetupResult,
) -> None:
    """Print environment handoff text after non-interactive setup.

    :param kit: Application config facade.
    :param result: Setup files and active storage selected by setup.
    :raises typer.Exit: If doctor reports that setup is incomplete.
    """
    payload = build_config_doctor_payload(
        kit,
        storage=result.registered_storage_name,
        storage_root=result.active_storage_root,
        apprc_toml_path=(
            result.registry.path if result.registry is not None else None
        ),
    )
    console = Console(soft_wrap=True)
    console.print(_style_setup_finish_text(kit, result))
    if not payload["ok"]:
        typer.echo("")
        print_config_doctor(kit, payload)
        raise typer.Exit(code=1)


def _raise_if_doctor_failed(
    kit: AppConfigKit,
    result: setup_flow.ConfigSetupResult,
) -> None:
    """Exit when the setup wizard completed but diagnostics still fail.

    :param kit: Application config facade.
    :param result: Setup files and active storage selected by setup.
    :raises typer.Exit: If doctor reports that setup is incomplete.
    """
    payload = build_config_doctor_payload(
        kit,
        storage=result.registered_storage_name,
        storage_root=result.active_storage_root,
        apprc_toml_path=(
            result.registry.path if result.registry is not None else None
        ),
    )
    if not payload["ok"]:
        raise typer.Exit(code=1)


def _raise_setup_error(exc: setup_flow.ConfigSetupError) -> None:
    """Convert setup workflow errors to Typer's CLI errors.

    :param exc: Setup-layer error with optional CLI context.
    :raises typer.Exit: For setup refusals that should keep exit code ``1``.
    :raises typer.BadParameter: For invalid command input.
    """
    exit_code = getattr(exc, "exit_code", None)
    if exit_code is not None:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exit_code)
    raise typer.BadParameter(str(exc), param_hint=exc.param_hint) from exc


def _style_setup_finish_text(
    kit: AppConfigKit,
    result: setup_flow.ConfigSetupResult,
) -> Text:
    """Return styled setup completion text for the CLI.

    :param kit: Application config facade.
    :param result: Setup files and active storage selected by setup.
    :return: Rich text with semantic setup spans.
    """
    paths = {
        str(result.active_storage_root): PATH_STYLE,
    }
    if result.registry is not None:
        paths.update(
            {
                str(result.registry.path): PATH_STYLE,
                str(result.registry.path.expanduser().resolve()): PATH_STYLE,
            }
        )
    styles = {
        "Shell:": "bold",
        "Or Dotenv:": "bold",
        "env_not_set": MISSING_STYLE,
        kit.apprc_toml_env_key(): ENV_KEY_STYLE,
        kit.spec.storage_env_key: ENV_KEY_STYLE,
        **paths,
    }
    return style_literals(
        setup_text.setup_finish_text(
            kit,
            result.registry,
            result.active_storage_root,
        ),
        styles,
    )
