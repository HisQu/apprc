"""Read-only guards used after acquiring stable resource write locks."""

from __future__ import annotations

from pathlib import Path

from apprc.definition.installation import (
    InstallationError,
    InstallationSnapshot,
    OperationContext,
)
from apprc.user_files.installation.discovery import inspect_installation


def validate_snapshot(
    snapshot: InstallationSnapshot,
    *,
    app_id: str,
    context: OperationContext | None = None,
) -> None:
    """Reject old consumers after namespace replacement or incomplete mutation.

    :param snapshot: Invocation's original discovery, not freshly resolved paths.
    :param app_id: Expected host application identity.
    :param context: Explicit authorization for a matching pending operation.
    """
    inspection = inspect_installation(snapshot.directory, app_id=app_id)
    actual = inspection.snapshot
    if actual.generation_id != snapshot.generation_id:
        raise InstallationError(
            "Installation generation changed; restart the application."
        )
    if context is not None:
        record = inspection.record
        if (
            record is None
            or record.operation is None
            or context.directory != inspection.directory
            or context.operation_id != record.operation.operation_id
            or context.generation_id != record.generation_id
            or context.placement != record.operation.placement
        ):
            raise InstallationError("Pending operation authorization is stale.")
    else:
        inspection.require_usable()
        if actual.revision != snapshot.revision:
            raise InstallationError(
                "Installation authority changed; capture a fresh invocation."
            )


def check_native_appdata_container(container: Path, *, app_id: str) -> None:
    """Reject silent Linux parent-to-child cutover before resolving a fresh store.

    :param container: Native application data parent, never a purge target.
    :param app_id: Expected owner identity.
    """
    from apprc.user_files.app_home.locations import assert_no_links
    from apprc.user_files.app_home.ownership import inspect_ownership

    assert_no_links(container)
    if not container.exists():
        return
    if not container.is_dir():
        raise InstallationError(
            "Native application data container is not a directory."
        )
    marker = container / ".apprc-owner.json"
    if marker.exists() or marker.is_symlink():
        inspect_ownership(container, app_id, "appdata")
        raise InstallationError(
            "Legacy native appdata requires explicit installation migrate; no empty store was selected."
        )
    unknown = [
        entry
        for entry in container.iterdir()
        if entry.name not in {"installation", "appdata"}
    ]
    if unknown:
        raise InstallationError(
            "Nonempty native appdata container requires project-owned migration or adoption."
        )
    child = container / "appdata"
    if (
        child.exists()
        and inspect_ownership(child, app_id, "appdata") != "owned"
        and any(child.iterdir())
    ):
        raise InstallationError(
            "Native appdata child is nonempty and unowned; inspect or adopt explicitly."
        )
