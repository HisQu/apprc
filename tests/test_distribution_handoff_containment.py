"""Sender and receiver containment at exact uninstall boundaries."""

from __future__ import annotations

import io
import os
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from apprc.definition.installation import (
    CleanupInventory,
    InstallationError,
    InstallationPlacement,
    InventoryEntry,
    OperationStep,
    RetiredResource,
    UninstallPlan,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime import controllers, removal
from apprc.distribution.runtime.backend import external_base_python
from apprc.distribution.runtime.controllers import (
    UninstallHandoff,
    _assert_outside_removal,
    _assert_private_directory,
    _handoff_removal_roots,
    prepare_uninstall,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.discovery import inspect_installation
from tests.test_distribution_process_waiter import _owned_child
from tests.test_distribution_support_recovery import (
    _run as install_fixture,
    _scenario as install_scenario,
    _stub_backend,
)


def _clear_controller_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "UV_CACHE_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "UV_PYTHON_BIN_DIR",
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
        "UV_CONFIG_DIR",
        "TMPDIR",
        "TMP",
        "TEMP",
    ):
        monkeypatch.delenv(key, raising=False)


def _installed_removal_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _clear_controller_environment(monkeypatch)
    directory, install_plan, snapshot, environment = install_scenario(tmp_path)
    cache_root = tmp_path / "owned-cache"
    cache_root.mkdir()
    cache_payload = cache_root / "owned.json"
    cache_payload.write_text('{"keep":true}\n', encoding="utf-8")
    absent_cache_root = tmp_path / "selected-but-absent-cache"
    retained_root = tmp_path / "retained-cache"
    placement = InstallationPlacement(
        Layout.native(),
        cache_dir=cache_root,
        capabilities=frozenset({"cache"}),
        retired=(
            RetiredResource("cache", absent_cache_root),
            RetiredResource("cache", retained_root),
        ),
    )
    install_plan = replace(
        install_plan,
        target=replace(install_plan.target, placement=placement),
    )
    snapshot = replace(snapshot, placement=placement)
    _stub_backend(monkeypatch, snapshot)
    support = {PurePosixPath("controller.py"): b"# saved controller\n"}
    installed = install_fixture(install_plan, environment, support)
    assert installed.status == "ready"

    program_prefix = snapshot.prefix
    program_prefix.mkdir(parents=True, exist_ok=True)
    program_marker = program_prefix / "program-marker"
    program_marker.write_text("installed program", encoding="utf-8")
    retained = InventoryEntry(retained_root, "directory", None, "cache")
    cache_entries = (
        InventoryEntry(cache_root, "directory", None, "cache"),
        InventoryEntry(
            cache_payload, "file", file_revision(cache_payload), "cache"
        ),
    )
    preparation = prepare_uninstall(
        directory,
        categories=frozenset({"cache"}),
        complete=True,
        forget_retained=True,
        inventory=CleanupInventory(cache_entries, (retained,)),
    )
    assert preparation.can_execute and preparation.plan is not None
    return (
        directory,
        program_prefix,
        program_marker,
        cache_root,
        cache_payload,
        absent_cache_root,
        retained_root,
        preparation,
    )


def _installed_zero_capability_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _clear_controller_environment(monkeypatch)
    directory, install_plan, snapshot, environment = install_scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    support = {PurePosixPath("controller.py"): b"# saved controller\n"}
    installed = install_fixture(install_plan, environment, support)
    assert installed.status == "ready"
    return directory, snapshot


def _pending_receiver_handoff(
    plan: UninstallPlan,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_pid: int,
) -> UninstallHandoff:
    """Stage real uninstall authority and its private envelope without launching UV."""
    safe_temp = tmp_path / "receiver-safe-temp"
    safe_temp.mkdir()
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO())
    with monkeypatch.context() as launch:
        launch.setattr(
            controllers.tempfile, "gettempdir", lambda: str(safe_temp)
        )
        launch.setattr(
            controllers,
            "external_base_python",
            lambda *_args, **_kwargs: Path(sys.executable),
        )
        launch.setattr(
            controllers.subprocess, "Popen", lambda *_args, **_kwargs: process
        )
        handoff = controllers.start_uninstall_handoff(
            plan,
            original_pid=original_pid,
            provider_cleanup=lambda _context: None,
        )

    envelope = removal._parse_plan(handoff.plan_file)
    pending = inspect_installation(plan.directory, app_id=plan.app_id)
    assert pending.record is not None and pending.record.operation is not None
    operation = pending.record.operation
    assert operation.kind == "uninstall"
    assert operation.operation_id == plan.operation_id
    assert pending.revision is not None
    assert pending.revision != plan.expected_revision
    assert OperationStep.PROVIDER_CLEANUP in operation.steps
    assert envelope["expected_revision"] == pending.revision
    assert envelope["operation_id"] == str(operation.operation_id)
    assert envelope["generation_id"] == str(pending.record.generation_id)
    assert envelope["app_id"] == pending.record.app_id == plan.app_id
    assert envelope["original_pid"] == original_pid
    assert envelope["original_start"] == removal.process_start_token(
        original_pid
    )
    assert (
        tuple(removal._inventory(envelope, "inventory"))
        == operation.inventory.entries
    )
    assert (
        tuple(removal._inventory(envelope, "retained"))
        == operation.inventory.retained
    )
    assert (
        operation.inventory == plan.inventory
        and operation.categories == plan.categories
        and operation.complete == plan.complete
        and operation.forget_retained == plan.forget_retained
        and envelope["categories"] == sorted(operation.categories)
        and operation.complete == envelope["complete"]
        and operation.forget_retained == envelope["forget_retained"]
    )
    _assert_private_directory(handoff.plan_file.parent)
    recovery = handoff.plan_file.parent / "recovery"
    _assert_private_directory(recovery)
    assert (recovery / "controller.py").is_file()
    return handoff


def test_receiver_rejects_management_prefix_under_program_only_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        directory,
        program_prefix,
        program_marker,
        cache_root,
        cache_payload,
        absent_cache_root,
        retained_root,
        _preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    plan = preparation.plan
    assert not plan.complete and not plan.categories
    receiver_prefix = program_prefix / "receiver-environment"
    receiver_prefix.mkdir()
    receiver_marker = receiver_prefix / "pyvenv.cfg"
    receiver_marker.write_bytes(b"receiver management environment\n")
    with _owned_child() as original:
        handoff = _pending_receiver_handoff(
            plan, tmp_path, monkeypatch, original.pid
        )
        authority = directory / "installation.json"
        authority_before = authority.read_bytes()
        revision_before = inspect_installation(
            directory, app_id=plan.app_id
        ).revision
        plan_before = handoff.plan_file.read_bytes()
        stdin = io.StringIO("NOT-EXIT\n")
        monkeypatch.setattr(
            removal,
            "sys",
            SimpleNamespace(
                prefix=str(receiver_prefix),
                base_prefix=sys.base_prefix,
                executable=sys.executable,
                stdin=stdin,
            ),
        )

        with pytest.raises(
            InstallationError,
            match="handoff location overlaps a removal target",
        ):
            removal.execute_handoff(handoff.plan_file)

        assert stdin.tell() == 0
        assert handoff.plan_file.read_bytes() == plan_before
        assert original.poll() is None
        assert authority.read_bytes() == authority_before
        assert (
            inspect_installation(directory, app_id=plan.app_id).revision
            == revision_before
        )
        assert program_marker.read_bytes() == b"installed program"
        assert (
            receiver_marker.read_bytes() == b"receiver management environment\n"
        )
        assert cache_root.is_dir()
        assert cache_payload.read_bytes() == b'{"keep":true}\n'
        assert not absent_cache_root.exists()
        assert not retained_root.exists()


def test_receiver_rejects_execution_cwd_under_complete_selected_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        directory,
        _program_prefix,
        program_marker,
        cache_root,
        cache_payload,
        absent_cache_root,
        retained_root,
        preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    plan = preparation.plan
    assert preparation.can_execute and plan is not None
    assert plan.complete and plan.categories == frozenset({"cache"})
    assert any(item.path == cache_root for item in plan.inventory.entries)
    assert any(item.path == retained_root for item in plan.inventory.retained)
    receiver_cwd = cache_root / "receiver-work"
    receiver_cwd.mkdir()
    receiver_marker = receiver_cwd / "working-payload"
    receiver_marker.write_bytes(b"receiver working directory\n")
    actual_cwd = Path.cwd()

    with _owned_child() as original:
        handoff = _pending_receiver_handoff(
            plan, tmp_path, monkeypatch, original.pid
        )
        authority = directory / "installation.json"
        authority_before = authority.read_bytes()
        revision_before = inspect_installation(
            directory, app_id=plan.app_id
        ).revision
        plan_before = handoff.plan_file.read_bytes()
        stdin = io.StringIO("NOT-EXIT\n")
        with monkeypatch.context() as receiver_boundary:
            receiver_boundary.setattr(removal.sys, "stdin", stdin)
            receiver_boundary.setattr(
                removal.Path,
                "cwd",
                classmethod(lambda _cls: receiver_cwd),
            )
            with pytest.raises(
                InstallationError,
                match="handoff location overlaps a removal target",
            ):
                removal.execute_handoff(handoff.plan_file)

        assert Path.cwd() == actual_cwd
        assert stdin.tell() == 0
        assert original.poll() is None
        assert authority.read_bytes() == authority_before
        assert (
            inspect_installation(directory, app_id=plan.app_id).revision
            == revision_before
        )
        assert handoff.plan_file.read_bytes() == plan_before
        assert program_marker.read_bytes() == b"installed program"
        assert cache_payload.read_bytes() == b'{"keep":true}\n'
        assert receiver_marker.read_bytes() == b"receiver working directory\n"
        assert not absent_cache_root.exists()
        assert not retained_root.exists()


def test_sender_rejects_tempdir_under_program_prefix_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        directory,
        program_prefix,
        program_marker,
        _cache_root,
        cache_payload,
        _absent_cache_root,
        _retained_root,
        preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    plan = preparation.plan
    assert plan is not None
    inspection = inspect_installation(directory, app_id=plan.app_id)
    before_revision = inspection.revision
    authority = directory / "installation.json"
    authority_before = authority.read_bytes()
    unsafe_temp = program_prefix / "temporary"
    unsafe_temp.mkdir()
    monkeypatch.setenv("TMPDIR", str(unsafe_temp))
    monkeypatch.setattr(
        controllers.tempfile, "gettempdir", lambda: str(unsafe_temp)
    )
    cleanup_calls: list[bool] = []

    with pytest.raises(InstallationError, match="removal target"):
        controllers.start_uninstall_handoff(
            plan,
            provider_cleanup=lambda _context: cleanup_calls.append(True),
        )

    assert not cleanup_calls
    assert (
        inspect_installation(directory, app_id=plan.app_id).revision
        == before_revision
    )
    assert authority.read_bytes() == authority_before
    assert program_marker.read_text(encoding="utf-8") == "installed program"
    assert cache_payload.read_text(encoding="utf-8") == '{"keep":true}\n'


@pytest.mark.parametrize(
    "managed_variable", ("UV_PYTHON_INSTALL_DIR", "TMPDIR")
)
def test_sender_rejects_managed_environment_root_under_absent_selected_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    managed_variable: str,
) -> None:
    (
        directory,
        _program_prefix,
        _program_marker,
        _cache_root,
        cache_payload,
        absent_cache_root,
        _retained_root,
        preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    plan = preparation.plan
    assert plan is not None
    safe_temp = tmp_path / "safe-temp"
    safe_temp.mkdir()
    monkeypatch.setattr(
        controllers.tempfile, "gettempdir", lambda: str(safe_temp)
    )
    monkeypatch.setenv(managed_variable, str(absent_cache_root / "managed"))
    inspection = inspect_installation(directory, app_id=plan.app_id)
    before_revision = inspection.revision
    authority = directory / "installation.json"
    authority_before = authority.read_bytes()
    cleanup_calls: list[bool] = []

    with pytest.raises(InstallationError, match="removal target"):
        controllers.start_uninstall_handoff(
            plan,
            provider_cleanup=lambda _context: cleanup_calls.append(True),
        )

    assert not absent_cache_root.exists()
    assert not cleanup_calls
    assert (
        inspect_installation(directory, app_id=plan.app_id).revision
        == before_revision
    )
    assert authority.read_bytes() == authority_before
    assert cache_payload.read_text(encoding="utf-8") == '{"keep":true}\n'


def test_safe_temp_alias_preserves_interrupted_provider_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        directory,
        _program_prefix,
        program_marker,
        _cache_root,
        cache_payload,
        _absent_cache_root,
        _retained_root,
        preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    assert preparation.can_execute and preparation.plan is not None
    plan = preparation.plan
    physical_temp = tmp_path / "physical-safe-temp"
    physical_temp.mkdir()
    alias = tmp_path / "safe-temp-alias"
    alias.symlink_to(physical_temp, target_is_directory=True)
    monkeypatch.setattr(controllers.tempfile, "gettempdir", lambda: str(alias))
    monkeypatch.setenv("TMPDIR", str(alias))

    def interrupted_cleanup(_context):
        cache_payload.unlink()
        raise RuntimeError("Application cleanup interrupted.")

    with pytest.raises(RuntimeError):
        controllers.start_uninstall_handoff(
            plan, provider_cleanup=interrupted_cleanup
        )

    failed = inspect_installation(directory, app_id=plan.app_id)
    assert failed.status == "incomplete"
    assert failed.record is not None and failed.record.operation is not None
    assert failed.record.operation.operation_id == plan.operation_id
    assert OperationStep.PROVIDER_CLEANUP not in failed.record.operation.steps
    assert not cache_payload.exists()
    assert program_marker.read_bytes() == b"installed program"
    assert alias.is_symlink() and alias.resolve() == physical_temp


def test_actual_selected_and_retained_roots_and_program_only_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        directory,
        program_prefix,
        _program_marker,
        cache_root,
        _cache_payload,
        absent_cache_root,
        retained_root,
        preparation,
    ) = _installed_removal_scenario(tmp_path, monkeypatch)
    plan = preparation.plan
    inspection = preparation.inspection
    assert plan is not None and inspection.record is not None
    roots = _handoff_removal_roots(plan, inspection.record)

    with pytest.raises(InstallationError, match="removal target"):
        _assert_outside_removal(absent_cache_root, roots)
    with pytest.raises(InstallationError, match="removal target"):
        _assert_outside_removal(cache_root, roots)
    with pytest.raises(InstallationError, match="removal target"):
        _assert_outside_removal(directory, roots)
    _assert_outside_removal(retained_root, roots)
    assert program_prefix in roots
    assert inspection.record.current is not None
    assert set(inspection.record.current.commands).issubset(roots)

    program_only = prepare_uninstall(directory)
    assert program_only.can_execute and program_only.plan is not None
    program_roots = _handoff_removal_roots(program_only.plan, inspection.record)
    _assert_outside_removal(directory, program_roots)
    _assert_outside_removal(cache_root, program_roots)
    _assert_outside_removal(retained_root, program_roots)

    explicitly_retained = prepare_uninstall(
        directory,
        categories=frozenset({"cache"}),
        complete=True,
        forget_retained=True,
        inventory=CleanupInventory(
            retained=(
                InventoryEntry(cache_root, "directory", None, "cache"),
                InventoryEntry(retained_root, "directory", None, "cache"),
            )
        ),
    )
    assert explicitly_retained.can_execute
    assert explicitly_retained.plan is not None
    retained_roots = _handoff_removal_roots(
        explicitly_retained.plan, inspection.record
    )
    _assert_outside_removal(cache_root, retained_roots)
    with pytest.raises(InstallationError, match="removal target"):
        _assert_outside_removal(absent_cache_root, retained_roots)


def test_zero_capability_install_only_excludes_program_and_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, snapshot = _installed_zero_capability_scenario(
        tmp_path, monkeypatch
    )
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    assert preparation.inspection.record is not None
    installed = preparation.inspection.record.current
    assert installed is not None
    assert installed.placement.capabilities == frozenset()

    roots = _handoff_removal_roots(
        preparation.plan, preparation.inspection.record
    )
    expected_roots = {
        snapshot.prefix.resolve(),
        *(
            Path(os.path.normpath(os.fspath(command))).absolute()
            for command in snapshot.commands
        ),
    }
    assert set(roots) == expected_roots
    _assert_outside_removal(directory, roots)
    _assert_outside_removal(tmp_path / "unselected-cache", roots)


def test_external_base_python_rejects_managed_executable_before_probe(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "uv-managed-python"
    managed.mkdir()
    executable = managed / ("python.exe" if os.name == "nt" else "python")
    executable.write_bytes(b"managed interpreter")

    with pytest.raises(InstallationError, match="removal target"):
        external_base_python(
            tmp_path / "application-prefix",
            executable=executable,
            forbidden_roots=(managed,),
        )

    assert executable.read_bytes() == b"managed interpreter"
