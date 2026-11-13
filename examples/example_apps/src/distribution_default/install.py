"""Default install composition using the maintained lifecycle transaction."""

from __future__ import annotations

from pathlib import Path

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    RuntimeSlot,
)
from apprc.distribution.runtime.installation import install_application
from apprc.services.installation import InstallationManager


def install_default(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: RuntimeSlot,
    placement: InstallationPlacement,
    *,
    command_name: str,
    project_archive: Path,
    manager_executable: Path,
    uv: Path,
    command_directory: Path | None = None,
    assume_yes: bool = False,
) -> InstallationInspection:
    """Install an embedded project snapshot through the shared transaction.

    :param manager: Bound installation/resource authority.
    :param identity: Declared application identity.
    :param runtime: Exact immutable managed candidate.
    :param placement: Selected owned resource locations.
    :param command_name: Primary declared console command.
    :param project_archive: Verified committed project snapshot.
    :param manager_executable: Native setup bytes to publish as the stable manager.
    :param uv: Absolute manager-owned uv executable.
    :param command_directory: Optional global command directory already on PATH.
    :param assume_yes: Accept an explicit mode/replacement confirmation.
    :return: Activated installation inspection.
    """
    return install_application(
        manager,
        identity,
        runtime,
        placement,
        command_name=command_name,
        project_archive=project_archive,
        manager_executable=manager_executable,
        uv=uv,
        command_directory=command_directory,
        assume_yes=assume_yes,
    )
