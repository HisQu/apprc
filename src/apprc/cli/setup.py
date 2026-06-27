"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console
from rich.text import Text

# == Internal ================================
from apprc.cli.errors import config_home_bad_parameter
from apprc.runtime_config.app_spec import StorageMode
from apprc.runtime_config.config_home import ConfigHomeError
from apprc.runtime_config.kit import AppConfigKit
import apprc.runtime_config.setup.flow as setup_flow
import apprc.runtime_config.setup.text as setup_text
from apprc.runtime_config.terminal_styles import (
    ENV_KEY_STYLE,
    MISSING_STYLE,
    PATH_STYLE,
    style_literals,
)
from apprc.runtime_config.tui.setup import ConfigSetupApp


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
    :param existing_action: Optional action for an existing AppRC TOML file.
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
    if kit.spec.storage_mode == StorageMode.DISABLED:
        if has_setup_options or multi_storage:
            raise typer.BadParameter(
                f"{kit.spec.display_name} does not use AppRC storage.",
                param_hint="storage",
            )
        try:
            _print_global_setup_finish(kit)
        except (ConfigHomeError, OSError) as exc:
            raise config_home_bad_parameter(exc) from exc
        return

    if not assume_yes:
        try:
            result = ConfigSetupApp(kit=kit).run()
        except (ConfigHomeError, OSError) as exc:
            raise config_home_bad_parameter(exc) from exc
        if result is None:
            raise typer.Exit(code=1)
        return

    flow = setup_flow.ConfigSetupFlow(kit)
    try:
        if multi_storage:
            registered_name = (
                flow.default_storage_name()
                if storage_name is None
                else storage_name
            )
            setup_result = flow.prepare_storage_registry(
                apprc_dir=apprc_dir,
                existing_action=existing_action,
                replace_existing_file=True,
            )
            root = flow.prepare_storage_root(
                storage_root=storage_root,
                storage_name=registered_name,
                allow_non_empty_storage=True,
            )
            result = flow.ensure_registered_storage(
                setup_result.registry,
                storage_root=root,
                storage_name=registered_name,
            )
        else:
            kit.spec.ensure_config_home()
            root = flow.prepare_storage_root(
                storage_root=storage_root,
                storage_name=None,
                allow_non_empty_storage=True,
            )
            result = flow.ensure_single_storage(
                storage_root=root,
            )
    except (ConfigHomeError, OSError) as exc:
        raise config_home_bad_parameter(exc) from exc
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
    """
    console = Console(soft_wrap=True)
    console.print(_style_setup_finish_text(kit, result))


def _print_global_setup_finish(kit: AppConfigKit) -> None:
    """Print storage-free setup guidance for AppRC-managed files.

    :param kit: Application config facade.
    """
    paths = kit.spec.ensure_config_home()
    text = "\n".join(
        (
            f"{kit.spec.display_name} AppRC config files are ready.",
            "",
            f"Config home: {paths.root}",
            f"Global env: {paths.global_env}",
            f"AppRC TOML: {paths.apprc_toml}",
            "",
            "AppRC owns the global env and AppRC TOML files. Host "
            "applications own their own structured config files in the same "
            "config home.",
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} config doctor",
            f"  {kit.spec.config_command_name()} config show",
        )
    )
    console = Console(soft_wrap=True)
    console.print(
        style_literals(
            text,
            {
                str(paths.root): PATH_STYLE,
                str(paths.global_env): PATH_STYLE,
                str(paths.apprc_toml): PATH_STYLE,
            },
        )
    )


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
        kit.spec.apprc_toml_env_key: ENV_KEY_STYLE,
        **paths,
    }
    if kit.spec.storage_env_key is not None:
        styles[kit.spec.storage_env_key] = ENV_KEY_STYLE
    return style_literals(
        setup_text.setup_finish_text(
            kit,
            result.registry,
            result.active_storage_root,
        ),
        styles,
    )
