"""Program-only and recorded application-hook removal composition."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from apprc.definition.installation import InstallationError
from apprc.distribution.runtime.controllers import (
    UninstallPreparation,
    prepare_uninstall,
    start_uninstall_handoff,
)


def uninstall_package_only(
    directory: Path, *, original_pid: int | None = None
) -> NoReturn:
    """Remove the installed tool while retaining application data and configuration."""
    preparation = prepare_uninstall(directory)
    if preparation.plan is None or not preparation.can_execute:
        raise InstallationError("Removal preview is not safe to execute.")
    handoff = start_uninstall_handoff(
        preparation.plan, original_pid=original_pid
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)


def uninstall_with_project_cleanup(
    preparation: UninstallPreparation,
    *,
    original_pid: int | None = None,
) -> NoReturn:
    """Remove through recorded runtime hooks, without serializing callbacks.

    :param preparation: Exact removal preview accepted by the caller.
    :param original_pid: Initiating CLI or launcher PID.
    """
    if preparation.plan is None or not preparation.can_execute:
        raise InstallationError("Removal preview is not safe to execute.")
    handoff = start_uninstall_handoff(
        preparation.plan, original_pid=original_pid
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)
