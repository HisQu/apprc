"""Sender and receiver containment at exact uninstall boundaries."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationHooks,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    InventoryEntry,
    OperationStep,
    ProjectSnapshot,
    RetiredResource,
    RuntimeSelection,
    RuntimeSlot,
    UninstallPlan,
)
from apprc.definition.paths import Layout, ResourceKind
from apprc.distribution.runtime import _handoff, controllers, removal
from apprc.distribution.runtime.controllers import (
    UninstallHandoff,
    prepare_uninstall,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import fail_operation
from apprc.distribution.runtime import namespace_finalizer
from tests.test_distribution_process_waiter import _owned_child


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


def _schema3_installation(
    tmp_path: Path,
    *,
    cache_root: Path | None = None,
    config_root: Path | None = None,
    retired: tuple[RetiredResource, ...] = (),
    hooks: InstallationHooks = InstallationHooks(
        cleanup="handoff_test.hooks:cleanup"
    ),
) -> tuple[Path, RuntimeSlot]:
    directory = tmp_path / "installation"
    create_private_directory_if_missing(directory)
    identity = InstallationIdentity(
        "handoff-app",
        "handoff-test",
        "handoff_test",
        None,
        ("handoff-app",),
    )
    resources: tuple[tuple[ResourceKind, Path | None], ...] = (
        ("config", config_root),
        ("cache", cache_root),
    )
    placement = InstallationPlacement(
        Layout.native(),
        config_dir=config_root,
        cache_dir=cache_root,
        capabilities=frozenset(
            category for category, root in resources if root is not None
        ),
        retired=retired,
    )
    slot_id = uuid4()
    slot_directory = directory / "runtimes" / str(slot_id)
    slot_directory.mkdir(parents=True)
    (slot_directory / ".apprc-runtime-lease").touch()
    runtime = RuntimeSlot(
        slot_id,
        ProjectSnapshot("0" * 64, "1" * 64, "2" * 40),
        RuntimeSelection("3.12"),
        version="1.0",
        python_version="3.12.1",
        hooks=hooks,
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=identity.commands[0],
        generation_id=uuid4(),
        support_version="0.31.0",
        placement=placement,
        status="ready",
        active_runtime=runtime,
    )
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    return directory, runtime


def _installed_removal_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _clear_controller_environment(monkeypatch)
    cache_root = tmp_path / "owned-cache"
    cache_root.mkdir()
    cache_payload = cache_root / "owned.json"
    cache_payload.write_text('{"keep":true}\n', encoding="utf-8")
    absent_cache_root = tmp_path / "selected-but-absent-cache"
    retained_root = tmp_path / "retained-cache"
    directory, runtime = _schema3_installation(
        tmp_path,
        cache_root=cache_root,
        retired=(
            RetiredResource("cache", absent_cache_root),
            RetiredResource("cache", retained_root),
        ),
    )
    program_prefix = directory / "runtimes" / str(runtime.slot_id)
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
    directory, runtime = _schema3_installation(tmp_path)
    return directory, directory / "runtimes" / str(runtime.slot_id)


def _pending_receiver_handoff(
    plan: UninstallPlan,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_pid: int,
) -> UninstallHandoff:
    """Stage exact schema-3 authority and private inputs without launching code."""
    safe_temp = tmp_path / "receiver-safe-temp"
    safe_temp.mkdir()
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO())
    with monkeypatch.context() as launch:
        launch.setattr(
            controllers.tempfile, "gettempdir", lambda: str(safe_temp)
        )
        launch.setattr(
            controllers.subprocess, "Popen", lambda *_args, **_kwargs: process
        )
        handoff = controllers.start_uninstall_handoff(
            plan,
            original_pid=original_pid,
        )

    envelope = removal._parse_plan(handoff.plan_file)
    pending = inspect_installation(plan.directory, app_id=plan.app_id)
    assert pending.record is not None and pending.record.operation is not None
    operation = pending.record.operation
    assert operation.kind == "uninstall"
    assert operation.operation_id == plan.operation_id
    assert pending.revision is not None
    assert pending.revision != plan.expected_revision
    assert OperationStep.PROVIDER_CLEANUP not in operation.steps
    assert envelope["expected_revision"] == pending.revision
    assert envelope["operation_id"] == str(operation.operation_id)
    assert envelope["generation_id"] == str(pending.record.generation_id)
    assert envelope["app_id"] == pending.record.identity.app_id == plan.app_id
    assert envelope["original_pid"] == original_pid
    assert envelope["original_start"] == _handoff.process_start_token(
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
    controllers._assert_private_directory(handoff.plan_file.parent)
    recovery = handoff.plan_file.parent / "recovery"
    controllers._assert_private_directory(recovery)
    assert not (recovery / "controller.py").exists()
    return handoff


def test_namespace_finalizer_rejects_substituted_product_identity(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    directory.mkdir()
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    plan = recovery / "finalization.json"
    plan.write_text(
        removal.json.dumps(
            {
                "directory": str(directory),
                "app_id": "saved-product",
                "generation_id": str(uuid4()),
                "support": [],
            }
        ),
        encoding="utf-8",
    )
    plan.chmod(0o600)

    with pytest.raises(ValueError, match="malformed or grants support"):
        namespace_finalizer.finalize_namespace(
            plan, directory, expected_app_id="different-product"
        )

    assert directory.is_dir()


def test_config_only_removal_needs_no_custom_provider(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    marker = config_root / ".apprc-owner.json"
    marker.write_text(
        '{"schema_version":1,"app_id":"handoff-app","category":"config"}\n',
        encoding="utf-8",
    )
    config_payload = config_root / "apprc.user.env"
    config_payload.write_text("VALUE=remove\n", encoding="utf-8")
    directory, _runtime = _schema3_installation(
        tmp_path, config_root=config_root, hooks=InstallationHooks()
    )

    preparation = prepare_uninstall(
        directory, categories=frozenset({"config"}), complete=True
    )

    assert preparation.can_execute
    assert preparation.plan is not None
    config_entries = tuple(
        entry
        for entry in preparation.plan.inventory.entries
        if entry.resource == "config"
    )
    assert {entry.path for entry in config_entries} == {
        config_root,
        marker,
        config_payload,
    }
    assert next(
        entry for entry in config_entries if entry.path == marker
    ).revision == file_revision(marker)
    assert next(
        entry for entry in config_entries if entry.path == config_payload
    ).revision == file_revision(config_payload)


@pytest.mark.skipif(os.name == "nt", reason="POSIX private directory modes")
def test_handoff_directory_refuses_shared_permissions_without_mutation(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "handoff"
    directory.mkdir(mode=0o700)
    directory.chmod(0o755)
    payload = directory / "retained"
    payload.write_text("keep", encoding="utf-8")
    mode = directory.stat().st_mode

    with pytest.raises(InstallationError) as error:
        controllers._assert_private_directory(directory)
    assert str(error.value) == "Uninstall handoff directory must be private."

    assert directory.stat().st_mode == mode
    assert payload.read_text(encoding="utf-8") == "keep"


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


def test_receiver_rejects_stale_revision_before_handoff_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    with _owned_child() as original:
        handoff = _pending_receiver_handoff(
            plan, tmp_path, monkeypatch, original.pid
        )
        envelope_before = handoff.plan_file.read_bytes()
        recovery = handoff.plan_file.parent / "recovery"
        authority = inspect_installation(directory, app_id=plan.app_id)
        assert authority.record is not None and authority.revision is not None
        changed = fail_operation(
            directory,
            operation_id=plan.operation_id,
            expected_revision=authority.revision,
            diagnostic=InstallationDiagnostic(
                "installation-incomplete",
                "The pending operation failed after handoff staging.",
                "Resume the pending uninstall with a fresh handoff.",
            ),
        )
        assert changed.revision != authority.revision
        stdin = io.StringIO("EXIT\n")
        monkeypatch.setattr(removal.sys, "stdin", stdin)

        with pytest.raises(
            InstallationError,
            match="Uninstall authority changed before handoff readiness.",
        ):
            removal.execute_handoff(
                handoff.plan_file,
                expected_identity=authority.record.identity,
            )

        assert stdin.tell() == 0
        assert "APPRC-UNINSTALL-READY:" not in capsys.readouterr().out
        assert original.poll() is None
        assert handoff.plan_file.read_bytes() == envelope_before
        assert recovery.is_dir()
        assert not (recovery / "controller.py").exists()
        assert program_marker.read_bytes() == b"installed program"
        assert cache_root.is_dir()
        assert cache_payload.read_bytes() == b'{"keep":true}\n'
        assert not absent_cache_root.exists()
        assert not retained_root.exists()


def test_sender_rejects_tempdir_under_program_prefix_before_staging(
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
    with pytest.raises(InstallationError, match="removal target"):
        controllers.start_uninstall_handoff(plan)
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
    with pytest.raises(InstallationError, match="removal target"):
        controllers.start_uninstall_handoff(plan)
    assert (
        inspect_installation(directory, app_id=plan.app_id).revision
        == before_revision
    )
    assert authority.read_bytes() == authority_before
    assert cache_payload.read_text(encoding="utf-8") == '{"keep":true}\n'


def test_safe_temp_alias_preserves_pending_handoff_without_provider_call(
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
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO())
    launch_environments: list[dict[str, str]] = []

    def record_launch(_command, **kwargs):
        launch_environments.append(kwargs["env"])
        return process

    monkeypatch.setattr(controllers.subprocess, "Popen", record_launch)
    handoff = controllers.start_uninstall_handoff(plan)

    pending = inspect_installation(directory, app_id=plan.app_id)
    assert pending.status == "incomplete"
    assert pending.record is not None and pending.record.operation is not None
    assert pending.record.operation.operation_id == plan.operation_id
    assert OperationStep.PROVIDER_CLEANUP not in pending.record.operation.steps
    assert launch_environments[0]["TMPDIR"] == str(physical_temp.resolve())
    controllers._assert_private_directory(handoff.plan_file.parent)
    assert cache_payload.read_text(encoding="utf-8") == '{"keep":true}\n'
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
    roots = _handoff.handoff_removal_roots(plan, inspection.record)

    with pytest.raises(InstallationError, match="removal target"):
        _handoff.assert_outside_removal(absent_cache_root, roots)
    with pytest.raises(InstallationError, match="removal target"):
        _handoff.assert_outside_removal(cache_root, roots)
    with pytest.raises(InstallationError, match="removal target"):
        _handoff.assert_outside_removal(directory, roots)
    _handoff.assert_outside_removal(retained_root, roots)
    assert program_prefix in roots
    assert directory in roots
    assert cache_root in roots

    program_only = prepare_uninstall(directory)
    assert program_only.can_execute and program_only.plan is not None
    program_roots = _handoff.handoff_removal_roots(
        program_only.plan, inspection.record
    )
    _handoff.assert_outside_removal(directory, program_roots)
    _handoff.assert_outside_removal(cache_root, program_roots)
    _handoff.assert_outside_removal(retained_root, program_roots)

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
    retained_roots = _handoff.handoff_removal_roots(
        explicitly_retained.plan, inspection.record
    )
    _handoff.assert_outside_removal(cache_root, retained_roots)
    with pytest.raises(InstallationError, match="removal target"):
        _handoff.assert_outside_removal(absent_cache_root, retained_roots)


def test_zero_capability_install_removes_only_managed_runtime_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, slot_directory = _installed_zero_capability_scenario(
        tmp_path, monkeypatch
    )
    preparation = prepare_uninstall(directory)
    assert preparation.can_execute and preparation.plan is not None
    assert preparation.inspection.record is not None
    installed = preparation.inspection.record.active_runtime
    assert isinstance(installed, RuntimeSlot)
    assert preparation.inspection.record.placement.capabilities == frozenset()

    roots = _handoff.handoff_removal_roots(
        preparation.plan, preparation.inspection.record
    )
    assert set(roots) == {slot_directory.resolve()}
    _handoff.assert_outside_removal(directory, roots)
    _handoff.assert_outside_removal(tmp_path / "unselected-cache", roots)


def test_handoff_python_rejects_managed_executable_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed = tmp_path / "uv-managed-python"
    binary_directory = managed / "bin"
    binary_directory.mkdir(parents=True)
    executable = binary_directory / "python"
    executable.write_bytes(b"managed interpreter")
    monkeypatch.setattr(
        controllers,
        "sys",
        SimpleNamespace(
            executable=str(executable),
            base_prefix=str(managed),
        ),
    )

    with pytest.raises(
        InstallationError,
        match="No external Python executable is available",
    ):
        controllers._handoff_python((managed,))

    assert executable.read_bytes() == b"managed interpreter"
