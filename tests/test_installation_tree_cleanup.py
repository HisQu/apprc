"""Whole-directory removal under explicitly selected saved ownership."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apprc.definition.installation import InstallationError, InstallationHooks
from apprc.distribution.runtime.controllers import prepare_uninstall
from apprc.distribution.runtime.removal import _remove_inventory
from tests.test_distribution_handoff_containment import _schema3_installation


def _owned_cache(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "cache"
    root.mkdir()
    (root / ".apprc-owner.json").write_text(
        json.dumps(
            {"schema_version": 1, "app_id": "handoff-app", "category": "cache"}
        )
    )
    (root / "payload").write_text("application data")
    directory, _ = _schema3_installation(
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


def test_keep_data_does_not_select_resource_trees(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory, keep_data=True)
    assert preparation.can_execute and preparation.plan is not None
    assert not preparation.plan.complete
    assert all(entry.resource is None for entry in preparation.entries)
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
    with pytest.raises(InstallationError, match="cannot be combined"):
        prepare_uninstall(directory, remove_repository=True, keep_data=True)


def test_repository_finalizer_preserves_external_link_targets(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime import _process_waiter
    from apprc.distribution.runtime.removal import _stage_repository_finalizer
    from apprc.user_files.installation.coordination import installation_lock
    from apprc.user_files.installation.inventory import tree_revision
    from tests.test_distribution_process_waiter import _owned_child

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
    with _owned_child() as process:
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
    from apprc.distribution.runtime import removal
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
    value: removal.HandoffPlan = {
        "directory": str(directory),
        "app_id": "fixture",
        "generation_id": generation,
        "operation_id": str(uuid4()),
        "expected_revision": "a" * 64,
        "original_pid": 1,
        "original_start": "exited",
        "readiness_token": "a" * 32,
        "recovery_directory": str(recovery),
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
        removal,
        "_wait_for_caller_exit",
        lambda payload: waits.append(payload["operation_id"]),
    )
    removal._finalize_committed_handoff(
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
    from tests.test_installation_coordination import _record
    from uuid import uuid4

    directory = tmp_path / "installation"
    root = tmp_path / "cache"
    manager = InstallationManager(
        AppRC(app_id="coordination-fixture", paths=Paths(cache=True)).schema,
        directory=directory,
    )
    identity = _record().identity
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
