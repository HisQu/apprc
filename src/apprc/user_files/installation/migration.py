"""Explicit ownership-preserving migration with durable resumable authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    MigrationInventory,
    MigrationPlan,
    OperationContext,
    OperationStep,
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
    record_step,
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


def execute_migration(
    plan: MigrationPlan,
    *,
    migration_hook: (
        Callable[[MigrationPlan, OperationContext], None] | None
    ) = None,
) -> InstallationInspection:
    """Begin and execute an explicitly confirmed migration.

    :param plan: Revision-checked mapping and resource-consumer quiescence confirmation.
    :param migration_hook: Application-owned callback composed by the CLI.
    :return: Activated placement, or a durable incomplete record on failure.
    """
    if not plan.quiescent:
        raise InstallationError(
            "Stop resource consumers before executing migration."
        )
    validate_migration_inventory(plan.inventory, directory=plan.directory)
    pending = begin_operation(plan)
    assert pending.revision is not None
    return resume_migration(
        plan.directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        migration_hook=migration_hook,
    )


def _run_migration_hook(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    migration_hook: (Callable[[MigrationPlan, OperationContext], None] | None),
) -> str:
    """Run the captured provider only after exact pending authority is durable."""
    record = _pending(directory, operation_id, expected_revision)
    operation = record.operation
    migration = record.migration
    runtime = record.active_runtime
    if operation is None or operation.kind != "migrate" or migration is None:
        raise InstallationError("No matching migration is pending.")
    if (
        runtime is None
        or OperationStep.MIGRATION_HOOK_COMPLETED in operation.steps
        or not runtime.hooks.migrate
    ):
        return expected_revision
    if migration_hook is None:
        raise InstallationError(
            "Required application migration provider is unavailable."
        )
    migration_plan = MigrationPlan(
        directory=directory,
        expected_revision=expected_revision,
        expected_generation=record.generation_id,
        app_id=record.identity.app_id,
        operation_id=operation_id,
        generation_id=record.generation_id,
        placement=operation.placement,
        inventory=migration.inventory,
        quiescent=True,
        identity=record.identity,
        command_name=record.command_name,
    )
    context = OperationContext(
        directory=directory,
        operation_id=operation_id,
        generation_id=record.generation_id,
        placement=operation.placement,
    )
    migration_hook(migration_plan, context)
    checkpoint = record_step(
        directory,
        operation_id=operation_id,
        expected_revision=expected_revision,
        step=OperationStep.MIGRATION_HOOK_COMPLETED,
    )
    if checkpoint.revision is None:
        raise InstallationError("Migration hook checkpoint was not persisted.")
    return checkpoint.revision


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

            activated = replace(
                record,
                placement=operation.placement,
                status="ready"
                if record.active_runtime is not None
                else "removed-retained",
                operation=None,
                migration=replace(migration, phase="activated"),
            )
            write_record(
                directory, activated, expected_revision=expected_revision
            )
        return inspect_installation(directory, app_id=record.identity.app_id)


def resume_migration(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    migration_hook: (
        Callable[[MigrationPlan, OperationContext], None] | None
    ) = None,
) -> InstallationInspection:
    """Resume exact migration state and record failure while authority is unchanged.

    :param directory: Explicit installation address.
    :param operation_id: Pending migration identifier.
    :param expected_revision: Exact current authority revision.
    :param migration_hook: Application-owned callback for an uncheckpointed hook.
    :return: Activated authority; unknown files remain untouched.
    """
    record = _pending(directory, operation_id, expected_revision)
    current_revision = expected_revision
    try:
        current_revision = _run_migration_hook(
            directory,
            operation_id=operation_id,
            expected_revision=current_revision,
            migration_hook=migration_hook,
        )
        return _resume_migration(
            directory,
            operation_id=operation_id,
            expected_revision=current_revision,
        )
    except Exception as error:
        try:
            _record_migration_failure(
                directory,
                operation_id=operation_id,
                expected_revision=current_revision,
                app_id=record.identity.app_id,
                error=error,
            )
        except Exception as record_error:
            raise ExceptionGroup(
                "Migration failed and its diagnostic could not be recorded.",
                [error, record_error],
            ) from error
        raise
