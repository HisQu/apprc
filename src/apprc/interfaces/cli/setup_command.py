"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli._interactive_setup import (
    prompt_apprc_setup_dir,
    prompt_storage_setup_root,
)
from apprc.user_files.app_home.locations import normalize_apprc_dir
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupFlow
from apprc.user_files.setup.text import shell_export_commands
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty
from apprc.interfaces._terminal_styles import (
    PATH_STYLE,
    style_literals,
)


def run_config_setup(
    kit: AppConfigKit,
    *,
    assume_yes: bool = False,
    apprc_dir: str | Path | None = None,
    storage_root: str | Path | None = None,
    config_group_name: str = "config",
) -> None:
    """Configure files required by the AppRC declaration.

    :param kit: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to run without prompts.
    :param apprc_dir: Optional AppRC directory for this setup run.
    :param storage_root: Optional active storage root.
    :param config_group_name: Config command group name used in generated
        guidance.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If setup inputs are invalid.
    """
    if not kit.spec.uses_managed_files():
        raise typer.BadParameter(
            f"{kit.spec.display_name} declares no managed files.",
            param_hint="setup",
        )
    selected_apprc_dir = _select_apprc_dir(
        kit,
        apprc_dir=apprc_dir,
        assume_yes=assume_yes,
    )
    if not kit.spec.uses_storage():
        if storage_root is not None:
            raise typer.BadParameter(
                f"{kit.spec.display_name} does not use AppRC storage.",
                param_hint="--storage-root",
            )
        try:
            result = ConfigSetupFlow(kit).run_user_dotenv_setup(
                apprc_dir=selected_apprc_dir
            )
        except ConfigSetupError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        _print_app_setup(
            kit,
            apprc_dir=result.apprc_dir,
            user_dotenv=result.user_dotenv,
            config_group_name=config_group_name,
        )
        return

    root = _select_storage_root(
        kit,
        apprc_dir=selected_apprc_dir,
        storage_root=storage_root,
        assume_yes=assume_yes,
    )
    try:
        result = ConfigSetupFlow(kit).run_storage_setup(
            root,
            apprc_dir=selected_apprc_dir,
        )
    except ConfigSetupError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint or "--storage-root",
        ) from exc
    _print_storage_setup(
        kit,
        apprc_dir=result.apprc_dir,
        storage_root=result.active_storage_root,
        storage_dotenv=result.storage_dotenv,
        app_path=result.user_dotenv,
        config_group_name=config_group_name,
    )


def _select_apprc_dir(
    kit: AppConfigKit,
    *,
    apprc_dir: str | Path | None,
    assume_yes: bool,
) -> Path:
    """Return the AppRC directory approved for this setup run.

    :param kit: Application declaration whose files will be created.
    :param apprc_dir: Optional command-provided directory.
    :param assume_yes: Whether to accept the resolved suggestion directly.
    :return: Absolute user-expanded directory path.
    :raises typer.Exit: If interactive selection is canceled.
    """
    selected = apprc_dir
    suggested = kit.spec.apprc_dir()
    if selected is None:
        if assume_yes:
            selected = suggested
        else:
            selected = prompt_apprc_setup_dir(suggested=suggested)
            if selected is None:
                typer.echo("No files were changed.", err=True)
                raise typer.Exit(code=1)
    return normalize_apprc_dir(selected)


def _select_storage_root(
    kit: AppConfigKit,
    *,
    apprc_dir: Path,
    storage_root: str | Path | None,
    assume_yes: bool,
) -> Path:
    """Return the storage root selected for setup before creation.

    :param kit: Application config facade.
    :param apprc_dir: AppRC directory selected earlier in this setup run.
    :param storage_root: Optional CLI-provided root.
    :param assume_yes: Whether setup may run without prompts.
    :return: Normalized storage root.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If the path cannot be used as a directory.
    """
    selected = storage_root
    suggested = apprc_dir / "storage"
    proc_env = {**os.environ, kit.spec.apprc_dir_env_key: str(apprc_dir)}
    registry_path = kit.spec.preferred_apprc_toml_path(proc_env)
    try:
        registry = load_storage_registry_or_empty(registry_path)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--apprc-dir") from exc
    if registry.selected_storage is not None:
        suggested = registry.selected(registry.selected_storage).root
    if selected is None:
        if assume_yes:
            selected = suggested
        else:
            selected = prompt_storage_setup_root(suggested=suggested)
            if selected is None:
                typer.echo("No files were changed.", err=True)
                raise typer.Exit(code=1)
    if Path(selected) == Path("."):
        raise typer.BadParameter(
            "--storage-root must not be empty or the current directory.",
            param_hint="--storage-root",
        )
    try:
        root = normalize_storage_root_path(selected)
    except StorageRootPathError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="--storage-root",
        ) from exc
    if root.exists() and not root.is_dir():
        raise typer.BadParameter(
            f"Storage root exists but is not a directory: {root}",
            param_hint="--storage-root",
        )
    if root.exists() and any(root.iterdir()) and not assume_yes:
        if not typer.confirm(
            f"Reuse non-empty storage root for {kit.spec.display_name}?"
        ):
            raise typer.Exit(code=1)
    return root


def _print_app_setup(
    kit: AppConfigKit,
    *,
    apprc_dir: Path,
    user_dotenv: Path | None,
    config_group_name: str,
) -> None:
    """Print setup completion for the per-user dotenv file."""
    if user_dotenv is None:
        raise typer.BadParameter("User dotenv setup returned no dotenv file.")
    lines = [
        f"{kit.spec.display_name} user dotenv is ready.",
        "",
        f"apprc_dir: {apprc_dir}",
        f"user_dotenv: {user_dotenv}",
    ]
    lines.extend(shell_export_commands(kit, apprc_dir))
    lines.extend(
        (
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} {config_group_name} doctor",
        )
    )
    text = "\n".join(lines)
    Console(soft_wrap=True).print(
        style_literals(
            text,
            {
                str(apprc_dir): PATH_STYLE,
                str(user_dotenv): PATH_STYLE,
            },
        )
    )


def _print_storage_setup(
    kit: AppConfigKit,
    *,
    apprc_dir: Path,
    storage_root: Path | None,
    storage_dotenv: Path | None,
    app_path: Path | None,
    config_group_name: str,
) -> None:
    """Print setup completion for storage-capable integrations."""
    if storage_root is None or storage_dotenv is None:
        raise typer.BadParameter("Storage setup did not create a dotenv file.")
    lines = [
        f"{kit.spec.display_name} AppRC files are ready.",
        "",
        f"apprc_dir: {apprc_dir}",
        f"storage_root: {storage_root}",
        f"storage_dotenv: {storage_dotenv}",
    ]
    if app_path is not None:
        lines.append(f"user_dotenv: {app_path}")
    lines.extend(("", "selected_storage: default"))
    lines.extend(shell_export_commands(kit, apprc_dir))
    lines.extend(
        (
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} {config_group_name} doctor",
        )
    )
    paths = {
        str(apprc_dir): PATH_STYLE,
        str(storage_root): PATH_STYLE,
        str(storage_dotenv): PATH_STYLE,
    }
    if app_path is not None:
        paths[str(app_path)] = PATH_STYLE
    Console(soft_wrap=True).print(
        style_literals(
            "\n".join(lines),
            {
                **paths,
            },
        )
    )
