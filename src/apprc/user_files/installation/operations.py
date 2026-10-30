"""Revision-checked authority transitions shared with standalone controllers.

Backend and provider actions are deliberately outside this module. Callers hold
one lifecycle lock around their ordinary Python composition; nested transition
calls reuse that lock and revalidate exact receipt revisions.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationSource,
    InstallationTarget,
    InstalledSnapshot,
    InstallPlan,
    LegacyMigrationEvidence,
    StagedSupportOutput,
    MigrationInventory,
    MigrationPlan,
    OperationPlan,
    OperationStep,
    UninstallCommit,
    UninstallPlan,
    UvToolTarget,
)
from apprc.definition.paths import ResourceKind
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation

from apprc.user_files.installation.planning import (
    validate_cleanup,
    validate_placement,
)

SUPPORT_VERSION = "0.31.0"


def _repair_source(
    record: InstallationRecord, source: InstallationSource
) -> InstallationSource:
    """Retain matching saved archive proof when rebuilding a repair plan."""
    for snapshot in (record.current, record.last_successful):
        if snapshot is None:
            continue
        observed = snapshot.source
        if not replace(source, digest=None).matches_observation(
            replace(observed, digest=None)
        ):
            continue
        if (
            source.digest is not None
            and observed.digest is not None
            and source.digest != observed.digest
        ):
            raise InstallationError(
                "Repair digest differs from the recorded source proof."
            )
        if source.digest is None and observed.digest is not None:
            return replace(source, digest=observed.digest)
        return source
    return source


def _requires_record_proof(source: InstallationSource) -> bool:
    """Identify acquired archive sources whose ready snapshot needs RECORD proof."""
    return source.kind == "release-sdist" or (
        source.kind == "index"
        and source.digest is not None
        and re.fullmatch(
            r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
            source.requirement,
        )
        is not None
    )


def plan_install(
    identity: InstallationIdentity,
    source: InstallationSource,
    placement: InstallationPlacement,
    backend: UvToolTarget,
    *,
    inspection: InstallationInspection,
) -> InstallPlan:
    """Plan acquisition without touching disk, executing uv or downloading code.

    :param identity: Distinct application/package/entry identities.
    :param source: Exact acquisition input.
    :param placement: Explicit intended absolute resource locations.
    :param backend: Selected backend address.
    :param inspection: Previously read authority and compare preconditions.
    :return: Immutable acquisition plan.
    """
    record = inspection.require_usable()
    if identity.app_id != inspection.app_id:
        raise InstallationError(
            "Target identity differs from captured discovery identity."
        )
    validate_placement(placement, directory=inspection.directory)
    if placement.layout.mode == "native" and placement.appdata_dir is not None:
        import sys
        from apprc.user_files.installation.validation import (
            check_native_appdata_container,
        )

        if sys.platform not in {"win32", "darwin"}:
            check_native_appdata_container(
                placement.appdata_dir.parent, app_id=identity.app_id
            )
    if record is not None and record.app_id != identity.app_id:
        raise InstallationError(
            "Install identity differs from saved authority."
        )
    if record is not None and record.current is not None:
        if record.current.identity.distribution != identity.distribution:
            raise InstallationError(
                "Cannot replace a different installed distribution."
            )
        if record.current.backend != backend:
            raise InstallationError(
                "Replacement must target the recorded uv backend."
            )
    if record is not None:
        from apprc.definition.installation import RetiredResource
        from apprc.user_files.installation.planning import resource_roots

        selected = set(resource_roots(placement))
        retired = tuple(
            dict.fromkeys(
                (
                    *placement.retired,
                    *(
                        RetiredResource(kind, path)
                        for kind, path in resource_roots(record.placement)
                        if (kind, path) not in selected
                    ),
                )
            )
        )
        placement = replace(placement, retired=retired)
        validate_placement(placement, directory=inspection.directory)
    return InstallPlan(
        inspection.directory,
        inspection.revision,
        record.generation_id if record is not None else None,
        InstallationTarget(identity, source, placement, backend),
        uuid4(),
        uuid4(),
        "replace" if record is not None else "install",
    )


def plan_repair(
    identity: InstallationIdentity,
    source: InstallationSource,
    placement: InstallationPlacement,
    backend: UvToolTarget,
    *,
    inspection: InstallationInspection,
) -> InstallPlan:
    """Plan repair from exact recorded facts without selecting a new backend.

    A matching pending install resumes its operation UUID and checkpoints. A
    ready or removed-retained generation starts a new operation while retaining
    that generation's UUID.

    :param identity: Explicit application/package/import/command identity.
    :param source: Explicit source facts matching the saved installation.
    :param placement: Explicit saved placement; repair does not relocate data.
    :param backend: Explicit recorded uv tool address.
    :param inspection: Previously inspected host authority and exact revision.
    :return: Repair plan retaining the saved generation.
    """
    record = inspection.record
    if (
        record is None
        or identity.app_id != inspection.app_id
        or record.app_id != identity.app_id
    ):
        raise InstallationError(
            "Repair requires a valid record for the captured application."
        )
    validate_placement(placement, directory=inspection.directory)
    target = InstallationTarget(
        identity, _repair_source(record, source), placement, backend
    )
    if record.operation is not None:
        saved = record.operation.intended
        if (
            inspection.status not in {"provisional", "incomplete"}
            or record.operation.kind not in {"install", "replace", "repair"}
            or saved is None
            or saved.identity != target.identity
            or not (
                saved.source.matches_observation(target.source)
                or target.source.matches_observation(saved.source)
            )
            or saved.placement != target.placement
            or saved.backend != target.backend
        ):
            raise InstallationError(
                "Pending operation does not match the explicit repair inputs."
            )
        retained_source = target.source
        if retained_source.digest is None and saved.source.digest is not None:
            retained_source = replace(
                retained_source, digest=saved.source.digest
            )
        saved_target = replace(saved, source=retained_source)
        return InstallPlan(
            inspection.directory,
            inspection.revision,
            record.generation_id,
            saved_target,
            record.operation.operation_id,
            record.generation_id,
            "repair",
        )
    if inspection.status not in {"ready", "removed-retained"}:
        raise InstallationError(
            "Repair requires a resumable operation or valid saved installation."
        )
    observed = record.current or record.last_successful
    if observed is None:
        raise InstallationError(
            "Repair needs explicit saved source and placement facts."
        )
    if (
        observed.identity != identity
        or not target.source.matches_observation(observed.source)
        or observed.placement != placement
        or observed.backend != backend
    ):
        raise InstallationError(
            "Repair inputs differ from the recorded installation."
        )
    return InstallPlan(
        inspection.directory,
        inspection.revision,
        record.generation_id,
        target,
        uuid4(),
        record.generation_id,
        "repair",
    )


def plan_uninstall(
    record: InstallationRecord,
    *,
    directory: Path,
    revision: str,
    categories: frozenset[ResourceKind] = frozenset(),
    complete: bool = False,
    forget_retained: bool = False,
    inventory: CleanupInventory,
) -> UninstallPlan:
    """Capture exact confirmed ownership targets; shared uv is never included.

    :param record: Valid observed authority.
    :param directory: Explicit authority namespace.
    :param revision: Exact record bytes digest.
    :param categories: Selected owned resource categories.
    :param complete: Retire authority only when tracked cleanup is resolved.
    :param forget_retained: Explicitly leave named retained files unmanaged.
    :param inventory: Exact owner/provider enumeration, not recursive roots.
    :return: Immutable removal plan.
    """
    if record.operation is not None:
        raise InstallationError(
            "Resume or repair the pending operation before removal."
        )
    if not complete and (categories or forget_retained):
        raise InstallationError(
            "Resource removal/forgetting requires explicit complete removal."
        )
    owned_categories = record.placement.capabilities | frozenset(
        resource.kind for resource in record.placement.retired
    )
    if not categories.issubset(owned_categories):
        raise InstallationError(
            "Removal cannot enable unrecorded resource categories."
        )
    validate_cleanup(
        inventory,
        placement=record.placement,
        directory=directory,
        categories=categories,
        complete=complete,
        forget_retained=forget_retained,
    )
    return UninstallPlan(
        directory,
        revision,
        record.generation_id,
        record.app_id,
        uuid4(),
        record.placement,
        inventory,
        categories,
        complete,
        forget_retained,
    )


def plan_migration(
    inspection: InstallationInspection,
    placement: InstallationPlacement,
    *,
    inventory: MigrationInventory,
    quiescent: bool = False,
    observed: InstalledSnapshot | None = None,
    legacy: LegacyMigrationEvidence | None = None,
    staged_support: tuple[StagedSupportOutput, ...] = (),
    generation_id: UUID | None = None,
) -> MigrationPlan:
    """Plan only explicitly enumerated ownership-preserving movement.

    :param inspection: Host authority and exact revision.
    :param placement: Intended absolute resource locations.
    :param inventory: Repository/provider source/destination enumeration.
    :param quiescent: Explicit confirmation that legacy consumers are stopped.
    :param observed: Live package evidence for legacy receipt conversion.
    :param legacy: Strict receipt and exact runnable revisions.
    :param staged_support: Digest-checked replacement support staged beside authority.
    :param generation_id: Chosen generation matching the stage namespace.
    :return: Migration plan; execution still revalidates quiescence and targets.
    """
    record = inspection.require_usable()
    if record is not None and record.app_id != inspection.app_id:
        raise InstallationError(
            "Migration identity differs from captured host."
        )
    validate_placement(placement, directory=inspection.directory)
    if inventory.unknown:
        raise InstallationError(
            "Unknown payload requires a project-owned migration inventory."
        )
    if (legacy is None) != (observed is None):
        raise InstallationError(
            "Legacy receipt migration requires live package evidence."
        )
    if legacy is not None and observed is not None:
        if (
            observed.identity.app_id != inspection.app_id
            or observed.identity.distribution != legacy.distribution
            or legacy.command not in observed.identity.commands
            or observed.version != legacy.version
            or observed.backend != legacy.backend
            or observed.placement != placement
        ):
            raise InstallationError(
                "Legacy receipt does not match the verified installed package."
            )
    generation = generation_id or uuid4()
    if legacy is None:
        if staged_support:
            raise InstallationError(
                "Staged support is only valid for legacy receipt migration."
            )
    else:
        assert observed is not None
        staging_root = (
            inspection.directory / "migration-staged" / str(generation)
        )
        expected = {
            inspection.directory / output.path: output.digest
            for output in observed.owned_outputs
            if output.kind == "support"
        }
        actual = {item.destination: item.digest for item in staged_support}
        if (
            not expected
            or None in expected.values()
            or actual != expected
            or len(staged_support) != len(actual)
            or len({item.source for item in staged_support})
            != len(staged_support)
            or any(
                item.source == item.destination
                or not item.source.is_relative_to(staging_root)
                for item in staged_support
            )
        ):
            raise InstallationError(
                "Staged support does not exactly match the saved replacement outputs."
            )
    return MigrationPlan(
        inspection.directory,
        inspection.revision,
        record.generation_id if record is not None else None,
        inspection.app_id,
        uuid4(),
        generation,
        placement,
        inventory,
        quiescent,
        observed,
        legacy,
        staged_support,
    )


def _identity(plan: OperationPlan) -> str:
    return (
        plan.target.identity.app_id
        if isinstance(plan, InstallPlan)
        else plan.app_id
    )


def _checked(plan: OperationPlan) -> InstallationInspection:
    inspection = inspect_installation(plan.directory, app_id=_identity(plan))
    if (
        inspection.revision != plan.expected_revision
        or inspection.snapshot.generation_id != plan.expected_generation
    ):
        raise InstallationError(
            "Installation changed after planning; inspect and plan again."
        )
    if isinstance(plan, InstallPlan) and plan.kind == "repair":
        record = inspection.record
        if record is None:
            raise InstallationError(
                "Repair requires a saved installation record."
            )
        if plan.generation_id != record.generation_id:
            raise InstallationError(
                "Repair cannot change the saved installation generation."
            )
        operation = record.operation
        if operation is not None:
            if (
                inspection.status not in {"provisional", "incomplete"}
                or operation.kind not in {"install", "replace", "repair"}
                or operation.operation_id != plan.operation_id
                or operation.intended is None
                or operation.intended.identity != plan.target.identity
                or not (
                    operation.intended.source.matches_observation(
                        plan.target.source
                    )
                    or plan.target.source.matches_observation(
                        operation.intended.source
                    )
                )
                or operation.intended.placement != plan.target.placement
                or operation.intended.backend != plan.target.backend
            ):
                raise InstallationError(
                    "Pending repair operation changed after planning."
                )
        elif inspection.status not in {"ready", "removed-retained"}:
            raise InstallationError(
                "Repair requires a resumable operation or valid saved installation."
            )
        return inspection
    inspection.require_usable()
    return inspection


def begin_operation(plan: OperationPlan) -> InstallationInspection:
    """Publish pending authority before the caller changes package or data.

    :param plan: Validated acquisition, migration or removal decision.
    :return: Newly persisted authority and exact revision.
    """
    with installation_lock(plan.directory):
        inspection = _checked(plan)
        previous = inspection.record
        if (
            isinstance(plan, InstallPlan)
            and plan.kind == "repair"
            and previous is not None
            and previous.operation is not None
        ):
            return inspection
        if isinstance(plan, MigrationPlan) and not plan.quiescent:
            raise InstallationError(
                "Stop legacy consumers before executing migration."
            )
        placement = (
            plan.target.placement
            if isinstance(plan, InstallPlan)
            else plan.placement
        )
        operation = InstallationOperation(
            operation_id=plan.operation_id,
            kind=plan.kind
            if isinstance(plan, InstallPlan)
            else (
                "uninstall" if isinstance(plan, UninstallPlan) else "migrate"
            ),
            phase="pending",
            intended=plan.target if isinstance(plan, InstallPlan) else None,
            placement=placement,
            categories=plan.categories
            if isinstance(plan, UninstallPlan)
            else frozenset(),
            complete=plan.complete
            if isinstance(plan, UninstallPlan)
            else False,
            forget_retained=plan.forget_retained
            if isinstance(plan, UninstallPlan)
            else False,
            inventory=plan.inventory
            if isinstance(plan, UninstallPlan)
            else CleanupInventory(),
        )
        generation = (
            plan.expected_generation
            if isinstance(plan, UninstallPlan)
            else plan.generation_id
        )
        if previous is None:
            record = InstallationRecord(
                1,
                _identity(plan),
                generation,
                SUPPORT_VERSION,
                placement,
                "provisional",
                operation=operation,
            )
        else:
            record = replace(
                previous,
                generation_id=generation,
                status="incomplete",
                operation=operation,
            )
        if isinstance(plan, MigrationPlan):
            from apprc.definition.installation import InstallationMigration

            if plan.observed is not None:
                record = replace(
                    record,
                    status="incomplete",
                    current=plan.observed,
                    last_successful=plan.observed,
                    owned_outputs=plan.observed.owned_outputs,
                )
            record = replace(
                record,
                migration=InstallationMigration(
                    plan.inventory.source_root,
                    plan.inventory.destination_root,
                    "staged",
                    plan.inventory,
                    legacy=plan.legacy,
                    staged_support=plan.staged_support,
                    operation_id=plan.operation_id,
                ),
            )
        write_record(
            plan.directory, record, expected_revision=plan.expected_revision
        )
        return inspect_installation(plan.directory, app_id=record.app_id)


def _pending(
    directory: Path,
    operation_id: UUID,
    revision: str,
    *,
    require_operation: bool = True,
) -> InstallationRecord:
    from apprc.user_files.installation.codec import decode_record
    from hashlib import sha256
    import json

    content = (directory / "installation.json").read_bytes()
    if sha256(content).hexdigest() != revision:
        raise InstallationError("Installation operation revision changed.")
    # > The caller's operation UUID is checked after strict decoding; app_id is
    # > used only to validate internal consistency, never for path discovery.
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get("app_id"), str):
        raise InstallationError("Installation identity is invalid.")
    record = decode_record(content, app_id=value["app_id"])
    if require_operation:
        if (
            record.operation is None
            or record.operation.operation_id != operation_id
        ):
            raise InstallationError(
                "Installation operation is no longer active."
            )
    elif (
        record.operation is not None
        and record.operation.operation_id != operation_id
    ):
        raise InstallationError("Installation operation identifier changed.")
    elif (
        record.migration is None
        or record.migration.operation_id != operation_id
    ):
        raise InstallationError("Installation migration identifier changed.")
    return record


def record_step(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    step: OperationStep,
    observed: InstalledSnapshot | None = None,
) -> InstallationInspection:
    """Save a completed action and truthful live state.

    :param directory: Explicit locked authority address.
    :param operation_id: Expected pending operation.
    :param expected_revision: Exact previous bytes digest.
    :param step: Completed standard checkpoint.
    :param observed: Actual observed backend, never a predicted package.
    :return: New authority and revision.
    """
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        if observed is not None and observed.identity.app_id != record.app_id:
            raise InstallationError(
                "Observed backend belongs to another application."
            )
        if (
            step == OperationStep.PACKAGE_CHANGED
            and observed is not None
            and operation.kind in {"repair", "replace"}
            and _requires_record_proof(observed.source)
            and (operation.kind == "repair" or record.current is not None)
        ):
            previous = record.current or record.last_successful
            if (
                previous is None
                or previous.distribution_record_digest is None
                or observed.distribution_record_digest
                != previous.distribution_record_digest
            ):
                raise InstallationError(
                    "Repair snapshot differs from the saved RECORD fingerprint."
                )
        current = record.current
        if step == OperationStep.PACKAGE_CHANGED:
            current = observed
        elif step == OperationStep.PACKAGE_REMOVED:
            if operation.kind != "uninstall" or observed is not None:
                raise InstallationError(
                    "Package absence checkpoint requires an uninstall operation."
                )
            current = None
        operation = replace(
            operation,
            phase="running",
            diagnostic=None,
            steps=tuple(dict.fromkeys((*operation.steps, step))),
        )
        record = replace(
            record, status="incomplete", operation=operation, current=current
        )
        write_record(directory, record, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.app_id)


def commit_installation(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    observed: InstalledSnapshot,
) -> InstallationInspection:
    """Activate only validated observed package, placement and saved support.

    :param directory: Explicit authority address.
    :param operation_id: Pending operation UUID.
    :param expected_revision: Last checkpoint revision.
    :param observed: Probe result after support/registration validation.
    :return: Ready inspection.
    """
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        required = {
            OperationStep.PACKAGE_CHANGED,
            OperationStep.RESOURCES_READY,
            OperationStep.SUPPORT_READY,
            OperationStep.REGISTRATION_READY,
        }
        if operation.kind not in {
            "install",
            "replace",
            "repair",
        } or not required.issubset(operation.steps):
            raise InstallationError(
                "Installation has not completed required checkpoints."
            )
        target = operation.intended
        if (
            target is None
            or observed.identity != target.identity
            or not target.source.matches_observation(observed.source)
            or observed.backend != target.backend
            or observed.placement != target.placement
        ):
            raise InstallationError(
                "Observed installation does not match intended target."
            )
        requires_record_proof = _requires_record_proof(observed.source)
        if requires_record_proof and (
            observed.distribution_record_digest is None
            or observed.source.digest is None
            or re.fullmatch(r"[0-9a-f]{64}", observed.source.digest) is None
        ):
            raise InstallationError(
                "Installed archive snapshot lacks acquisition or RECORD SHA-256 proof."
            )
        if operation.kind in {"repair", "replace"} and requires_record_proof:
            previous = record.current or record.last_successful
            if (
                previous is None
                or previous.distribution_record_digest is None
                or observed.distribution_record_digest
                != previous.distribution_record_digest
            ):
                raise InstallationError(
                    "Repair snapshot differs from the saved RECORD fingerprint."
                )
        if record.current is not None:
            recorded_source = _repair_source(
                replace(record, last_successful=None), target.source
            )
            if (
                recorded_source.digest is not None
                and recorded_source.digest != observed.source.digest
            ):
                raise InstallationError(
                    "Observed source differs from the recorded archive proof."
                )
        elif operation.kind == "repair":
            recorded_source = _repair_source(record, target.source)
            if (
                recorded_source.digest is not None
                and recorded_source.digest != observed.source.digest
            ):
                raise InstallationError(
                    "Observed source differs from the recorded archive proof."
                )
        ready = replace(
            record,
            status="ready",
            current=observed,
            last_successful=observed,
            placement=observed.placement,
            owned_outputs=observed.owned_outputs,
            operation=None,
        )
        write_record(directory, ready, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.app_id)


def fail_operation(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    diagnostic: InstallationDiagnostic,
) -> InstallationInspection:
    """Preserve pending recovery without claiming historical package success.

    :param directory: Explicit authority address.
    :param operation_id: Pending operation UUID.
    :param expected_revision: Last known checkpoint revision.
    :param diagnostic: Sanitized failure and safe retry guidance.
    :return: Incomplete inspection.
    """
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        assert record.operation is not None
        failed = replace(
            record,
            status="incomplete",
            operation=replace(
                record.operation, phase="failed", diagnostic=diagnostic
            ),
        )
        write_record(directory, failed, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.app_id)


def commit_uninstall(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
) -> UninstallCommit:
    """Retain reconnectable placement or delete authority irreversibly last.

    :param directory: Explicit authority namespace.
    :param operation_id: Expected pending removal UUID.
    :param expected_revision: Exact last checkpoint revision.
    :return: Retained inspection or retired generation without authority.
    """
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        if (
            operation.kind != "uninstall"
            or record.current is not None
            or OperationStep.PACKAGE_REMOVED not in operation.steps
        ):
            raise InstallationError("Program absence has not been observed.")
        if not operation.complete:
            retained = replace(
                record, status="removed-retained", operation=None
            )
            write_record(
                directory, retained, expected_revision=expected_revision
            )
            return UninstallCommit(
                "retained",
                directory,
                record.generation_id,
                inspect_installation(directory, app_id=record.app_id),
            )
        if OperationStep.DATA_REMOVED not in operation.steps:
            raise InstallationError("Requested data cleanup has not completed.")
        from apprc.user_files.installation.planning import resource_roots

        for _, root in resource_roots(record.placement):
            if (root.exists() or root.is_symlink()) and not (
                operation.forget_retained
                and any(
                    entry.path == root for entry in operation.inventory.retained
                )
            ):
                raise InstallationError(
                    "Tracked resource roots remain; authority retained."
                )
        leftovers = tuple(
            entry
            for entry in operation.inventory.entries
            if entry.path.exists() or entry.path.is_symlink()
        )
        if leftovers or (
            operation.inventory.retained and not operation.forget_retained
        ):
            raise InstallationError(
                "Tracked leftovers prevent complete retirement."
            )
        permitted = {"installation.json", "locks"}
        if any(entry.name not in permitted for entry in directory.iterdir()):
            raise InstallationError(
                "Installation support or unknown payload remains; authority retained."
            )
        (directory / "installation.json").unlink()
        return UninstallCommit("retired", directory, record.generation_id)
