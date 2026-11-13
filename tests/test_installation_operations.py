"""Transactional schema-3 installation transitions and recovery invariants."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    CleanupInventory,
    EditableCheckout,
    InstallationDiagnostic,
    InstallationError,
    InstallationHooks,
    InstallationIdentity,
    InstallationPlacement,
    InstallPlan,
    MigrationInventory,
    OperationStep,
    OwnedOutput,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    begin_operation,
    commit_installation,
    commit_uninstall,
    fail_operation,
    plan_install,
    plan_migration,
    plan_repair,
    plan_uninstall,
    record_owned_outputs,
    record_runtime_retired,
)
from apprc.user_files.installation.validation import validate_snapshot


def _identity() -> InstallationIdentity:
    return InstallationIdentity(
        "lifecycle-fixture",
        "lifecycle-fixture",
        "fixture",
        None,
        ("fixture",),
    )


def _source(*, commit: str = "a" * 40) -> ProjectSnapshot:
    return ProjectSnapshot(
        digest="b" * 64,
        lock_digest="c" * 64,
        commit=commit,
    )


def _candidate(
    *,
    source: ProjectSnapshot | None = None,
    hooks: InstallationHooks = InstallationHooks(),
) -> RuntimeSlot:
    return RuntimeSlot(
        uuid4(),
        source or _source(),
        RuntimeSelection("3.14"),
        hooks=hooks,
    )


def _prepare(
    directory: Path,
    *,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    placement: InstallationPlacement,
    command_name: str = "fixture",
) -> tuple[InstallPlan, str]:
    """Persist and checkpoint one candidate before activation."""
    plan = plan_install(
        identity,
        runtime,
        placement,
        inspection=inspect_installation(directory, app_id=identity.app_id),
        command_name=command_name,
    )
    inspection = begin_operation(plan)
    assert inspection.revision is not None
    observed = (
        replace(runtime, version="1.0", python_version="3.14.1")
        if isinstance(runtime, RuntimeSlot)
        else runtime
    )
    for step in (
        OperationStep.SOURCE_VERIFIED,
        OperationStep.RUNTIME_PREPARED,
        OperationStep.RUNTIME_VALIDATED,
        OperationStep.RESOURCES_READY,
        OperationStep.SUPPORT_READY,
        OperationStep.REGISTRATION_READY,
    ):
        inspection = record_step(
            directory,
            operation_id=plan.operation_id,
            expected_revision=inspection.revision,
            step=step,
            observed=observed if step == OperationStep.RUNTIME_VALIDATED else None,
        )
        assert inspection.revision is not None
    return plan, inspection.revision


def _install(tmp_path: Path) -> tuple[Path, RuntimeSlot]:
    directory = tmp_path / "installation"
    candidate = _candidate()
    placement = InstallationPlacement(Layout.native())
    plan, revision = _prepare(
        directory,
        identity=_identity(),
        runtime=candidate,
        placement=placement,
    )
    observed = replace(candidate, version="1.0", python_version="3.14.1")
    ready = commit_installation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=revision,
        observed=observed,
    )
    assert ready.status == "ready"
    assert ready.record is not None and ready.record.active_runtime == observed
    return directory, observed


def test_program_only_removal_retains_placement_without_active_runtime(
    tmp_path: Path,
) -> None:
    directory, active = _install(tmp_path)
    inspection = inspect_installation(directory, app_id=_identity().app_id)
    assert inspection.record is not None and inspection.revision is not None
    plan = plan_uninstall(
        inspection.record,
        directory=directory,
        revision=inspection.revision,
        inventory=CleanupInventory(),
    )
    pending = begin_operation(plan)
    assert pending.revision is not None
    absent = record_step(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        step=OperationStep.RUNTIME_REMOVED,
    )
    assert absent.revision is not None
    result = commit_uninstall(
        directory,
        operation_id=plan.operation_id,
        expected_revision=absent.revision,
    )
    assert result.kind == "retained"
    assert result.inspection is not None and result.inspection.record is not None
    assert result.inspection.record.active_runtime is None
    assert result.inspection.record.placement == InstallationPlacement(Layout.native())


def test_complete_uninstall_retires_authority_and_rejects_stale_retry(
    tmp_path: Path,
) -> None:
    directory, active = _install(tmp_path)
    inspection = inspect_installation(directory, app_id=_identity().app_id)
    assert inspection.record is not None and inspection.revision is not None
    plan = plan_uninstall(
        inspection.record,
        directory=directory,
        revision=inspection.revision,
        complete=True,
        inventory=CleanupInventory(),
    )
    current = begin_operation(plan)
    for step in (OperationStep.RUNTIME_REMOVED, OperationStep.DATA_REMOVED):
        assert current.revision is not None
        current = record_step(
            directory,
            operation_id=plan.operation_id,
            expected_revision=current.revision,
            step=step,
        )
    assert current.revision is not None
    result = commit_uninstall(
        directory,
        operation_id=plan.operation_id,
        expected_revision=current.revision,
    )
    assert result.kind == "retired"
    assert inspect_installation(directory, app_id=_identity().app_id).status == "missing"
    with pytest.raises(FileNotFoundError):
        fail_operation(
            directory,
            operation_id=plan.operation_id,
            expected_revision=current.revision,
            diagnostic=InstallationDiagnostic("late", "late", "inspect"),
        )

def test_failed_replacement_keeps_active_runtime_access_and_stale_writers_fail(
    tmp_path: Path,
) -> None:
    directory, active = _install(tmp_path)
    before = inspect_installation(directory, app_id=_identity().app_id)
    assert before.record is not None
    stale_snapshot = before.snapshot
    replacement = _candidate(source=_source(commit="d" * 40))
    plan = plan_install(
        _identity(),
        replacement,
        before.record.placement,
        inspection=before,
        command_name="fixture",
    )
    pending = begin_operation(plan)
    assert pending.revision is not None
    failed = fail_operation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        diagnostic=InstallationDiagnostic(
            "runtime-failed", "Runtime validation failed.", "Repair the saved candidate."
        ),
    )
    assert failed.record is not None and failed.record.operation is not None
    assert failed.record.active_runtime == active
    assert failed.record.operation.intended is not None
    assert failed.require_usable() == failed.record

    fresh = inspect_installation(directory, app_id=_identity().app_id)
    assert fresh.record is not None and fresh.record.active_runtime == active
    validate_snapshot(fresh.snapshot, app_id=_identity().app_id)
    with pytest.raises(InstallationError, match="authority changed"):
        validate_snapshot(stale_snapshot, app_id=_identity().app_id)


def test_repair_resumes_exact_pending_candidate_without_reselecting_source(
    tmp_path: Path,
) -> None:
    directory, active = _install(tmp_path)
    current = inspect_installation(directory, app_id=_identity().app_id)
    candidate = _candidate(source=_source(commit="d" * 40))
    plan = plan_install(
        _identity(), candidate, current.record.placement, inspection=current
    )
    pending = begin_operation(plan)
    failed = fail_operation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        diagnostic=InstallationDiagnostic("sync-failed", "sync failed", "retry"),
    )
    repair = plan_repair(
        _identity(),
        _candidate(source=active.source),
        failed.record.placement,
        inspection=failed,
    )
    assert repair.operation_id == plan.operation_id
    assert repair.target == plan.target
    resumed = begin_operation(repair)
    assert resumed.revision == failed.revision


def test_activation_lists_previous_managed_slot_and_clears_it_by_revision(
    tmp_path: Path,
) -> None:
    directory, old = _install(tmp_path)
    before = inspect_installation(directory, app_id=_identity().app_id)
    candidate = _candidate(source=_source(commit="d" * 40))
    plan, revision = _prepare(
        directory,
        identity=_identity(),
        runtime=candidate,
        placement=before.record.placement,
    )
    observed = replace(candidate, version="2.0", python_version="3.14.1")
    activated = commit_installation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=revision,
        observed=observed,
    )
    assert activated.record is not None and activated.revision is not None
    assert activated.record.active_runtime == observed
    assert activated.record.retiring_runtime_ids == (old.slot_id,)
    retired = record_runtime_retired(
        directory,
        slot_id=old.slot_id,
        expected_revision=activated.revision,
        generation_id=activated.record.generation_id,
    )
    assert retired.record is not None
    assert retired.record.retiring_runtime_ids == ()
    with pytest.raises(InstallationError, match="changed"):
        record_runtime_retired(
            directory,
            slot_id=old.slot_id,
            expected_revision=activated.revision,
            generation_id=activated.record.generation_id,
        )


def test_owned_outputs_update_is_generation_and_revision_cas(
    tmp_path: Path,
) -> None:
    directory, active_runtime = _install(tmp_path)
    before = inspect_installation(directory, app_id=_identity().app_id)
    assert before.record is not None and before.revision is not None
    output = OwnedOutput(
        "shortcut", str(tmp_path / "fixture.desktop"), "d" * 64
    )
    updated = record_owned_outputs(
        directory,
        app_id=_identity().app_id,
        expected_revision=before.revision,
        generation_id=before.record.generation_id,
        owned_outputs=(output,),
    )
    assert updated.record is not None and updated.revision is not None
    assert updated.record.owned_outputs == (output,)
    assert updated.record.active_runtime == active_runtime
    assert updated.record.generation_id == before.record.generation_id
    with pytest.raises(InstallationError, match="changed"):
        record_owned_outputs(
            directory,
            app_id=_identity().app_id,
            expected_revision=before.revision,
            generation_id=before.record.generation_id,
            owned_outputs=(),
        )

def test_managed_to_editable_switch_retires_only_the_managed_slot(
    tmp_path: Path,
) -> None:
    directory, managed = _install(tmp_path)
    checkout = tmp_path / "checkout"
    environment = checkout / ".venv"
    checkout.mkdir()
    environment.mkdir()
    sentinel = environment / "owned-by-developer"
    sentinel.write_text("keep", encoding="utf-8")
    inspection = inspect_installation(directory, app_id=_identity().app_id)
    editable = EditableCheckout(checkout, environment)
    plan, revision = _prepare(
        directory,
        identity=_identity(),
        runtime=editable,
        placement=inspection.record.placement,
    )
    switched = commit_installation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=revision,
        observed=editable,
    )
    assert switched.record is not None
    assert switched.record.active_runtime == editable
    assert switched.record.retiring_runtime_ids == (managed.slot_id,)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_initial_resource_migration_requires_and_persists_real_identity(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    source_root = tmp_path / "legacy"
    destination_root = tmp_path / "current"
    source_root.mkdir()
    destination_root.mkdir()
    inventory = MigrationInventory(source_root, destination_root)
    inspection = inspect_installation(directory, app_id=_identity().app_id)
    placement = InstallationPlacement(Layout.native())
    with pytest.raises(InstallationError, match="exact application identity"):
        plan_migration(
            inspection, placement, inventory=inventory, quiescent=True
        )

    plan = plan_migration(
        inspection,
        placement,
        inventory=inventory,
        quiescent=True,
        identity=_identity(),
        command_name="fixture",
    )
    pending = begin_operation(plan)
    assert pending.record is not None
    assert pending.record.identity == _identity()
    assert pending.record.command_name == "fixture"
    assert pending.record.operation is not None

def test_migration_hook_is_pending_checkpointed_and_skipped_on_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apprc.user_files.installation.migration as migration_engine

    directory = tmp_path / "installation"
    source_root = tmp_path / "legacy"
    destination_root = tmp_path / "current"
    source_root.mkdir()
    destination_root.mkdir()
    candidate = _candidate(
        hooks=InstallationHooks(migrate="fixture:migrate")
    )
    plan, revision = _prepare(
        directory,
        identity=_identity(),
        runtime=candidate,
        placement=InstallationPlacement(Layout.native()),
    )
    observed = replace(candidate, version="1.0", python_version="3.14.1")
    active = commit_installation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=revision,
        observed=observed,
    )
    assert active.record is not None
    migration_plan = plan_migration(
        active,
        active.record.placement,
        inventory=MigrationInventory(source_root, destination_root),
        quiescent=True,
    )
    bridge_calls: list[dict[str, object]] = []

    def bridge(*_args: object, **kwargs: object) -> dict[str, object]:
        pending = inspect_installation(directory, app_id=_identity().app_id)
        assert pending.record is not None
        assert pending.record.operation is not None
        assert pending.record.operation.kind == "migrate"
        assert kwargs["expected_revision"] == pending.revision
        bridge_calls.append(kwargs)
        return {"completed": True}

    def stop_before_sdk_moves(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated interruption after provider checkpoint")

    monkeypatch.setattr(migration_engine, "application_bridge", bridge)
    monkeypatch.setattr(
        migration_engine, "_resume_migration", stop_before_sdk_moves
    )
    with pytest.raises(RuntimeError, match="provider checkpoint"):
        migration_engine.execute_migration(
            migration_plan,
            environment={"FIXTURE_ENV": "preserved"},
        )

    failed = inspect_installation(directory, app_id=_identity().app_id)
    assert failed.record is not None and failed.record.operation is not None
    assert failed.revision is not None
    assert (
        OperationStep.MIGRATION_HOOK_COMPLETED
        in failed.record.operation.steps
    )
    assert failed.record.operation.phase == "failed"
    assert len(bridge_calls) == 1
    assert bridge_calls[0]["environment"] == {"FIXTURE_ENV": "preserved"}
    monkeypatch.undo()
    monkeypatch.setattr(
        migration_engine,
        "application_bridge",
        lambda *_args, **_kwargs: pytest.fail(
            "completed migration hook was invoked again"
        ),
    )
    resumed = migration_engine.resume_migration(
        directory,
        operation_id=migration_plan.operation_id,
        expected_revision=failed.revision,
    )
    assert resumed.record is not None
    assert resumed.record.operation is None
    assert resumed.record.migration is not None
    assert resumed.record.migration.phase == "activated"


def test_migration_hook_failure_records_failed_pending_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apprc.user_files.installation.migration as migration_engine

    directory = tmp_path / "installation"
    source_root = tmp_path / "legacy"
    destination_root = tmp_path / "current"
    source_root.mkdir()
    destination_root.mkdir()
    candidate = _candidate(
        hooks=InstallationHooks(migrate="fixture:migrate")
    )
    install_plan, revision = _prepare(
        directory,
        identity=_identity(),
        runtime=candidate,
        placement=InstallationPlacement(Layout.native()),
    )
    observed = replace(candidate, version="1.0", python_version="3.14.1")
    active = commit_installation(
        directory,
        operation_id=install_plan.operation_id,
        expected_revision=revision,
        observed=observed,
    )
    assert active.record is not None
    migration_plan = plan_migration(
        active,
        active.record.placement,
        inventory=MigrationInventory(source_root, destination_root),
        quiescent=True,
    )

    def fail_hook(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("provider migration failed")

    monkeypatch.setattr(migration_engine, "application_bridge", fail_hook)
    with pytest.raises(RuntimeError, match="provider migration failed"):
        migration_engine.execute_migration(migration_plan)

    failed = inspect_installation(directory, app_id=_identity().app_id)
    assert failed.record is not None and failed.record.operation is not None
    assert failed.record.operation.phase == "failed"
    assert failed.record.operation.diagnostic is not None
    assert failed.record.operation.diagnostic.code == "migration-failed"
    assert OperationStep.MIGRATION_HOOK_COMPLETED not in failed.record.operation.steps
