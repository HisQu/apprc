"""Human-readable messages for AppRC configuration diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def config_command_text(
    apprc: "AppRC",
    action: str,
    *,
    config_group_name: str = "config",
) -> str:
    """Return one display command for this app's config group.

    :param apprc: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :param config_group_name: Mounted config command name.
    :return: Human-readable command text.
    """
    return f"{apprc.schema.config_command_name()} {config_group_name} {action}"


def config_setup_message(
    apprc: "AppRC",
    *,
    config_group_name: str = "config",
) -> str:
    """Return read-only guidance when a required configuration is absent.

    :param apprc: Application declaration.
    :param config_group_name: Mounted config command name.
    :return: Human-readable inspection and setup commands.
    """
    inspect = config_command_text(
        apprc, "doctor", config_group_name=config_group_name
    )
    if apprc.schema.uses_user_dotenv():
        return (
            f"{apprc.schema.display_name} user configuration is not initialized. "
            "Run the explicit setup command, then inspect the result:\n"
            f"  {config_command_text(apprc, 'setup', config_group_name=config_group_name)}\n"
            f"  {inspect}"
        )
    return (
        f"{apprc.schema.display_name} reads configuration from its declared "
        "defaults, explicit env files, and shell environment. Inspect the "
        f"current configuration with:\n  {inspect}"
    )
