"""User-facing setup copy for AppRC declarations."""

from __future__ import annotations

# == Standard Library ========================
import shlex
from pathlib import Path

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit


def setup_overview_text(kit: AppConfigKit) -> str:
    """Return a short summary of the declared setup route.

    :param kit: Application config facade.
    :return: Human-facing setup overview.
    """
    if kit.spec.uses_storage():
        user_text = (
            "creates apprc.user.env and " if kit.spec.uses_user_dotenv() else ""
        )
        return (
            f"{kit.spec.display_name} setup {user_text}registers a storage "
            "named default in apprc.toml."
        )
    if kit.spec.uses_user_dotenv():
        return f"{kit.spec.display_name} setup creates an empty apprc.user.env."
    return f"{kit.spec.display_name} declares no managed files."


def setup_finish_text(
    kit: AppConfigKit,
    *,
    apprc_dir: Path | None = None,
    storage_root: Path | None = None,
    storage_dotenv: Path | None = None,
    user_dotenv: Path | None = None,
    previous_apprc_dir: Path | None = None,
    config_group_name: str = "config",
) -> str:
    """Return setup completion copy for initialized managed files.

    :param kit: Application config facade.
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
    lines = [f"{kit.spec.display_name} AppRC setup complete.", ""]
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
                kit,
                apprc_dir,
                previous_apprc_dir=previous_apprc_dir,
            )
        )
    lines.extend(
        (
            "",
            "Then verify:",
            *verification_commands(
                kit,
                config_group_name=config_group_name,
            ),
        )
    )
    return "\n".join(lines)


def shell_export_commands(
    kit: AppConfigKit,
    apprc_dir: Path,
    *,
    previous_apprc_dir: Path | None = None,
) -> list[str]:
    """Return shell assignments needed for a command-only directory choice.

    :param kit: Application config facade.
    :param apprc_dir: AppRC directory selected by setup.
    :param previous_apprc_dir: Directory resolved before a process-local
        override, when the caller has already applied one.
    :return: Shell command lines.
    """
    selected = apprc_dir.expanduser().absolute()
    previous = previous_apprc_dir or kit.spec.apprc_dir()
    if selected == previous.expanduser().absolute():
        return []
    key = kit.spec.apprc_dir_env_key
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
    kit: AppConfigKit,
    storage_root: Path | None,
) -> list[str]:
    """Return dotenv assignment lines needed after setup.

    :param kit: Application config facade.
    :param storage_root: Storage root selected by setup, if any.
    :return: Dotenv assignment lines.
    """
    del kit, storage_root
    return []


def verification_commands(
    kit: AppConfigKit,
    *,
    config_group_name: str = "config",
) -> list[str]:
    """Return commands that inspect the resulting setup.

    :param kit: Application config facade.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Command lines.
    """
    return [
        f"  {kit.spec.config_command_name()} {config_group_name} paths",
        f"  {kit.spec.config_command_name()} {config_group_name} doctor",
    ]


def storage_root_reuse_text(kit: AppConfigKit, storage_root: Path) -> str:
    """Return warning copy for a non-empty storage root.

    :param kit: Application config facade.
    :param storage_root: Existing storage directory.
    :return: Human-facing reuse warning.
    """
    return (
        f"{kit.spec.display_name} will reuse non-empty storage root "
        f"{storage_root} without deleting existing files."
    )
