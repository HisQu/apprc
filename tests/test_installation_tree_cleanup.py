"""Whole-directory removal under explicitly selected saved ownership."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apprc.definition.installation import InstallationError, InstallationHooks
from apprc.distribution.runtime._uninstall_controller import prepare_uninstall
from apprc.distribution.runtime.uninstall_handoff import _remove_inventory
from tests.support_installation import managed_installation


def _owned_cache(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "cache"
    root.mkdir()
    (root / ".apprc-owner.json").write_text(
        json.dumps(
            {"schema_version": 1, "app_id": "handoff-app", "category": "cache"}
        )
    )
    (root / "payload").write_text("application data")
    directory, _ = managed_installation(
        tmp_path, cache_root=root, hooks=InstallationHooks()
    )
    return directory, root


def test_default_removal_needs_no_application_callbacks(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    assert preparation.plan.complete
    assert any(
        entry.path == root and entry.kind == "tree"
        for entry in preparation.entries
    )
    assert (root / "payload").read_text() == "application data"


def test_keep_config_still_selects_cache_tree(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory, keep_config=True)
    assert preparation.can_execute and preparation.plan is not None
    assert preparation.plan.complete
    assert any(entry.resource == "cache" for entry in preparation.entries)
    assert root.exists()


def test_tree_removal_unlinks_inner_links_without_following(
    tmp_path: Path,
) -> None:
    directory, root = _owned_cache(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (root / "link").symlink_to(outside)
    preparation = prepare_uninstall(directory)
    assert preparation.plan is not None
    trees = tuple(
        entry
        for entry in preparation.plan.inventory.entries
        if entry.kind == "tree"
    )
    _remove_inventory(trees)
    assert not root.exists()
    assert outside.read_text() == "keep"


def test_replaced_tree_is_not_removed(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory)
    assert preparation.plan is not None
    root.rename(tmp_path / "previous-cache")
    root.mkdir()
    with pytest.raises(InstallationError, match="changed"):
        _remove_inventory(
            tuple(
                entry
                for entry in preparation.plan.inventory.entries
                if entry.kind == "tree"
            )
        )
    assert root.exists()


def test_unowned_data_is_preserved(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    (root / ".apprc-owner.json").unlink()
    preparation = prepare_uninstall(directory)
    assert not preparation.can_execute
    assert (root / "payload").exists()


def test_repository_option_rejects_managed_installation(tmp_path: Path) -> None:
    directory, _ = _owned_cache(tmp_path)
    with pytest.raises(InstallationError, match="editable"):
        prepare_uninstall(directory, remove_repository=True)


def test_repository_target_is_workspace_checkout_and_is_deferred(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from apprc.definition.installation import EditableCheckout, RuntimeSlot
    from apprc.user_files.installation.coordination import (
        installation_lock,
        write_record,
    )
    from apprc.user_files.installation.discovery import inspect_installation

    directory, _ = _owned_cache(tmp_path)
    repository = tmp_path / "checkout"
    member = repository / "apps" / "member"
    member.mkdir(parents=True)
    (repository / ".git").mkdir()
    environment = repository / ".venv"
    environment.mkdir()
    local_changes = repository / "untracked.txt"
    local_changes.write_text("local work")
    inspection = inspect_installation(directory, app_id="handoff-app")
    assert inspection.record is not None
    assert isinstance(inspection.record.active_runtime, RuntimeSlot)
    with installation_lock(directory):
        write_record(
            directory,
            replace(
                inspection.record,
                active_runtime=EditableCheckout(member, environment),
                retiring_runtime_ids=(
                    inspection.record.active_runtime.slot_id,
                ),
            ),
            expected_revision=inspection.revision,
        )
    preparation = prepare_uninstall(directory, remove_repository=True)
    assert preparation.can_execute and preparation.plan is not None
    selected = tuple(
        entry for entry in preparation.entries if entry.kind == "repository"
    )
    assert len(selected) == 1 and selected[0].path == repository
    _remove_inventory(selected)
    assert local_changes.read_text() == "local work"
    assert prepare_uninstall(
        directory, remove_repository=True, keep_config=True
    ).can_execute


def test_repository_finalizer_preserves_external_link_targets(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime import _process_waiter
    from apprc.distribution.runtime.uninstall_handoff import (
        _stage_repository_finalizer,
    )
    from apprc.user_files.installation.coordination import installation_lock
    from apprc.user_files.installation.inventory import tree_revision
    from tests.support_installation import owned_child_process

    repository = tmp_path / "checkout"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (repository / "link").symlink_to(outside)
    staging = tmp_path / "staging"
    recovery = staging / "recovery"
    staging.mkdir(mode=0o700)
    recovery.mkdir(parents=True, mode=0o700)
    _stage_repository_finalizer(staging)
    with installation_lock(tmp_path / "retired-installation"):
        pass
    proof = recovery / "repository.json"
    proof.write_text(
        json.dumps(
            {
                "directory": str(tmp_path / "retired-installation"),
                "app_id": "fixture",
                "generation_id": "00000000-0000-0000-0000-000000000000",
                "repository": str(repository),
                "revision": tree_revision(repository),
            }
        )
    )
    with owned_child_process() as process:
        token = _process_waiter.process_start_token(process.pid)
        assert process.stdin is not None
        process.stdin.write("exit\n")
        process.stdin.flush()
        process.wait(timeout=5)
        # > A fresh interpreter with no site packages must use the staged dependency.
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-S",
                str(staging / "repository_finalizer.py"),
                "--repository-plan",
                str(proof),
                "--parent",
                str(process.pid),
                "--parent-token",
                token,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert not repository.exists()
    assert outside.read_text() == "preserve"
    assert not staging.exists()


@pytest.mark.parametrize("caller_exited", [False, True])
def test_finalization_does_not_repeat_exit_handshake_for_running_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caller_exited: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from apprc.distribution.runtime import uninstall_handoff
    from uuid import uuid4

    directory = tmp_path / "installation"
    staging = tmp_path / "staging"
    recovery = staging / "recovery"
    staging.mkdir(mode=0o700)
    recovery.mkdir(mode=0o700)
    generation = str(uuid4())
    proof = {
        "directory": str(directory),
        "app_id": "fixture",
        "generation_id": generation,
        "support": [],
    }
    (recovery / "finalization.json").write_text(json.dumps(proof))
    value: uninstall_handoff.HandoffPlan = {
        "directory": str(directory),
        "app_id": "fixture",
        "generation_id": generation,
        "operation_id": str(uuid4()),
        "expected_revision": "a" * 64,
        "original_pid": 1,
        "original_start": "exited",
        "readiness_token": "a" * 32,
        "recovery_directory": str(recovery),
        "wait": False,
        "complete": True,
        "categories": [],
        "forget_retained": False,
        "inventory": [],
        "retained": [],
        "manager_executable": None,
        "manager_executable_revision": None,
    }
    waits: list[str] = []
    monkeypatch.setattr(
        uninstall_handoff,
        "_wait_for_caller_exit",
        lambda payload: waits.append(payload["operation_id"]),
    )
    uninstall_handoff._finalize_committed_handoff(
        staging / "handoff.json",
        value,
        recovery,
        expected_app_id="fixture",
        caller_exited=caller_exited,
    )
    assert len(waits) == (0 if caller_exited else 1)
    assert not staging.exists()
    reminder = (
        "Any retained editable checkout and development environment remain."
    )
    assert (reminder in capsys.readouterr().err) is (not caller_exited)


@pytest.mark.parametrize(
    "hooks",
    [
        InstallationHooks(initialize="fixture:initialize"),
        InstallationHooks(inventory="fixture:inventory"),
        InstallationHooks(cleanup="fixture:cleanup"),
        InstallationHooks(migrate="fixture:migrate"),
    ],
)
def test_registration_rejects_unusable_callbacks_before_initializing_resources(
    tmp_path: Path, hooks: InstallationHooks
) -> None:
    from apprc import AppRC, Paths
    from apprc.definition.installation import (
        OperationContext,
        InstallationPlacement,
        ProjectSnapshot,
        RuntimeSelection,
        RuntimeSlot,
    )
    from apprc.definition.paths import Layout
    from apprc.distribution.runtime.installation import _initialize_runtime
    from apprc.services.installation import InstallationManager
    from apprc.user_files.installation.operations import begin_operation
    from tests.support_installation import installation_record
    from uuid import uuid4

    directory = tmp_path / "installation"
    root = tmp_path / "cache"
    manager = InstallationManager(
        AppRC(app_id="coordination-fixture", paths=Paths(cache=True)).schema,
        directory=directory,
    )
    identity = installation_record().identity
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.14"),
        hooks=hooks,
    )
    placement = InstallationPlacement(
        Layout.native(), cache_dir=root, capabilities=frozenset({"cache"})
    )
    plan = manager.plan_install(identity, runtime, placement)
    current = begin_operation(plan)
    assert current.revision is not None
    context = OperationContext(
        directory, plan.operation_id, plan.generation_id, placement
    )
    with pytest.raises(InstallationError, match="AppRC declaration"):
        _initialize_runtime(
            manager,
            identity,
            runtime,
            "coordination-fixture",
            context,
            expected_revision=current.revision,
            manager_executable=None,
            expected_observations={},
        )
    assert not root.exists()


def test_support_leftovers_are_captured_and_links_preserve_targets(tmp_path):
    directory, _ = _owned_cache(tmp_path)
    names = (
        "receipt.json",
        "lifecycle.py",
        "uninstall.sh",
        "uninstall.cmd",
        "uninstall.ps1",
        "prepare-powershell-windows.cmd",
    )
    for name in names:
        (directory / name).write_text("obsolete support")
    nested = directory / "old" / "nested"
    nested.mkdir(parents=True)
    (nested / "extra").write_text("leftover")
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (directory / "outside-link").symlink_to(outside)
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    selected = tuple(
        entry
        for entry in preparation.plan.inventory.entries
        if entry.resource is None
    )
    assert all(
        any(entry.path == directory / name for entry in selected)
        for name in names
    )
    # Runtime retirement precedes support removal in the actual handoff.
    import shutil

    shutil.rmtree(directory / "runtimes")
    _remove_inventory(selected)
    assert outside.read_text() == "preserve"
    assert not (directory / "old").exists()


def test_support_link_recovery_refreshes_only_restored_link_identity(tmp_path):
    from apprc.definition.installation import CleanupInventory, InventoryEntry
    from apprc.distribution.runtime.uninstall_handoff import (
        _backup_support,
        _restore_support_links,
    )
    from apprc.user_files.installation.inventory import symlink_revision

    directory = tmp_path / "installation"
    directory.mkdir()
    recovery = tmp_path / "recovery"
    from apprc.user_files.app_home.permissions import (
        create_private_directory_if_missing,
    )

    create_private_directory_if_missing(recovery)
    outside = tmp_path / "outside"
    outside.write_text("keep external contents")
    link = directory / "link"
    link.symlink_to(outside)
    entry = InventoryEntry(link, "symlink", symlink_revision(link))
    inventory = CleanupInventory((entry,))
    _backup_support(inventory.entries, directory, recovery)
    _remove_inventory(inventory.entries)
    restored = _restore_support_links(recovery, directory, inventory)
    assert link.is_symlink() and link.readlink() == outside
    assert restored.entries[0].revision == symlink_revision(link)
    _remove_inventory(restored.entries)
    assert outside.read_text() == "keep external contents"


def test_keep_config_removes_cache_and_retires_authority(tmp_path):
    import shutil
    from apprc.definition.installation import OperationStep
    from apprc.user_files.installation.operations import (
        begin_operation,
        record_step,
        commit_uninstall,
    )

    config = tmp_path / "config"
    cache = tmp_path / "cache"
    for root, category in ((config, "config"), (cache, "cache")):
        root.mkdir()
        (root / ".apprc-owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": "handoff-app",
                    "category": category,
                }
            )
        )
        (root / "payload").write_text(category)
    directory, _runtime = managed_installation(
        tmp_path,
        config_root=config,
        cache_root=cache,
        hooks=InstallationHooks(),
    )
    preparation = prepare_uninstall(directory, keep_config=True)
    assert preparation.plan is not None
    plan = preparation.plan
    assert plan.complete and plan.forget_retained
    assert {entry.path for entry in plan.inventory.retained} == {config}
    assert "config" not in plan.categories and "cache" in plan.categories
    current = begin_operation(plan)
    assert current.revision is not None
    # Runtime retirement is a separate phase; exercise the retained-data commit boundary here.
    shutil.rmtree(directory / "runtimes")
    current = record_step(
        directory,
        operation_id=plan.operation_id,
        expected_revision=current.revision,
        step=OperationStep.RUNTIME_REMOVED,
    )
    _remove_inventory(plan.inventory.entries)
    assert current.revision is not None
    current = record_step(
        directory,
        operation_id=plan.operation_id,
        expected_revision=current.revision,
        step=OperationStep.DATA_REMOVED,
    )
    assert current.revision is not None
    result = commit_uninstall(
        directory,
        operation_id=plan.operation_id,
        expected_revision=current.revision,
    )
    assert result.kind == "retired"
    assert not (directory / "installation.json").exists()
    assert not cache.exists()
    assert (config / "payload").read_text() == "config"


def test_pending_uninstall_rejects_new_config_retention_choice(tmp_path):
    from apprc.user_files.installation.operations import begin_operation

    config = tmp_path / "config"
    config.mkdir()
    (config / ".apprc-owner.json").write_text(
        json.dumps(
            {"schema_version": 1, "app_id": "handoff-app", "category": "config"}
        )
    )
    settings = config / "settings"
    settings.write_text("preserve until confirmed removal")
    directory, _ = managed_installation(
        tmp_path, config_root=config, hooks=InstallationHooks()
    )
    preparation = prepare_uninstall(directory)
    assert preparation.plan is not None
    begin_operation(preparation.plan)
    with pytest.raises(InstallationError, match="retention differs"):
        prepare_uninstall(directory, keep_config=True)
    assert settings.read_text() == "preserve until confirmed removal"
