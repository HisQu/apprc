"""Explicit ownership-preserving migration with durable resumable authority."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    MigrationInventory,
    MigrationPlan,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision, managed_write_lock
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    _pending,
    begin_operation,
    fail_operation,
)


def validate_migration_inventory(
    inventory: MigrationInventory,
    *,
    directory: Path,
) -> None:
    """Reject unsafe or ambiguous mapping before publishing pending authority.

    :param inventory: Exact project-enumerated movement, including ownership marker.
    :param directory: Installation metadata excluded from payload movement.
    """
    if inventory.unknown:
        raise InstallationError(
            "Unknown payload needs a project-owned migration inventory."
        )
    if inventory.source_root == inventory.destination_root:
        raise InstallationError("Migration source and destination must differ.")
    sources: set[Path] = set()
    destinations: set[Path] = set()
    for entry, destination in zip(
        inventory.entries, inventory.destinations, strict=True
    ):
        assert_no_links(entry.path)
        assert_no_links(destination)
        if (
            not entry.path.is_absolute()
            or not destination.is_absolute()
            or not entry.path.is_relative_to(inventory.source_root)
            or not destination.is_relative_to(inventory.destination_root)
            or entry.path == inventory.source_root
            or destination == inventory.destination_root
            or entry.path.is_relative_to(directory)
            or destination.is_relative_to(directory)
            or entry.path in sources
            or destination in destinations
        ):
            raise InstallationError(
                "Migration inventory has unsafe, duplicate or out-of-root targets."
            )
        if entry.kind != "file" or entry.revision is None:
            raise InstallationError(
                "Enumerate individual revision-checked files; directories are never moved recursively."
            )
        sources.add(entry.path)
        destinations.add(destination)
    if sources & destinations:
        raise InstallationError(
            "Migration source/destination mapping overlaps."
        )


def _record_migration_failure(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    app_id: str,
    error: Exception,
) -> None:
    """Persist a failure only while the same pending revision remains active."""
    latest = inspect_installation(directory, app_id=app_id)
    record = latest.record
    if (
        record is None
        or latest.revision is None
        or latest.revision != expected_revision
        or record.operation is None
        or record.operation.operation_id != operation_id
        or record.operation.phase == "failed"
    ):
        return
    fail_operation(
        directory,
        operation_id=operation_id,
        expected_revision=latest.revision,
        diagnostic=InstallationDiagnostic(
            "migration-failed",
            str(error),
            "Resolve the reported conflict, then resume this migration.",
        ),
    )


def execute_migration(plan: MigrationPlan) -> InstallationInspection:
    """Begin and execute an explicitly confirmed migration.

    :param plan: Revision-checked mapping and resource-consumer quiescence confirmation.
    :return: Activated placement, or a durable incomplete record on failure.
    """
    if not plan.quiescent:
        raise InstallationError(
            "Stop resource consumers before executing migration."
        )
    validate_migration_inventory(plan.inventory, directory=plan.directory)
    with installation_lock(plan.directory):
        pending = begin_operation(plan)
        assert pending.revision is not None
        return resume_migration(
            plan.directory,
            operation_id=plan.operation_id,
            expected_revision=pending.revision,
        )


def _resume_migration(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
) -> InstallationInspection:
    """Resume exact resource moves while preserving unknown files.

    :param directory: Explicit installation authority address.
    :param operation_id: Expected pending migration identifier.
    :param expected_revision: Last inspected authority revision.
    :return: Activated placement; unknown files remain untouched.
    """
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        migration = record.migration
        if (
            operation is None
            or operation.kind != "migrate"
            or migration is None
        ):
            raise InstallationError("No matching migration is pending.")
        inventory = migration.inventory
        validate_migration_inventory(inventory, directory=directory)
        roots = (
            [inventory.source_root, inventory.destination_root]
            if inventory.entries
            else []
        )
        with managed_write_lock(*roots):
            ordered = sorted(
                zip(inventory.entries, inventory.destinations, strict=True),
                key=lambda pair: pair[0].path.name == ".apprc-owner.json",
            )
            for entry, destination in ordered:
                source_revision = file_revision(entry.path)
                destination_revision = file_revision(destination)
                if (
                    source_revision is None
                    and destination_revision == entry.revision
                ):
                    continue
                if source_revision != entry.revision:
                    raise InstallationError(
                        f"Migration source changed: {entry.path}."
                    )
                if destination_revision is not None:
                    raise InstallationError(
                        f"Migration destination is occupied: {destination}."
                    )
                assert_no_links(entry.path)
                assert_no_links(destination)
                create_private_directory_if_missing(destination.parent)
                entry.path.rename(destination)

            current = record.current
            if current is not None:
                current = replace(current, placement=operation.placement)
            activated = replace(
                record,
                placement=operation.placement,
                status="ready" if current is not None else "removed-retained",
                current=current,
                operation=None,
                last_successful=current
                if current is not None
                else record.last_successful,
                migration=replace(migration, phase="activated"),
            )
            write_record(
                directory, activated, expected_revision=expected_revision
            )
        return inspect_installation(directory, app_id=record.app_id)


def resume_migration(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
) -> InstallationInspection:
    """Resume exact migration state and record failure while authority is unchanged.

    :param directory: Explicit installation address.
    :param operation_id: Pending migration identifier.
    :param expected_revision: Last inspected authority revision.
    :return: Activated authority; unknown files remain untouched.
    """
    record = _pending(directory, operation_id, expected_revision)
    try:
        return _resume_migration(
            directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
        )
    except Exception as error:
        try:
            _record_migration_failure(
                directory,
                operation_id=operation_id,
                expected_revision=expected_revision,
                app_id=record.app_id,
                error=error,
            )
        except Exception as record_error:
            raise ExceptionGroup(
                "Migration failed and its diagnostic could not be recorded.",
                [error, record_error],
            ) from error
        raise
