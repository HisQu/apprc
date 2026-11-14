"""Default package-only removal through the independent saved controller."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from apprc.definition.installation import InstallationError
from apprc.distribution.runtime.controllers import (
    UninstallPreparation,
    prepare_uninstall,
    start_uninstall_handoff,
)


def uninstall_default(
    directory: Path,
    *,
    original_pid: int | None = None,
    preparation: UninstallPreparation | None = None,
) -> NoReturn:
    """Preview program-only removal, then hand off immediately before process exit."""
    preparation = preparation or prepare_uninstall(directory)
    if not preparation.can_execute or preparation.plan is None:
        detail = "; ".join(item.message for item in preparation.diagnostics)
        raise InstallationError(
            detail or "Saved installation cannot be removed safely."
        )
    handoff = start_uninstall_handoff(
        preparation.plan, original_pid=original_pid
    )
    handoff.wait_ready()
    handoff.signal_exit()
    raise SystemExit(0)
