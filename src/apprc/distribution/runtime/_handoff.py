"""Shared uninstall handoff identity and containment primitives."""

from __future__ import annotations

import os
from pathlib import Path

from apprc.definition.installation import (
    InstallationError,
    InstallationRecord,
    RuntimeSlot,
    UninstallPlan,
)
from apprc.distribution.runtime._process_waiter import (
    process_start_token,
)

from apprc.user_files.installation.planning import resource_roots


def handoff_removal_roots(
    plan: UninstallPlan, record: InstallationRecord
) -> tuple[Path, ...]:
    """Return only paths the pending uninstall can actually delete.

    Editable checkouts and their environments are never removal roots. Managed
    slots enter only by their active or explicitly retiring record IDs.
    """
    slot_ids = set(record.retiring_runtime_ids)
    if isinstance(record.active_runtime, RuntimeSlot):
        slot_ids.add(record.active_runtime.slot_id)
    roots = [plan.directory / "runtimes" / str(slot_id) for slot_id in slot_ids]
    for output in record.owned_outputs:
        if output.kind in {"shortcut", "command"}:
            path = Path(output.path)
            if path.is_absolute():
                roots.append(Path(os.path.normpath(os.fspath(path))))
    roots.extend(
        entry.path
        for entry in plan.inventory.entries
        if plan.complete or entry.resource is None
    )
    if plan.complete:
        roots.append(plan.directory)
        retained_roots = {
            item.path.resolve() for item in plan.inventory.retained
        }
        roots.extend(
            path
            for kind, path in resource_roots(plan.placement)
            if kind in plan.categories and path.resolve() not in retained_roots
        )
    return tuple(dict.fromkeys(roots))


def assert_outside_removal(path: Path, roots: tuple[Path, ...]) -> None:
    """Reject a location equal to or nested in an actual delete target."""
    lexical = Path(os.path.normpath(os.fspath(path.expanduser().absolute())))
    resolved = lexical.resolve()
    if any(
        candidate == root or candidate.is_relative_to(root)
        for candidate in (lexical, resolved)
        for root in roots
    ):
        raise InstallationError(
            "Uninstall handoff location overlaps a removal target."
        )


