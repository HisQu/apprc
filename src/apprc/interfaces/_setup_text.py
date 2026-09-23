"""User-facing setup copy for AppRC declarations."""

from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

# == Standard Library ========================
import shlex
from pathlib import Path

# == Internal ================================
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def setup_overview_text(apprc: AppRC) -> str:
    """Return a short summary of the declared setup route.

    :param apprc: Application config facade.
    :return: Human-facing setup overview.
    """
    if apprc.schema.uses_storage():
        user_text = (
            "creates apprc.user.env and "
            if apprc.schema.uses_user_dotenv()
            else ""
        )
        return (
            f"{apprc.schema.display_name} setup {user_text}registers a storage "
            "named default in apprc.toml."
        )
    if apprc.schema.uses_user_dotenv():
        return f"{apprc.schema.display_name} setup creates an empty apprc.user.env."
    return f"{apprc.schema.display_name} declares no managed files."


def setup_finish_text(
    apprc: AppRC,
    *,
    apprc_dir: Path | None = None,
    storage_root: Path | None = None,
    storage_dotenv: Path | None = None,
    user_dotenv: Path | None = None,
    previous_apprc_dir: Path | None = None,
    config_group_name: str = "config",
) -> str:
    """Return setup completion copy for initialized managed files.

    :param apprc: Application config facade.
    :param apprc_dir: AppRC directory selected for this setup run.
    :param storage_root: Storage root selected by setup, if any.
    :param storage_dotenv: Storage dotenv file initialized by setup, if any.
    :param user_dotenv: Per-user dotenv file initialized by setup, if any.
    :param previous_apprc_dir: Directory resolved before an interactive
        process-local override.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Human-facing setup completion text.
    """
    lines = [f"{apprc.schema.display_name} AppRC setup complete.", ""]
    if apprc_dir is not None:
        lines.append(f"apprc_dir: {apprc_dir}")
    if user_dotenv is not None:
        lines.append(f"user_dotenv: {user_dotenv}")
    if storage_root is not None:
        lines.append(f"storage_root: {storage_root}")
    if storage_dotenv is not None:
        lines.append(f"storage_dotenv: {storage_dotenv}")
    if apprc_dir is not None:
        lines.extend(
            shell_export_commands(
                apprc,
                apprc_dir,
                previous_apprc_dir=previous_apprc_dir,
            )
        )
    lines.extend(
        (
            "",
            "Then verify:",
            *verification_commands(
                apprc,
                config_group_name=config_group_name,
            ),
        )
    )
    return "\n".join(lines)


def shell_export_commands(
    apprc: AppRC,
    apprc_dir: Path,
    *,
    previous_apprc_dir: Path | None = None,
) -> list[str]:
    """Return shell assignments needed for a command-only directory choice.

    :param apprc: Application config facade.
    :param apprc_dir: AppRC directory selected by setup.
    :param previous_apprc_dir: Directory resolved before a process-local
        override, when the caller has already applied one.
    :return: Shell command lines.
    """
    selected = apprc_dir.expanduser().absolute()
    previous = previous_apprc_dir or AppFiles(apprc.schema).apprc_dir()
    if selected == previous.expanduser().absolute():
        return []
    key = apprc.schema.apprc_dir_env_key
    value = str(selected)
    powershell_value = value.replace("'", "''")
    return [
        "",
        "The setup command cannot remember this custom directory. Set this "
        "environment variable before future runs:",
        f"  POSIX: export {key}={shlex.quote(value)}",
        f"  PowerShell: $env:{key} = '{powershell_value}'",
        f'  cmd.exe: set "{key}={value}"',
    ]


def dotenv_assignment_commands(
    apprc: AppRC,
    storage_root: Path | None,
) -> list[str]:
    """Return dotenv assignment lines needed after setup.

    :param apprc: Application config facade.
    :param storage_root: Storage root selected by setup, if any.
    :return: Dotenv assignment lines.
    """
    del apprc, storage_root
    return []


def verification_commands(
    apprc: AppRC,
    *,
    config_group_name: str = "config",
) -> list[str]:
    """Return commands that inspect the resulting setup.

    :param apprc: Application config facade.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Command lines.
    """
    return [
        f"  {apprc.schema.config_command_name()} {config_group_name} paths",
        f"  {apprc.schema.config_command_name()} {config_group_name} doctor",
    ]


def storage_root_reuse_text(apprc: AppRC, storage_root: Path) -> str:
    """Return warning copy for a non-empty storage root.

    :param apprc: Application config facade.
    :param storage_root: Existing storage directory.
    :return: Human-facing reuse warning.
    """
    return (
        f"{apprc.schema.display_name} will reuse non-empty storage root "
        f"{storage_root} without deleting existing files."
    )
