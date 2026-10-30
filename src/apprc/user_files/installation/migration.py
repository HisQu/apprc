"""Explicit ownership-preserving migration with durable resumable authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstallationRecord,
    InstallationMigration,
    LegacyMigrationEvidence,
    OwnedOutput,
    StagedSupportOutput,
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
    allow_empty_same_root: bool = False,
) -> None:
    """Reject unsafe/ambiguous mapping before publishing pending authority.

    :param inventory: Exact project-enumerated movement, including ownership marker.
    :param directory: Installation metadata excluded from payload movement.
    :param allow_empty_same_root: Permit in-place receipt migration without resource moves.
    """
    if inventory.unknown:
        raise InstallationError(
            "Unknown payload needs a project-owned migration inventory."
        )
    if inventory.source_root == inventory.destination_root and not (
        allow_empty_same_root and not inventory.entries
    ):
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


def _validate_legacy_namespace(
    evidence: LegacyMigrationEvidence,
    owned_outputs: tuple[OwnedOutput, ...],
    *,
    staged_support: tuple[StagedSupportOutput, ...] = (),
    directory: Path,
) -> None:
    """Reject unknown files in the exact legacy authority namespace.

    :param evidence: Strict receipt and runnable paths.
    :param owned_outputs: Exact replacement support outputs.
    :param directory: New AppRC authority address.
    :return: None.
    """
    root = evidence.receipt.path.parent
    if not root.exists():
        return
    assert_no_links(root)
    expected = {
        evidence.receipt.path,
        *(item.path for item in evidence.runnables),
        *(item.inert_path for item in evidence.runnables),
    }
    if root == directory:
        expected.add(directory / "installation.json")
        expected.add(directory / "locks")
        expected.update(
            directory / output.path
            for output in owned_outputs
            if output.kind == "support"
        )
        expected.update(item.source for item in staged_support)
        if staged_support:
            expected.add(directory / "migration-staged")
        locks = directory / "locks"
        if locks.exists():
            expected.update(locks.iterdir())
    if any(path not in expected for path in root.iterdir()):
        raise InstallationError(
            "Unknown legacy installation files require project-owned migration."
        )


def _validate_support_outputs(
    record: InstallationRecord, *, directory: Path
) -> None:
    """Verify every replacement controller before retiring migration state."""
    support_outputs = tuple(
        output for output in record.owned_outputs if output.kind == "support"
    )
    if not support_outputs:
        raise InstallationError("Validated replacement support is missing.")
    for output in support_outputs:
        path = directory / output.path
        assert_no_links(path)
        if output.digest is None or file_revision(path) != output.digest:
            raise InstallationError(
                f"Replacement support is not validated: {output.path}."
            )


def _validate_staged_support(
    migration: InstallationMigration,
    record: InstallationRecord,
    *,
    directory: Path,
) -> None:
    """Validate exact staged replacement bytes without publishing them."""
    staged_support = migration.staged_support
    outputs = {
        directory / output.path: output.digest
        for output in record.owned_outputs
        if output.kind == "support"
    }
    staging_root = directory / "migration-staged" / str(record.generation_id)
    if (
        not outputs
        or None in outputs.values()
        or {item.destination: item.digest for item in staged_support} != outputs
        or len(staged_support) != len(outputs)
        or len({item.source for item in staged_support}) != len(staged_support)
        or any(
            not item.source.is_relative_to(staging_root)
            for item in staged_support
        )
    ):
        raise InstallationError(
            "Staged support does not exactly match replacement outputs."
        )
    expected_files = {item.source for item in staged_support}
    expected_directories = {
        parent
        for item in staged_support
        for parent in item.source.parents
        if parent == staging_root or parent.is_relative_to(staging_root)
    }
    for directory_path in expected_directories:
        if not directory_path.exists():
            continue
        assert_no_links(directory_path)
        if not directory_path.is_dir() or any(
            child not in expected_files | expected_directories
            for child in directory_path.iterdir()
        ):
            raise InstallationError(
                f"Unknown staged support content requires manual inspection: {directory_path}."
            )
    for item in staged_support:
        assert_no_links(item.source)
        assert_no_links(item.destination)
        source_revision = file_revision(item.source)
        destination_revision = file_revision(item.destination)
        if source_revision is not None and source_revision != item.digest:
            raise InstallationError(f"Staged support changed: {item.source}.")
        if source_revision is None and destination_revision != item.digest:
            raise InstallationError(
                f"Staged support is missing: {item.source}."
            )


def _retire_legacy_controllers(
    evidence: LegacyMigrationEvidence,
    *,
    replacements: Mapping[Path, str],
    allow_missing_receipt: bool = False,
) -> None:
    """Rename only inspected controller files to their exact inert addresses."""
    receipt = evidence.receipt.path
    assert_no_links(receipt)
    receipt_revision = file_revision(receipt)
    if receipt_revision == evidence.receipt.revision:
        pass
    elif not (allow_missing_receipt and receipt_revision is None):
        raise InstallationError("Legacy receipt changed after inspection.")
    for runnable in evidence.runnables:
        assert_no_links(runnable.path)
        assert_no_links(runnable.inert_path)
        source_revision = file_revision(runnable.path)
        inert_revision = file_revision(runnable.inert_path)
        if inert_revision == runnable.revision and (
            source_revision is None
            or source_revision == replacements.get(runnable.path)
        ):
            continue
        if source_revision != runnable.revision:
            raise InstallationError(
                f"Legacy controller changed after inspection: {runnable.path}."
            )
        if inert_revision is not None:
            raise InstallationError(
                f"Legacy inert target is occupied: {runnable.inert_path}."
            )
        runnable.path.rename(runnable.inert_path)


def _promote_staged_support(migration: InstallationMigration) -> None:
    """Promote staged support without overwriting a canonical target."""
    for item in migration.staged_support:
        assert_no_links(item.source)
        assert_no_links(item.destination)
        source_revision = file_revision(item.source)
        destination_revision = file_revision(item.destination)
        if source_revision is None and destination_revision == item.digest:
            continue
        if source_revision != item.digest:
            raise InstallationError(
                f"Staged support changed or disappeared: {item.source}."
            )
        if destination_revision is not None:
            raise InstallationError(
                f"Support destination is occupied: {item.destination}."
            )
        create_private_directory_if_missing(item.destination.parent)
        item.source.rename(item.destination)


def _remove_legacy_receipt(
    evidence: LegacyMigrationEvidence,
    *,
    replacements: Mapping[Path, str],
) -> None:
    """Delete the exact old receipt only after every controller is inert."""
    for runnable in evidence.runnables:
        assert_no_links(runnable.path)
        assert_no_links(runnable.inert_path)
        active_revision = file_revision(runnable.path)
        if active_revision is not None and active_revision != replacements.get(
            runnable.path
        ):
            raise InstallationError("Legacy controller is still active.")
        if file_revision(runnable.inert_path) != runnable.revision:
            raise InstallationError("Retired legacy controller changed.")
    receipt = evidence.receipt.path
    assert_no_links(receipt)
    revision = file_revision(receipt)
    if revision is None:
        return
    if revision != evidence.receipt.revision:
        raise InstallationError("Legacy receipt changed after inspection.")
    receipt.unlink()


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

    :param plan: Revision-checked mapping and old-consumer quiescence confirmation.
    :return: Activated placement, or a durable incomplete record on failure.
    """
    if not plan.quiescent:
        raise InstallationError(
            "Stop legacy consumers before executing migration."
        )
    validate_migration_inventory(
        plan.inventory,
        directory=plan.directory,
        allow_empty_same_root=plan.legacy is not None,
    )
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
    """Resume exact resource moves and the staged legacy controller cutover."""
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
        validate_migration_inventory(
            inventory,
            directory=directory,
            allow_empty_same_root=migration.legacy is not None,
        )
        roots = [inventory.source_root, inventory.destination_root]
        legacy = migration.legacy
        if legacy is not None:
            roots.append(legacy.receipt.path.parent)
            roots.extend(item.path.parent for item in legacy.runnables)
            roots.extend(
                item.source.parent for item in migration.staged_support
            )
            roots.extend(
                item.destination.parent for item in migration.staged_support
            )
        with managed_write_lock(*roots):
            if legacy is not None:
                _validate_legacy_namespace(
                    legacy,
                    record.owned_outputs,
                    staged_support=migration.staged_support,
                    directory=directory,
                )
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

            revision = expected_revision
            if legacy is not None:
                _validate_staged_support(migration, record, directory=directory)
                replacements = {
                    item.destination: item.digest
                    for item in migration.staged_support
                }
                _retire_legacy_controllers(
                    legacy,
                    replacements=replacements,
                    allow_missing_receipt=migration.phase
                    in {"moved", "activated"},
                )
                if migration.phase == "staged":
                    migration = replace(migration, phase="retired")
                    record = replace(record, migration=migration)
                    revision = write_record(
                        directory, record, expected_revision=revision
                    )
                _promote_staged_support(migration)
                if migration.phase != "moved":
                    migration = replace(migration, phase="moved")
                    record = replace(record, migration=migration)
                    revision = write_record(
                        directory, record, expected_revision=revision
                    )
                _validate_support_outputs(record, directory=directory)
                _remove_legacy_receipt(legacy, replacements=replacements)

            current = record.current
            if current is not None:
                current = replace(current, placement=operation.placement)
            retired_files = (
                tuple(item.inert_path for item in legacy.runnables)
                if legacy is not None
                else ()
            )
            activated = replace(
                record,
                placement=operation.placement,
                status="ready" if current is not None else "removed-retained",
                current=current,
                operation=None,
                last_successful=current
                if current is not None
                else record.last_successful,
                migration=replace(
                    migration,
                    phase="activated",
                    retired_files=retired_files,
                    cleanup_complete=legacy is None,
                ),
            )
            activated_revision = write_record(
                directory, activated, expected_revision=revision
            )
            if legacy is not None:
                return _cleanup_activated_migration(
                    directory, activated, expected_revision=activated_revision
                )
        return inspect_installation(directory, app_id=record.app_id)


def _cleanup_activated_migration(
    directory: Path,
    record: InstallationRecord,
    *,
    expected_revision: str,
) -> InstallationInspection:
    """Remove only recorded inert controllers and this generation's empty staging tree."""
    migration = record.migration
    if (
        record.operation is not None
        or migration is None
        or migration.operation_id is None
        or migration.phase != "activated"
    ):
        raise InstallationError("No activated migration cleanup is pending.")
    if migration.cleanup_complete:
        return inspect_installation(directory, app_id=record.app_id)
    if migration.legacy is None:
        raise InstallationError(
            "Activated migration has no legacy cleanup evidence."
        )
    with installation_lock(directory):
        latest = _pending(
            directory,
            migration.operation_id,
            expected_revision,
            require_operation=False,
        )
        migration = latest.migration
        if (
            latest.status not in {"ready", "removed-retained"}
            or migration is None
            or migration.phase != "activated"
            or migration.cleanup_complete
            or migration.legacy is None
        ):
            raise InstallationError(
                "Activated migration cleanup changed after inspection."
            )
        _validate_support_outputs(latest, directory=directory)
        runnables = {
            item.inert_path: item for item in migration.legacy.runnables
        }
        if not set(migration.retired_files).issubset(runnables):
            raise InstallationError(
                "Retired cleanup list contains an unknown path."
            )
        roots = [item.path.parent for item in migration.legacy.runnables]
        roots.extend(item.source.parent for item in migration.staged_support)
        with managed_write_lock(*roots):
            _validate_legacy_namespace(
                migration.legacy,
                latest.owned_outputs,
                staged_support=migration.staged_support,
                directory=directory,
            )
            for path in migration.retired_files:
                runnable = runnables[path]
                assert_no_links(path)
                revision = file_revision(path)
                if revision is None:
                    continue
                if revision != runnable.revision:
                    raise InstallationError(
                        f"Retired controller changed: {path}."
                    )
                path.unlink()
            if migration.staged_support:
                stage_root = (
                    directory / "migration-staged" / str(latest.generation_id)
                )
                directories = {
                    parent
                    for item in migration.staged_support
                    for parent in item.source.parents
                    if parent == stage_root or parent.is_relative_to(stage_root)
                }
                for path in sorted(
                    directories, key=lambda item: len(item.parts), reverse=True
                ):
                    if path.exists() or path.is_symlink():
                        assert_no_links(path)
                        try:
                            path.rmdir()
                        except OSError as error:
                            raise InstallationError(
                                f"Staging directory is not empty: {path}."
                            ) from error
            cleared = replace(
                latest,
                migration=replace(
                    migration, retired_files=(), cleanup_complete=True
                ),
            )
            write_record(
                directory, cleared, expected_revision=expected_revision
            )
        return inspect_installation(directory, app_id=record.app_id)


def resume_migration(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
) -> InstallationInspection:
    """Resume exact migration state and record failures when authority is unchanged.

    :param directory: Explicit installation address.
    :param operation_id: Expected pending cutover UUID.
    :param expected_revision: Last inspected authority revision.
    :return: Activated authority; unknown files remain untouched.
    """
    record = _pending(
        directory, operation_id, expected_revision, require_operation=False
    )
    try:
        if record.operation is None:
            return _cleanup_activated_migration(
                directory, record, expected_revision=expected_revision
            )
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
