"""Shared installation checkpoints, activation and failure recovery."""

from __future__ import annotations


import contextvars
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator
from uuid import UUID

from apprc.definition.installation import (
    EditableCheckout,
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstallationRecord,
    InstallPlan,
    OperationStep,
    OwnedOutput,
    RuntimeSlot,
)
from apprc.distribution.runtime import _command_publication
from apprc.distribution.runtime._install_progress import report, warn
from apprc.distribution.runtime._leases import (
    try_retire_runtime_slot,
)
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.operations import _matches_candidate

from ._resources import ResourceSnapshot, rollback_resources

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager

LOG = logging.getLogger(__name__)


_MAINTENANCE_GROUP: contextvars.ContextVar[str] = contextvars.ContextVar(
    "apprc_installation_maintenance_group", default="app"
)


@contextmanager
def installation_maintenance_group(name: str) -> Iterator[None]:
    """Bind native command-group metadata to one installation transaction."""
    if (
        not name
        or name in {".", ".."}
        or any(char in name for char in "/\\\x00")
    ):
        raise InstallationError("Maintenance group name is invalid.")
    token = _MAINTENANCE_GROUP.set(name)
    try:
        yield
    finally:
        _MAINTENANCE_GROUP.reset(token)


def require_update_record(
    inspection: InstallationInspection, expected: tuple[UUID, str]
) -> InstallationRecord:
    """Require the same ready installation that was offered to the user."""
    record = inspection.require_usable()
    if (
        record is None
        or record.status != "ready"
        or record.operation is not None
        or (record.generation_id, inspection.revision) != expected
    ):
        raise InstallationError(
            "The installation changed after update was requested. Run update again."
        )
    return record


def checkpoint(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    step: OperationStep,
    observed: RuntimeSlot | EditableCheckout | None = None,
) -> str:
    result = manager.record_step(
        operation_id=operation_id,
        expected_revision=revision,
        step=step,
        observed=observed,
    )
    if result.revision is None:
        raise InstallationError(
            f"{step.value} checkpoint has no authority revision."
        )
    return result.revision


def checkpoint_activation(
    manager: InstallationManager, operation_id: UUID, revision: str
) -> str:
    """Record the final pre-activation checkpoints for a published command."""
    for step in (OperationStep.SUPPORT_READY, OperationStep.REGISTRATION_READY):
        revision = checkpoint(manager, operation_id, revision, step)
    report("stage", "Saving Installation Record")
    return revision


def commit_activation(
    manager: InstallationManager,
    *,
    operation_id: UUID,
    revision: str,
    observed: RuntimeSlot | EditableCheckout,
    outputs: list[OwnedOutput],
    command: Path,
    version: str,
) -> InstallationInspection:
    """Commit the candidate, then publish optional registration metadata."""
    result = manager.commit_install(
        operation_id=operation_id,
        expected_revision=revision,
        observed=observed,
        owned_outputs=tuple(outputs),
    )
    report(
        "result",
        "Installation record",
        "RECORDED",
        manager.directory / "installation.json",
    )
    from apprc.distribution.runtime._windows_registration import (
        publish_registration,
    )
    from apprc.distribution.runtime._icons import ready_icon

    result, icon, icon_resolved = ready_icon(result, publish=True)
    result = publish_registration(
        result,
        version,
        command,
        _MAINTENANCE_GROUP.get(),
        icon=icon,
        preserve_icon=not icon_resolved,
    )
    return _finish_committed_installation(manager, result)


def _finish_committed_installation(
    manager: InstallationManager, inspection: InstallationInspection
) -> InstallationInspection:
    """Keep activation successful when postcommit housekeeping needs a retry."""
    try:
        inspection = _command_publication.cleanup_publication_images(
            manager, inspection
        )
        return (
            _retire_recorded_runtimes(manager)
            if inspection.record
            else inspection
        )
    except Exception as error:
        warn(LOG, "Installation succeeded; cleanup remains pending", error)
        return inspection


def _retire_recorded_runtimes(
    manager: InstallationManager,
) -> InstallationInspection:
    directory = manager.directory
    with installation_lock(directory):
        inspection = manager.inspect()
        record = inspection.record
        if record is None or inspection.revision is None:
            return inspection
        generation_id = record.generation_id
        for slot_id in record.retiring_runtime_ids:
            fresh = manager.inspect()
            if (
                fresh.record is None
                or fresh.revision is None
                or fresh.record.generation_id != generation_id
                or slot_id not in fresh.record.retiring_runtime_ids
            ):
                return fresh
            slot_directory = directory / "runtimes" / str(slot_id)
            try:
                if not try_retire_runtime_slot(slot_directory):
                    continue
                inspection = manager.record_runtime_retired(
                    slot_id=slot_id,
                    expected_revision=fresh.revision,
                    generation_id=generation_id,
                )
            except (InstallationError, OSError):
                return manager.inspect()
            if inspection.record is None or inspection.revision is None:
                break
        return inspection


def recover_installation_failure(
    manager: InstallationManager,
    plan: InstallPlan,
    prior: InstallationInspection,
    error: BaseException,
    *,
    resources: ResourceSnapshot,
    activation_started: bool,
    candidate_existed: bool = False,
) -> InstallationInspection | None:
    """Restore one caught install failure or retain honest recovery authority.

    Authority is restored last, only after exact-owned effects were reversed.
    Application callbacks remain responsible for their own data and side effects.

    :param manager: Installation whose lifecycle lock is already held.
    :param plan: Exact operation this invocation attempted.
    :param prior: Authority captured before this attempt.
    :param error: Original failure, preserved if rollback succeeds.
    :param resources: Resource existence before initialization.
    :param candidate_existed: Whether the managed candidate predates this attempt.
    :param activation_started: Whether activation was called before the failure.
    :return: Committed success after a read-back failure, otherwise ``None``.
    """
    try:
        latest = manager.inspect()
        record = latest.record
        if (
            activation_started
            and record is not None
            and record.status == "ready"
            and record.operation is None
            and record.generation_id == plan.generation_id
            and record.identity == plan.target.identity
            and record.command_name == plan.command_name
            and record.active_runtime is not None
            and _matches_candidate(plan.target.runtime, record.active_runtime)
        ):
            report(
                "result",
                "Installation record",
                "RECORDED",
                manager.directory / "installation.json",
            )
            warn(
                LOG,
                "Installation succeeded despite activation read-back error",
                error,
            )
            return _finish_committed_installation(manager, latest)
        if (
            (prior.record is None or prior.record.operation is None)
            and latest.revision == prior.revision
            and record == prior.record
        ):
            error.add_note("AppRC installation changes were rolled back.")
            return None
        if (
            record is None
            or record.operation is None
            or record.operation.operation_id != plan.operation_id
            or record.generation_id != plan.generation_id
            or latest.revision is None
        ):
            raise InstallationError(
                "Installation authority changed; rollback was not authorized."
            )
        operation = record.operation
        _command_publication.restore_commands(manager, operation.publication)
        rollback_resources(manager, plan, latest, resources)
        runtime = plan.target.runtime
        if isinstance(runtime, RuntimeSlot):
            if candidate_existed:
                raise InstallationError(
                    "The resumed runtime candidate retains preparation effects; resume or repair this exact attempt."
                )
            if not try_retire_runtime_slot(
                manager.directory / "runtimes" / str(runtime.slot_id)
            ):
                raise InstallationError(
                    "New runtime candidate is busy; retry recovery after its processes exit."
                )
        previous_operation = (
            prior.record.operation if prior.record is not None else None
        )
        _command_publication.discard_rollback_images(
            manager.directory,
            operation.publication,
            previous_operation.publication
            if previous_operation is not None
            else (),
        )
        manager.rollback_installation(
            operation_id=plan.operation_id,
            expected_revision=latest.revision,
            previous=prior.record,
        )
        error.add_note("AppRC installation changes were rolled back.")
        return None
    except BaseException as rollback_error:
        failures = [error, rollback_error]
        message = f"{error} AppRC installation rollback is incomplete: {rollback_error}"
        try:
            latest = manager.inspect()
            record = latest.record
            if (
                record is not None
                and record.operation is not None
                and record.operation.operation_id == plan.operation_id
                and latest.revision is not None
            ):
                manager.fail_operation(
                    operation_id=plan.operation_id,
                    expected_revision=latest.revision,
                    diagnostic=InstallationDiagnostic(
                        "runtime-incomplete",
                        message,
                        "Inspect the installation and retry the matching checkout command or original setup to resume recovery.",
                    ),
                )
        except BaseException as journal_error:
            failures.append(journal_error)
            message += f" Failure recording also failed: {journal_error}"
        raise InstallationError(
            message
            + " Inspect the installation and retry the matching checkout command or original setup to resume recovery."
        ) from BaseExceptionGroup(
            "Installation and rollback failures", failures
        )
