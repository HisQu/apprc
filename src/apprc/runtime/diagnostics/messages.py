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
        f"Set {storage_key} to a registered name or path, pass "
        "--storage NAME_OR_PATH, or "
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
    storage_count: int,
    selector_error: bool,
) -> list[str]:
    """Return recovery steps tailored to one doctor status.

    :param kit: Application config facade.
    :param status: Public readiness status.
    :param config_group_name: Config command group name used in generated
        guidance.
    :param storage_count: Number of registered live storages.
    :param selector_error: Whether an explicit selector failed to resolve.
    :return: Ordered actions for human and JSON output.
    """
    if status == ConfigDoctorStatus.RUNNABLE:
        return []
    if status == ConfigDoctorStatus.STORAGE_NOT_SELECTED:
        selection_step = (
            config_command_text(
                kit,
                "storage select NAME",
                config_group_name=config_group_name,
            )
            if storage_count
            else config_command_text(
                kit,
                "setup --yes --storage-root /absolute/path/to/storage-root",
                config_group_name=config_group_name,
            )
        )
        return [
            selection_step,
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
    if selector_error:
        return [
            "Fix or unset the invalid storage selector shown above.",
            config_command_text(
                kit, "storage list", config_group_name=config_group_name
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


def _missing_storage_issue(
    kit: "AppConfigKit",
    *,
    selector_key: str,
    config_group_name: str,
) -> str:
    """Return one readable issue for a missing storage selection.

    :param kit: Application config facade.
    :param selector_key: Optional environment selector key.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Human-facing doctor issue.
    """
    return (
        f"No storage is selected for {kit.spec.display_name}. Run "
        f"{config_command_text(kit, 'setup', config_group_name=config_group_name)} "
        "to create one, choose a registered default with "
        f"{config_command_text(kit, 'storage select NAME', config_group_name=config_group_name)}, "
        f"pass --storage NAME_OR_PATH, or set {selector_key}=NAME_OR_PATH."
    )
