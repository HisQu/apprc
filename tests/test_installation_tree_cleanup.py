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
    (root / ".apprc-owner.json").write_text(json.dumps({"schema_version": 1, "app_id": "handoff-app", "category": "cache"}))
    (root / "payload").write_text("application data")
    directory, _ = _schema3_installation(tmp_path, cache_root=root, hooks=InstallationHooks())
    return directory, root


def test_default_removal_needs_no_application_callbacks(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    assert preparation.plan.complete
    assert any(entry.path == root and entry.kind == "tree" for entry in preparation.entries)
    assert (root / "payload").read_text() == "application data"


def test_keep_data_does_not_select_resource_trees(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    preparation = prepare_uninstall(directory, keep_data=True)
    assert preparation.can_execute and preparation.plan is not None
    assert not preparation.plan.complete
    assert all(entry.resource is None for entry in preparation.entries)
    assert root.exists()


def test_tree_removal_unlinks_inner_links_without_following(tmp_path: Path) -> None:
    directory, root = _owned_cache(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (root / "link").symlink_to(outside)
    preparation = prepare_uninstall(directory)
    assert preparation.plan is not None
    trees = tuple(entry for entry in preparation.plan.inventory.entries if entry.kind == "tree")
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
        _remove_inventory(tuple(entry for entry in preparation.plan.inventory.entries if entry.kind == "tree"))
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


def test_repository_target_is_workspace_checkout_and_is_deferred(tmp_path: Path) -> None:
    from dataclasses import replace
    from apprc.definition.installation import EditableCheckout
    from apprc.user_files.installation.coordination import installation_lock, write_record
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
    with installation_lock(directory):
        write_record(directory, replace(inspection.record, active_runtime=EditableCheckout(member, environment)), expected_revision=inspection.revision)
    preparation = prepare_uninstall(directory, remove_repository=True)
    assert preparation.can_execute and preparation.plan is not None
    selected = tuple(entry for entry in preparation.entries if entry.kind == "repository")
    assert len(selected) == 1 and selected[0].path == repository
    _remove_inventory(selected)
    assert local_changes.read_text() == "local work"
    with pytest.raises(InstallationError, match="cannot be combined"):
        prepare_uninstall(directory, remove_repository=True, keep_data=True)


def test_repository_finalizer_preserves_external_link_targets(tmp_path: Path) -> None:
    import shutil
    from apprc.distribution.runtime import namespace_finalizer, _process_waiter
    from apprc.user_files.installation.inventory import tree_revision
    from tests.test_distribution_process_waiter import _owned_child

    repository = tmp_path / "checkout"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (repository / "link").symlink_to(outside)
    staging = tmp_path / "staging"
    recovery = staging / "recovery"
    recovery.mkdir(parents=True, mode=0o700)
    shutil.copyfile(_process_waiter.__file__, staging / "_process_waiter.py")
    shutil.copyfile(namespace_finalizer.__file__, staging / "repository_finalizer.py")
    proof = recovery / "repository.json"
    proof.write_text(json.dumps({"directory": str(tmp_path / "retired-installation"), "app_id": "fixture", "generation_id": "00000000-0000-0000-0000-000000000000", "repository": str(repository), "revision": tree_revision(repository)}))
    with _owned_child() as process:
        token = _process_waiter.process_start_token(process.pid)
        assert process.stdin is not None
        process.stdin.write("exit\n")
        process.stdin.flush()
        process.wait(timeout=5)
        # > Load the actual staged leaf so its sibling stdlib waiter is exercised.
        import importlib.util
        spec = importlib.util.spec_from_file_location("fixture_finalizer", staging / "repository_finalizer.py")
        assert spec is not None and spec.loader is not None
        leaf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(leaf)
        leaf.finalize_repository(proof, process.pid, token)
    assert not repository.exists()
    assert outside.read_text() == "preserve"
    assert not staging.exists()
