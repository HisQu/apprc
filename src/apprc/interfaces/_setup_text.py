"""User-facing setup copy for AppRC declarations."""

from __future__ import annotations

# == Standard Library ========================
import shlex
from pathlib import Path

# == Internal ================================
from typing import TYPE_CHECKING

from apprc.definition.paths import AppPaths

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def setup_overview_text(apprc: AppRC) -> str:
    """Return a short summary of the declared setup route.

    :param apprc: Application config facade.
    :return: Human-facing setup overview.
    """
    if apprc.schema.uses_user_dotenv():
        return f"{apprc.schema.display_name} setup creates apprc.user.env."
    return f"{apprc.schema.display_name} declares no user configuration files."


def setup_finish_text(
    apprc: AppRC,
    *,
    paths: AppPaths,
    user_dotenv: Path | None = None,
    config_group_name: str = "config",
) -> str:
    """Return setup completion copy for initialized user configuration.

    :param apprc: Application config facade.
    :param paths: Captured application locations for this setup invocation.
    :param user_dotenv: Per-user dotenv initialized by setup, if any.
    :param config_group_name: Config command group name used in guidance.
    :return: Human-facing setup completion text.
    """
    lines = [f"{apprc.schema.display_name} AppRC setup complete.", ""]
    if paths.config_dir is not None:
        lines.append(f"config: {paths.config_dir}")
    if user_dotenv is not None:
        lines.append(f"user_dotenv: {user_dotenv}")
    lines.extend(
        (
            "",
            "Then verify:",
            *verification_commands(apprc, config_group_name=config_group_name),
        )
    )
    return "\n".join(lines)


def bootstrap_export_commands(apprc: AppRC, paths: AppPaths) -> list[str]:
    """Return shell assignments for an invocation-only single-root layout.

    :param apprc: Application config facade.
    :param paths: Captured application locations.
    :return: Shell command lines.
    """
    if paths.source != "invocation" or paths.layout.mode != "single-root":
        return []
    root_path = paths.layout.root
    if root_path is None:
        raise ValueError("Single-root layout requires a root.")
    prefix = apprc.schema.bootstrap_env_prefix
    layout_key, root_key = f"{prefix}_LAYOUT", f"{prefix}_ROOT"
    root = str(root_path)
    powershell_value = root.replace("'", "''")
    return [
        "",
        "The setup command cannot remember this custom layout. Set these "
        "environment variables before future runs:",
        f"  POSIX: export {layout_key}=single-root {root_key}={shlex.quote(root)}",
        f"  PowerShell: $env:{layout_key} = 'single-root'; $env:{root_key} = '{powershell_value}'",
        f'  cmd.exe: set "{layout_key}=single-root" && set "{root_key}={root}"',
    ]


def verification_commands(
    apprc: AppRC,
    *,
    config_group_name: str = "config",
) -> list[str]:
    """Return commands that inspect the resulting setup.

    :param apprc: Application config facade.
    :param config_group_name: Retained config group name for integrations.
    :return: Command lines.
    """
    del config_group_name
    executable = apprc.schema.config_command_name()
    return [f"  {executable} paths --json", f"  {executable} doctor --json"]
