"""Truthful pending, failure, retention and irreversible retirement transitions."""

from dataclasses import replace
from pathlib import Path

import pytest

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
    InstalledSnapshot,
    OperationStep,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    begin_operation,
    commit_installation,
    commit_uninstall,
    fail_operation,
    plan_install,
    plan_repair,
    plan_uninstall,
    record_step,
)


def _install(
    tmp_path: Path,
    *,
    source: InstallationSource | None = None,
    observed_source: InstallationSource | None = None,
) -> tuple[Path, InstalledSnapshot]:
    directory = tmp_path / "installation"
    identity = InstallationIdentity(
        "lifecycle-fixture", "lifecycle-fixture", "fixture", None, ("fixture",)
    )
    placement = InstallationPlacement(Layout.native())
    source = source or InstallationSource("editable", str(tmp_path / "project"))
    backend = UvToolTarget(
        tmp_path / "uv", tmp_path / "tools", tmp_path / "bin"
    )
    plan = plan_install(
        identity,
        source,
        placement,
        backend,
        inspection=inspect_installation(directory, app_id=identity.app_id),
    )
    observed_source = observed_source or source
    if (
        observed_source.kind == "index"
        and observed_source.requirement.startswith("git+https://github.com/")
        and observed_source.digest is None
    ):
        observed_source = replace(observed_source, digest="b" * 64)
    observed = InstalledSnapshot(
        identity,
        "1.0",
        observed_source,
        placement,
        backend,
        tmp_path / "tools" / "fixture",
        tmp_path / "tools" / "fixture" / "python",
        (),
        distribution_record_digest=(
            "a" * 64
            if observed_source.kind == "release-sdist"
            or (
                observed_source.kind == "index"
                and observed_source.requirement.startswith(
                    "git+https://github.com/"
                )
            )
            else None
        ),
    )
    with installation_lock(directory):
        current = begin_operation(plan)
        for step in (
            OperationStep.PACKAGE_CHANGED,
            OperationStep.RESOURCES_READY,
            OperationStep.SUPPORT_READY,
            OperationStep.REGISTRATION_READY,
        ):
            assert current.revision is not None
            current = record_step(
                directory,
                operation_id=plan.operation_id,
                expected_revision=current.revision,
                step=step,
                observed=observed
                if step == OperationStep.PACKAGE_CHANGED
                else None,
            )
        assert current.revision is not None
        commit_installation(
            directory,
            operation_id=plan.operation_id,
            expected_revision=current.revision,
            observed=observed,
        )
    return directory, observed


def test_program_only_removal_retains_reconnectable_history(
    tmp_path: Path,
) -> None:
    directory, observed = _install(tmp_path)
    current = inspect_installation(directory, app_id=observed.identity.app_id)
    assert current.record is not None and current.revision is not None
    plan = plan_uninstall(
        current.record,
        directory=directory,
        revision=current.revision,
        inventory=CleanupInventory(),
    )
    pending = begin_operation(plan)
    assert pending.revision is not None
    absent = record_step(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        step=OperationStep.PACKAGE_REMOVED,
    )
    assert absent.revision is not None
    result = commit_uninstall(
        directory,
        operation_id=plan.operation_id,
        expected_revision=absent.revision,
    )
    assert result.kind == "retained"
    assert (
        result.inspection is not None and result.inspection.record is not None
    )
    assert result.inspection.record.current is None
    assert result.inspection.record.last_successful == observed
    assert result.inspection.record.placement == observed.placement


def test_replacement_failure_preserves_history_not_live_package(
    tmp_path: Path,
) -> None:
    directory, observed = _install(tmp_path)
    current = inspect_installation(directory, app_id=observed.identity.app_id)
    plan = plan_install(
        observed.identity,
        observed.source,
        observed.placement,
        observed.backend,
        inspection=current,
    )
    pending = begin_operation(plan)
    assert pending.revision is not None
    changed = record_step(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        step=OperationStep.PACKAGE_CHANGED,
    )
    assert changed.revision is not None
    failed = fail_operation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=changed.revision,
        diagnostic=InstallationDiagnostic(
            "backend-failed", "Installation failed.", "Repair exact source."
        ),
    )
    assert failed.record is not None
    assert failed.record.current is None
    assert failed.record.last_successful == observed
    with pytest.raises(InstallationError):
        failed.require_usable()


def test_complete_commit_is_irreversible_and_stale_retry_cannot_recreate(
    tmp_path: Path,
) -> None:
    directory, observed = _install(tmp_path)
    current = inspect_installation(directory, app_id=observed.identity.app_id)
    assert current.record is not None and current.revision is not None
    plan = plan_uninstall(
        current.record,
        directory=directory,
        revision=current.revision,
        complete=True,
        inventory=CleanupInventory(),
    )
    pending = begin_operation(plan)
    for step in (OperationStep.PACKAGE_REMOVED, OperationStep.DATA_REMOVED):
        assert pending.revision is not None
        pending = record_step(
            directory,
            operation_id=plan.operation_id,
            expected_revision=pending.revision,
            step=step,
        )
    assert pending.revision is not None
    result = commit_uninstall(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
    )
    assert result.kind == "retired"
    assert (
        inspect_installation(directory, app_id=observed.identity.app_id).status
        == "missing"
    )
    with pytest.raises(FileNotFoundError):
        fail_operation(
            directory,
            operation_id=plan.operation_id,
            expected_revision=pending.revision,
            diagnostic=InstallationDiagnostic(
                "late", "Must not recreate.", "Inspect."
            ),
        )
    assert not (directory / "installation.json").exists()


def test_repair_resumes_matching_failed_operation_without_changing_generation(
    tmp_path: Path,
) -> None:
    directory, observed = _install(tmp_path)
    current = inspect_installation(directory, app_id=observed.identity.app_id)
    replacement = plan_install(
        observed.identity,
        observed.source,
        observed.placement,
        observed.backend,
        inspection=current,
    )
    pending = begin_operation(replacement)
    assert pending.revision is not None
    changed = record_step(
        directory,
        operation_id=replacement.operation_id,
        expected_revision=pending.revision,
        step=OperationStep.PACKAGE_CHANGED,
    )
    assert changed.revision is not None
    failed = fail_operation(
        directory,
        operation_id=replacement.operation_id,
        expected_revision=changed.revision,
        diagnostic=InstallationDiagnostic(
            "backend-failed",
            "Replacement failed.",
            "Repair the recorded target.",
        ),
    )
    assert failed.record is not None and failed.record.operation is not None
    generation_id = failed.record.generation_id
    operation_id = failed.record.operation.operation_id
    steps = failed.record.operation.steps

    repair = plan_repair(
        observed.identity,
        observed.source,
        observed.placement,
        observed.backend,
        inspection=failed,
    )
    resumed = begin_operation(repair)

    assert repair.kind == "repair"
    assert repair.generation_id == generation_id
    assert repair.operation_id == operation_id
    assert resumed.revision == failed.revision
    assert resumed.record is not None and resumed.record.operation is not None
    assert resumed.record.operation.steps == steps
    assert resumed.record.generation_id == generation_id


def test_repair_retains_saved_archive_proof_and_rejects_digest_swap(
    tmp_path: Path,
) -> None:
    source = InstallationSource(
        "index",
        "git+https://github.com/example/project.git@" + "a" * 40,
    )
    digest = "b" * 64
    observed_source = InstallationSource(
        source.kind, source.requirement, digest=digest
    )
    directory, observed = _install(
        tmp_path, source=source, observed_source=observed_source
    )
    current = inspect_installation(directory, app_id=observed.identity.app_id)

    ready_repair = plan_repair(
        observed.identity,
        source,
        observed.placement,
        observed.backend,
        inspection=current,
    )
    assert ready_repair.target.source.digest == digest
    conflicting = InstallationSource(
        source.kind, source.requirement, digest="c" * 64
    )
    with pytest.raises(InstallationError, match="recorded source proof"):
        plan_repair(
            observed.identity,
            conflicting,
            observed.placement,
            observed.backend,
            inspection=current,
        )

    replacement = plan_install(
        observed.identity,
        source,
        observed.placement,
        observed.backend,
        inspection=current,
    )
    pending = begin_operation(replacement)
    assert pending.revision is not None
    failed = fail_operation(
        directory,
        operation_id=replacement.operation_id,
        expected_revision=pending.revision,
        diagnostic=InstallationDiagnostic(
            "interrupted", "Replacement stopped.", "Resume the repair."
        ),
    )
    pending_repair = plan_repair(
        observed.identity,
        source,
        observed.placement,
        observed.backend,
        inspection=failed,
    )
    assert pending_repair.target.source.digest == digest
    with pytest.raises(InstallationError, match="recorded source proof"):
        plan_repair(
            observed.identity,
            conflicting,
            observed.placement,
            observed.backend,
            inspection=failed,
        )
    resumed = begin_operation(pending_repair)
    assert resumed.record is not None and resumed.record.operation is not None
    assert resumed.record.operation.operation_id == replacement.operation_id


def test_repair_rejects_record_replacement_before_checkpoint_overwrites_saved(
    tmp_path: Path,
) -> None:
    source = InstallationSource(
        "index",
        "git+https://github.com/example/project.git@" + "a" * 40,
    )
    observed_source = replace(source, digest="b" * 64)
    directory, observed = _install(
        tmp_path, source=source, observed_source=observed_source
    )
    inspection = inspect_installation(
        directory, app_id=observed.identity.app_id
    )
    repair = plan_repair(
        observed.identity,
        source,
        observed.placement,
        observed.backend,
        inspection=inspection,
    )
    pending = begin_operation(repair)
    assert pending.revision is not None
    with pytest.raises(InstallationError, match="saved RECORD fingerprint"):
        record_step(
            directory,
            operation_id=repair.operation_id,
            expected_revision=pending.revision,
            step=OperationStep.PACKAGE_CHANGED,
            observed=replace(observed, distribution_record_digest="c" * 64),
        )
    unchanged = inspect_installation(directory, app_id=observed.identity.app_id)
    assert unchanged.revision == pending.revision
    assert unchanged.record is not None
    assert unchanged.record.current == observed
    assert unchanged.record.operation is not None
    assert unchanged.record.operation.operation_id == repair.operation_id


def test_pending_replace_repair_keeps_its_new_record_fingerprint(
    tmp_path: Path,
) -> None:
    original = InstallationSource(
        "index",
        "git+https://github.com/example/project.git@" + "a" * 40,
        digest="b" * 64,
    )
    directory, previous = _install(
        tmp_path, source=original, observed_source=original
    )
    inspection = inspect_installation(
        directory, app_id=previous.identity.app_id
    )
    replacement_source = InstallationSource(
        "index",
        "git+https://github.com/example/project.git@" + "c" * 40,
    )
    replacement = plan_install(
        previous.identity,
        replacement_source,
        previous.placement,
        previous.backend,
        inspection=inspection,
    )
    pending = begin_operation(replacement)
    assert pending.revision is not None
    cleared = record_step(
        directory,
        operation_id=replacement.operation_id,
        expected_revision=pending.revision,
        step=OperationStep.PACKAGE_CHANGED,
    )
    assert cleared.revision is not None
    replacement_observation = replace(
        previous,
        source=replace(replacement_source, digest="d" * 64),
        distribution_record_digest="e" * 64,
    )
    captured = record_step(
        directory,
        operation_id=replacement.operation_id,
        expected_revision=cleared.revision,
        step=OperationStep.PACKAGE_CHANGED,
        observed=replacement_observation,
    )
    repair = plan_repair(
        previous.identity,
        replacement_source,
        previous.placement,
        previous.backend,
        inspection=captured,
    )
    resumed = begin_operation(repair)
    assert resumed.revision == captured.revision
    assert resumed.record is not None
    assert resumed.record.current == replacement_observation
    assert resumed.record.last_successful == previous

    assert captured.revision is not None
    with pytest.raises(InstallationError, match="saved RECORD fingerprint"):
        record_step(
            directory,
            operation_id=repair.operation_id,
            expected_revision=captured.revision,
            step=OperationStep.PACKAGE_CHANGED,
            observed=replace(
                replacement_observation,
                distribution_record_digest="f" * 64,
            ),
        )
    unchanged = inspect_installation(directory, app_id=previous.identity.app_id)
    assert unchanged.revision == captured.revision
    assert unchanged.record is not None
    assert unchanged.record.current == replacement_observation
    current = unchanged
    for step in (
        OperationStep.RESOURCES_READY,
        OperationStep.SUPPORT_READY,
        OperationStep.REGISTRATION_READY,
    ):
        assert current.revision is not None
        current = record_step(
            directory,
            operation_id=repair.operation_id,
            expected_revision=current.revision,
            step=step,
        )
    assert current.revision is not None
    completed = commit_installation(
        directory,
        operation_id=repair.operation_id,
        expected_revision=current.revision,
        observed=replacement_observation,
    )
    assert completed.status == "ready"
    assert completed.record is not None
    assert completed.record.current == replacement_observation
