"""Human-readable messages for AppRC diagnostics."""

from __future__ import annotations

# == Standard Library ========================
from typing import TYPE_CHECKING

# == Internal ================================
from apprc.runtime.diagnostics.status import ConfigDoctorStatus

if TYPE_CHECKING:
    from apprc.definition.app_config.kit import AppConfigKit


def config_command_text(
    kit: "AppConfigKit",
    action: str,
    *,
    config_group_name: str = "config",
) -> str:
    """Return one display command for this app's config group.

    :param kit: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Human-readable command text.
    """
    return f"{kit.spec.config_command_name()} {config_group_name} {action}"


def config_setup_message(
    kit: "AppConfigKit",
    *,
    config_group_name: str = "config",
) -> str:
    """Return setup text shown when runtime storage is missing."""
    if not kit.spec.uses_storage():
        return (
            f"{kit.spec.display_name} can run from packaged defaults, explicit "
            "env files, and shell environment variables.\n\n"
            "Inspect the current layer state:\n"
            f"  {config_command_text(kit, 'paths', config_group_name=config_group_name)}\n"
            f"  {config_command_text(kit, 'doctor', config_group_name=config_group_name)}"
        )
    storage_key = kit.spec.require_storage_selector_env_key()
    return (
        f"No active {kit.spec.display_name} storage is selected.\n\n"
        f"Set {storage_key} to a registered name, pass --storage NAME, or "
        "select a default in apprc.toml.\n"
        "For guided setup:\n"
        f"  {config_command_text(kit, 'setup --yes --storage-root /absolute/path/to/storage-root', config_group_name=config_group_name)}\n\n"
        "Then inspect the setup:\n"
        f"  {config_command_text(kit, 'paths', config_group_name=config_group_name)}\n"
        f"  {config_command_text(kit, 'doctor', config_group_name=config_group_name)}"
    )


def _doctor_next_steps(
    kit: "AppConfigKit",
    status: ConfigDoctorStatus,
    *,
    config_group_name: str,
) -> list[str]:
    """Return recovery steps tailored to one doctor status.

    :param kit: Application config facade.
    :param status: Public readiness status.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Ordered actions for human and JSON output.
    """
    if status == ConfigDoctorStatus.RUNNABLE:
        return []
    if status == ConfigDoctorStatus.ENV_NOT_SET:
        return [
            config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root",
                config_group_name=config_group_name,
            ),
            config_command_text(
                kit, "paths", config_group_name=config_group_name
            ),
            config_command_text(
                kit, "doctor", config_group_name=config_group_name
            ),
        ]
    if status == ConfigDoctorStatus.USER_DOTENV_NOT_READY:
        return [
            config_command_text(
                kit,
                "setup",
                config_group_name=config_group_name,
            ),
            config_command_text(
                kit, "doctor", config_group_name=config_group_name
            ),
        ]
    if status == ConfigDoctorStatus.STORAGE_REGISTRY_NOT_READY:
        return [
            "Fix AppRC TOML or create a new storage entry:",
            config_command_text(
                kit,
                "storage add NAME /absolute/path/to/storage-root",
                config_group_name=config_group_name,
            ),
            config_command_text(
                kit, "doctor", config_group_name=config_group_name
            ),
        ]
    return [
        "Ensure the selected storage root exists and contains "
        f"{kit.spec.storage_dotenv_filename}.",
        config_command_text(
            kit,
            "setup --yes --storage-root /absolute/path/to/storage-root",
            config_group_name=config_group_name,
        ),
        config_command_text(kit, "doctor", config_group_name=config_group_name),
    ]


def _missing_env_issue(
    kit: "AppConfigKit",
    missing_env_keys: list[str],
    *,
    config_group_name: str,
) -> str:
    """Return one readable issue for missing bootstrap env keys.

    :param kit: Application config facade.
    :param missing_env_keys: Required env keys absent from this process.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Human-facing doctor issue.
    """
    keys = ", ".join(missing_env_keys)
    return (
        f"No storage is selected for {kit.spec.display_name}; selector key: "
        f"{keys}. Run "
        f"{config_command_text(kit, 'setup', config_group_name=config_group_name)} "
        "to create and select one, or pass --storage NAME."
    )
