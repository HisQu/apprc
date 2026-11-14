"""Revision-checked authority transitions shared with standalone controllers.

Backend and provider actions are deliberately outside this module. Callers hold
one lifecycle lock around their ordinary Python composition; nested transition
calls reuse that lock and revalidate exact authority revisions.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from apprc.definition.installation import (
    CleanupInventory,
    EditableCheckout,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationTarget,
    OwnedOutput,
    PublicationOutput,
    RuntimeSlot,
    InstallPlan,
    MigrationInventory,
    MigrationPlan,
    OperationPlan,
    OperationStep,
    UninstallCommit,
    UninstallPlan,
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


def plan_install(
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    placement: InstallationPlacement,
    *,
    inspection: InstallationInspection,
    command_name: str | None = None,
) -> InstallPlan:
    """Plan runtime registration or replacement with exact CAS preconditions."""
    record = inspection.require_usable()
    selected_command = command_name or (
        identity.commands[0] if identity.commands else ""
    )
    if identity.app_id != inspection.app_id:
        raise InstallationError(
            "Target identity differs from captured discovery identity."
        )
    if selected_command not in identity.commands:
        raise InstallationError(
            "Primary command is not declared by the application."
        )
    validate_placement(placement, directory=inspection.directory)
    if isinstance(runtime, RuntimeSlot) and (
        runtime.version is not None or runtime.python_version is not None
    ):
        raise InstallationError(
            "New managed candidates cannot contain observations."
        )
    if record is not None and record.operation is not None:
        raise InstallationError(
            "Resume or repair the pending operation before planning another install."
        )
    if placement.layout.mode == "native" and placement.appdata_dir is not None:
        import sys

        from apprc.user_files.installation.validation import (
            check_native_appdata_container,
        )

        if sys.platform not in {"win32", "darwin"}:
            check_native_appdata_container(
                placement.appdata_dir.parent, app_id=identity.app_id
            )
    if record is not None and record.identity != identity:
        raise InstallationError(
            "Install identity differs from saved authority."
        )
    if record is not None and record.command_name != selected_command:
        raise InstallationError(
            "Primary command is retained across installation updates."
        )
    if record is not None and record.placement != placement:
        raise InstallationError(
            "Installation placement is retained; relocate resources with app migrate."
        )
    return InstallPlan(
        directory=inspection.directory,
        expected_revision=inspection.revision,
        expected_generation=record.generation_id
        if record is not None
        else None,
        target=InstallationTarget(identity, placement, runtime),
        operation_id=uuid4(),
        generation_id=record.generation_id if record is not None else uuid4(),
        command_name=selected_command,
        kind="replace"
        if record is not None and record.active_runtime is not None
        else "install",
    )


def plan_repair(
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    placement: InstallationPlacement,
    *,
    inspection: InstallationInspection,
) -> InstallPlan:
    """Resume the exact candidate or create a repair from active authority."""
    record = inspection.record
    if (
        record is None
        or record.identity != identity
        or identity.app_id != inspection.app_id
    ):
        raise InstallationError(
            "Repair requires a valid record for this application."
        )
    if placement != record.placement:
        raise InstallationError("Repair cannot relocate recorded resources.")
    if record.operation is not None and record.operation.kind not in {
        "install",
        "replace",
        "repair",
    }:
        raise InstallationError(
            "Resume or complete the pending operation before repair."
        )
    if record.operation is not None and record.operation.intended is not None:
        saved = record.operation.intended
        if saved.identity != identity:
            raise InstallationError("Pending candidate identity has changed.")
        if not isinstance(saved.runtime, RuntimeSlot):
            raise InstallationError(
                "Editable environments are developer-owned; restore it with uv sync --locked."
            )
        return InstallPlan(
            directory=inspection.directory,
            expected_revision=inspection.revision,
            expected_generation=record.generation_id,
            target=saved,
            operation_id=record.operation.operation_id,
            generation_id=record.generation_id,
            command_name=record.command_name,
            kind="repair",
        )
    if isinstance(record.active_runtime, EditableCheckout):
        raise InstallationError(
            "Editable environments are developer-owned; restore it with uv sync --locked."
        )
    if not isinstance(record.active_runtime, RuntimeSlot):
        raise InstallationError(
            "Repair requires a managed active or pending runtime."
        )
    if not isinstance(runtime, RuntimeSlot):
        raise InstallationError(
            "Managed repair requires a runtime slot candidate."
        )
    if (
        runtime.source != record.active_runtime.source
        or runtime.selection != record.active_runtime.selection
        or runtime.hooks != record.active_runtime.hooks
    ):
        raise InstallationError(
            "Repair must reuse active runtime source, selection and hooks."
        )
    candidate = replace(runtime, version=None, python_version=None)
    return InstallPlan(
        directory=inspection.directory,
        expected_revision=inspection.revision,
        expected_generation=record.generation_id,
        target=InstallationTarget(identity, record.placement, candidate),
        operation_id=uuid4(),
        generation_id=record.generation_id,
        command_name=record.command_name,
        kind="repair",
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
        record.identity.app_id,
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
    identity: InstallationIdentity | None = None,
    command_name: str | None = None,
) -> MigrationPlan:
    """Plan explicitly enumerated resource movement with bound app identity."""
    record = inspection.require_usable()
    if record is not None and record.identity.app_id != inspection.app_id:
        raise InstallationError(
            "Migration identity differs from captured host."
        )
    if record is not None and record.operation is not None:
        raise InstallationError(
            "Resume or complete the pending operation before migration."
        )
    if record is not None:
        if identity is not None and identity != record.identity:
            raise InstallationError(
                "Migration identity differs from saved authority."
            )
        if command_name is not None and command_name != record.command_name:
            raise InstallationError(
                "Migration command differs from saved authority."
            )
        identity = record.identity
        command_name = record.command_name
    if identity is None or command_name is None:
        raise InstallationError(
            "Initial migration needs exact application identity and primary command."
        )
    if (
        identity.app_id != inspection.app_id
        or command_name not in identity.commands
    ):
        raise InstallationError(
            "Migration identity or primary command does not match the application."
        )
    validate_placement(placement, directory=inspection.directory)
    if inventory.unknown:
        raise InstallationError(
            "Unknown payload requires a project-owned migration inventory."
        )
    return MigrationPlan(
        directory=inspection.directory,
        expected_revision=inspection.revision,
        expected_generation=record.generation_id
        if record is not None
        else None,
        app_id=inspection.app_id,
        operation_id=uuid4(),
        generation_id=record.generation_id if record is not None else uuid4(),
        placement=placement,
        inventory=inventory,
        quiescent=quiescent,
        identity=identity,
        command_name=command_name,
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
                or operation.intended.runtime != plan.target.runtime
                or operation.intended.placement != plan.target.placement
                or plan.command_name != record.command_name
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
            if isinstance(plan, InstallPlan):
                identity = plan.target.identity
                command_name = plan.command_name
            elif isinstance(plan, MigrationPlan):
                identity = plan.identity
                command_name = plan.command_name
            else:
                raise InstallationError(
                    "Initial removal requires saved installation authority."
                )
            if identity is None or command_name is None:
                raise InstallationError(
                    "Initial installation authority is incomplete."
                )
            record = InstallationRecord(
                schema_version=3,
                identity=identity,
                command_name=command_name,
                generation_id=generation,
                support_version=SUPPORT_VERSION,
                placement=placement,
                status="provisional",
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

            record = replace(
                record,
                migration=InstallationMigration(
                    plan.inventory.source_root,
                    plan.inventory.destination_root,
                    "staged",
                    plan.inventory,
                ),
            )
        write_record(
            plan.directory, record, expected_revision=plan.expected_revision
        )
        return inspect_installation(
            plan.directory, app_id=record.identity.app_id
        )


def _pending(
    directory: Path,
    operation_id: UUID,
    revision: str,
) -> InstallationRecord:
    import json
    from hashlib import sha256

    from apprc.user_files.installation.codec import decode_record

    content = (directory / "installation.json").read_bytes()
    if sha256(content).hexdigest() != revision:
        raise InstallationError("Installation operation revision changed.")
    value = json.loads(content)
    identity = value.get("identity") if isinstance(value, dict) else None
    app_id = identity.get("app_id") if isinstance(identity, dict) else None
    if not isinstance(app_id, str):
        raise InstallationError("Installation identity is invalid.")
    record = decode_record(content, app_id=app_id)
    if (
        record.operation is None
        or record.operation.operation_id != operation_id
    ):
        raise InstallationError("Installation operation is no longer active.")
    return record


def _matches_candidate(
    intended: RuntimeSlot | EditableCheckout,
    observed: RuntimeSlot | EditableCheckout,
) -> bool:
    if isinstance(intended, RuntimeSlot) and isinstance(observed, RuntimeSlot):
        return (
            intended.slot_id == observed.slot_id
            and intended.source == observed.source
            and intended.selection == observed.selection
            and intended.hooks == observed.hooks
            and (
                intended.version is None or intended.version == observed.version
            )
            and (
                intended.python_version is None
                or intended.python_version == observed.python_version
            )
        )
    return intended == observed


def record_step(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    step: OperationStep,
    observed: RuntimeSlot | EditableCheckout | None = None,
) -> InstallationInspection:
    """Persist an exact lifecycle checkpoint without replacing active authority."""
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        if (
            step == OperationStep.MIGRATION_HOOK_COMPLETED
            and operation.kind != "migrate"
        ):
            raise InstallationError(
                "Migration hook checkpoint requires a pending migration."
            )
        if step == OperationStep.RUNTIME_REMOVED:
            if operation.kind != "uninstall" or observed is not None:
                raise InstallationError(
                    "Runtime absence checkpoint requires uninstall."
                )
            record = replace(
                record, active_runtime=None, retiring_runtime_ids=()
            )
        elif operation.kind == "uninstall" and observed is not None:
            raise InstallationError(
                "Uninstall checkpoints cannot carry runtime observations."
            )
        elif observed is not None:
            candidate = operation.intended
            if candidate is None or not _matches_candidate(
                candidate.runtime, observed
            ):
                raise InstallationError(
                    "Observation differs from the pending runtime candidate."
                )
        operation = replace(
            operation,
            phase="running",
            diagnostic=None,
            steps=tuple(dict.fromkeys((*operation.steps, step))),
        )
        updated = replace(record, operation=operation, status="incomplete")
        write_record(directory, updated, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.identity.app_id)


def commit_installation(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    observed: RuntimeSlot | EditableCheckout,
    owned_outputs: tuple[OwnedOutput, ...] | None = None,
) -> InstallationInspection:
    """CAS-activate a validated candidate and retire only its prior managed slot."""
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        required = {
            OperationStep.RUNTIME_PREPARED,
            OperationStep.RUNTIME_VALIDATED,
            OperationStep.RESOURCES_READY,
            OperationStep.SUPPORT_READY,
            OperationStep.REGISTRATION_READY,
        }
        target = operation.intended
        if (
            operation.kind not in {"install", "replace", "repair"}
            or target is None
            or not _matches_candidate(target.runtime, observed)
            or not required.issubset(operation.steps)
        ):
            raise InstallationError(
                "Candidate has not completed required validated checkpoints."
            )
        if isinstance(observed, RuntimeSlot) and (
            observed.version is None or observed.python_version is None
        ):
            raise InstallationError(
                "Managed candidate lacks observed version metadata."
            )
        retiring = record.retiring_runtime_ids
        previous = record.active_runtime
        if isinstance(previous, RuntimeSlot) and (
            not isinstance(observed, RuntimeSlot)
            or previous.slot_id != observed.slot_id
        ):
            retiring = tuple(dict.fromkeys((*retiring, previous.slot_id)))
        output_values = list(
            record.owned_outputs if owned_outputs is None else owned_outputs
        )
        known_paths = {item.path for item in output_values}
        if operation.registration is not None:
            output_values = [
                item
                for item in output_values
                if item.path != operation.registration.path
            ]
            output_values.append(operation.registration)
            known_paths = {item.path for item in output_values}
        for item in operation.publication:
            for image in (item.previous, item.intended):
                if (
                    image is None
                    or image.content is None
                    or image.content in known_paths
                ):
                    continue
                output_values.append(
                    OwnedOutput("support", image.content, image.digest)
                )
                known_paths.add(image.content)
        ready = replace(
            record,
            status="ready",
            placement=target.placement,
            active_runtime=observed,
            retiring_runtime_ids=retiring,
            owned_outputs=tuple(output_values),
            operation=None,
        )
        write_record(directory, ready, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.identity.app_id)


def record_owned_outputs(
    directory: Path,
    *,
    app_id: str,
    expected_revision: str,
    generation_id: UUID,
    owned_outputs: tuple[OwnedOutput, ...],
) -> InstallationInspection:
    """Replace support-output ownership without changing the runtime generation.

    :param directory: Explicit installation authority address.
    :param app_id: Expected saved application identity.
    :param expected_revision: Exact authority revision from activation.
    :param generation_id: Generation whose shortcuts were published.
    :param owned_outputs: Exact support outputs observed after publication.
    :return: Updated authority at the same generation.
    """
    with installation_lock(directory):
        inspection = inspect_installation(directory, app_id=app_id)
        record = inspection.record
        if (
            record is None
            or inspection.revision != expected_revision
            or record.identity.app_id != app_id
            or record.generation_id != generation_id
            or record.status != "ready"
            or record.operation is not None
        ):
            raise InstallationError(
                "Installation changed before support outputs were recorded."
            )
        updated = replace(record, owned_outputs=owned_outputs)
        write_record(directory, updated, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=app_id)


def record_runtime_retired(
    directory: Path,
    *,
    slot_id: UUID,
    expected_revision: str,
    generation_id: UUID,
) -> InstallationInspection:
    """CAS-clear one listed slot after its exclusive claim confirms absence."""
    with installation_lock(directory):
        import json
        from hashlib import sha256

        from apprc.user_files.installation.codec import decode_record

        content = (directory / "installation.json").read_bytes()
        if sha256(content).hexdigest() != expected_revision:
            raise InstallationError(
                "Installation changed before runtime retirement was recorded."
            )
        value = json.loads(content)
        identity = value.get("identity") if isinstance(value, dict) else None
        app_id = identity.get("app_id") if isinstance(identity, dict) else None
        if not isinstance(app_id, str):
            raise InstallationError("Installation identity is invalid.")
        record = decode_record(content, app_id=app_id)
        if (
            record.generation_id != generation_id
            or slot_id not in record.retiring_runtime_ids
        ):
            raise InstallationError(
                "Runtime slot is not listed for this generation."
            )
        updated = replace(
            record,
            retiring_runtime_ids=tuple(
                candidate
                for candidate in record.retiring_runtime_ids
                if candidate != slot_id
            ),
        )
        write_record(directory, updated, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=app_id)


def record_publication(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    publication: tuple[PublicationOutput, ...],
) -> InstallationInspection:
    """Persist authenticated output intent before replacing command files."""
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        if operation.kind not in {"install", "replace", "repair"}:
            raise InstallationError(
                "Command publication requires a runtime operation."
            )
        outputs = {item.path for item in publication}
        if len(outputs) != len(publication):
            raise InstallationError("Publication output paths must be unique.")
        updated = replace(
            record, operation=replace(operation, publication=publication)
        )
        write_record(directory, updated, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.identity.app_id)


def record_registration(
    directory: Path,
    *,
    operation_id: UUID,
    expected_revision: str,
    registration: OwnedOutput,
) -> InstallationInspection:
    """Persist an exact HKCU value recipe before creating its registry key."""
    with installation_lock(directory):
        record = _pending(directory, operation_id, expected_revision)
        operation = record.operation
        assert operation is not None
        if operation.kind not in {"install", "replace", "repair"}:
            raise InstallationError(
                "Registry registration requires a runtime operation."
            )
        if registration.kind != "hkcu":
            raise InstallationError("Registry intent must be an HKCU output.")
        updated = replace(
            record, operation=replace(operation, registration=registration)
        )
        write_record(directory, updated, expected_revision=expected_revision)
        return inspect_installation(directory, app_id=record.identity.app_id)


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
        return inspect_installation(directory, app_id=record.identity.app_id)


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
            or record.active_runtime is not None
            or OperationStep.RUNTIME_REMOVED not in operation.steps
        ):
            raise InstallationError("Program absence has not been observed.")
        if not operation.complete:
            retained = replace(
                record,
                status="removed-retained",
                operation=None,
                owned_outputs=(),
            )
            write_record(
                directory, retained, expected_revision=expected_revision
            )
            return UninstallCommit(
                "retained",
                directory,
                record.generation_id,
                inspect_installation(directory, app_id=record.identity.app_id),
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
