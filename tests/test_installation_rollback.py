"""Caught installation failures restore authority and exact owned effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial
import hashlib
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallPlan,
    OperationStep,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime import _command_publication, installation
from apprc.distribution.runtime._install_progress import (
    InstallProgress,
    installation_progress,
)
from apprc.services.installation import InstallationManager
from apprc.user_files.app_home.writes import managed_lock_path


@dataclass
class _NativeCase:
    manager: InstallationManager
    identity: InstallationIdentity
    placement: InstallationPlacement
    setup: Path
    uv: Path
    archive: Path

    def install(
        self,
        *,
        commit: str = "c" * 40,
        setup_version: str | None = "1.0",
        command_directory: Path | None = None,
        expected_update: tuple[UUID, str] | None = None,
    ) -> InstallationInspection:
        """Run the real controller with a fresh candidate and isolated effects."""
        return installation.install_application(
            self.manager,
            self.identity,
            RuntimeSlot(
                uuid4(),
                ProjectSnapshot("a" * 64, "b" * 64, commit),
                RuntimeSelection("3.14"),
            ),
            self.placement,
            command_name="fixture",
            setup_version=setup_version,
            project_archive=self.archive,
            manager_executable=self.setup,
            uv=self.uv,
            command_directory=command_directory,
            expected_update=expected_update,
        )


def _prepare(
    manager: InstallationManager,
    plan: InstallPlan,
    runtime: RuntimeSlot,
    archive: Path,
    uv: Path,
    *,
    environment: Mapping[str, str],
    manager_executable: Path,
    resources: installation._ResourceSnapshot,
    version: str = "1.0",
) -> tuple[RuntimeSlot, str]:
    """Replace dependency acquisition while exercising real lifecycle writes."""
    slot = manager.directory / "runtimes" / str(runtime.slot_id)
    slot.mkdir(parents=True)
    (slot / "project.zip").write_bytes(archive.read_bytes())
    (slot / ".venv").mkdir()
    observed = replace(runtime, version=version, python_version="3.14")
    current = manager.inspect()
    assert current.revision is not None
    current = manager.record_step(
        operation_id=plan.operation_id,
        expected_revision=current.revision,
        step=OperationStep.RUNTIME_PREPARED,
    )
    assert current.revision is not None
    current = manager.record_step(
        operation_id=plan.operation_id,
        expected_revision=current.revision,
        step=OperationStep.RUNTIME_VALIDATED,
        observed=observed,
    )
    manager.initialize(
        context=installation._context(
            manager.directory,
            plan.operation_id,
            plan.generation_id,
            plan.target.placement,
        )
    )
    assert current.revision is not None
    current = manager.record_step(
        operation_id=plan.operation_id,
        expected_revision=current.revision,
        step=OperationStep.RESOURCES_READY,
    )
    assert current.revision is not None
    return observed, current.revision


@pytest.fixture
def native_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _NativeCase:
    """Isolate platform integration and dependency builds from rollback tests."""
    roots = tmp_path / "resources"
    placement = InstallationPlacement(
        Layout.single_root(roots),
        config_dir=roots / "config",
        appdata_dir=roots / "appdata",
        state_dir=roots / "state",
        logs_dir=roots / "state" / "logs",
        capabilities=frozenset({"config", "appdata", "state"}),
    )
    manager = InstallationManager(
        AppRC(
            app_id="rollback-fixture",
            paths=Paths(config=True, appdata=True, state=True),
        ).schema,
        environment={},
        directory=tmp_path / "installation",
    )
    files = tuple(tmp_path / name for name in ("setup", "uv", "project.zip"))
    for path in files:
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(installation, "_prepare_candidate", _prepare)
    return _NativeCase(
        manager,
        InstallationIdentity(
            "rollback-fixture",
            "rollback-fixture",
            "fixture",
            None,
            ("fixture",),
        ),
        placement,
        *files,
    )


def test_managed_setup_and_update_publish_the_probed_application_version(
    native_case: _NativeCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.distribution.runtime import (
        _windows_registration,
        _windows_version,
    )

    command_directory = tmp_path / "bin"
    command_directory.mkdir()
    monkeypatch.setattr(
        native_case.manager, "environment", {"PATH": str(command_directory)}
    )
    registered: list[str] = []

    def stamp(content: bytes, version: str) -> bytes:
        return content + version.encode()

    def register(
        inspection: InstallationInspection, version: str, *_args, **_kwargs
    ) -> InstallationInspection:
        registered.append(version)
        return inspection

    monkeypatch.setattr(_windows_version, "versioned_executable", stamp)
    monkeypatch.setattr(_windows_registration, "publish_registration", register)

    first, second = "0.23.1b1", "0.23.1b2"
    command_name = installation._command_filename("fixture")
    paths = (
        native_case.manager.directory / command_name,
        command_directory / command_name,
    )
    monkeypatch.setattr(
        installation, "_prepare_candidate", partial(_prepare, version=first)
    )
    initial = native_case.install(
        command_directory=command_directory, setup_version=first
    )
    assert initial.record is not None and initial.revision is not None
    assert all(path.read_bytes() == b"setup0.23.1b1" for path in paths)

    monkeypatch.setattr(
        installation, "_prepare_candidate", partial(_prepare, version=second)
    )
    updated = native_case.install(
        commit="d" * 40,
        setup_version=second,
        expected_update=(initial.record.generation_id, initial.revision),
    )
    assert updated.status == "ready"
    assert all(path.read_bytes() == b"setup0.23.1b2" for path in paths)
    assert registered == [first, second]


def test_managed_setup_compares_installed_and_incoming_builds(
    native_case: _NativeCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.distribution.runtime import _windows_version

    case = native_case
    versions: list[str] = []
    stamp = b"version resource"

    def versioned(content: bytes, version: str) -> bytes:
        versions.append(version)
        return content + stamp

    monkeypatch.setattr(_windows_version, "versioned_executable", versioned)

    def run_setup(*, commit: str = "c" * 40) -> list[str]:
        events: list[InstallProgress] = []
        with installation_progress(events.append):
            assert case.install(commit=commit).status == "ready"
        assert events[3].message == "Preparing Runtime"
        return [event.message for event in events[:3]]

    assert run_setup() == [
        "Install",
        "Installed  No active installation",
        "Incoming   1.0",
    ]
    published = case.manager.directory / installation._command_filename(
        "fixture"
    )
    installed_digest = hashlib.sha256(published.read_bytes()).hexdigest()[:12]
    assert run_setup() == [
        "Reinstall",
        f"Installed  1.0 (commit cccccccccccc) · Command SHA-256 {installed_digest}",
        f"Incoming   1.0 (commit cccccccccccc) · Command SHA-256 {installed_digest}",
    ]

    case.setup.write_bytes(b"new executable")
    incoming_digest = hashlib.sha256(b"new executable" + stamp).hexdigest()[:12]
    assert run_setup() == [
        "Replace",
        f"Installed  1.0 (commit cccccccccccc) · Command SHA-256 {installed_digest}",
        f"Incoming   1.0 (commit cccccccccccc) · Command SHA-256 {incoming_digest}",
    ]
    assert published.read_bytes() == b"new executable" + stamp
    assert run_setup(commit="d" * 40) == [
        "Replace",
        "Installed  1.0 (commit cccccccccccc)",
        "Incoming   1.0 (commit dddddddddddd)",
    ]
    assert versions == ["1.0"] * 4


def test_managed_setup_reads_snapshot_version_when_caller_omits_version(
    native_case: _NativeCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    def snapshot_version(
        archive: Path, runtime: RuntimeSlot, identity: InstallationIdentity
    ) -> str:
        assert archive == native_case.archive
        assert runtime.source.commit == "c" * 40
        assert identity == native_case.identity
        return "1.0"

    monkeypatch.setattr(installation, "_snapshot_metadata", snapshot_version)
    events: list[InstallProgress] = []
    with installation_progress(events.append):
        assert native_case.install(setup_version=None).status == "ready"
    assert events[2].message == "Incoming   1.0"


@pytest.mark.parametrize(
    "replacement", [False, True], ids=["first", "replacement"]
)
@pytest.mark.parametrize(
    "boundary", ["begin", "prepare", "resources", "publication", "activation"]
)
def test_caught_native_failure_restores_previous_state_and_retry_succeeds(
    native_case: _NativeCase,
    monkeypatch: pytest.MonkeyPatch,
    replacement: bool,
    boundary: str,
) -> None:
    case = native_case
    if replacement:
        case.install()
    before = case.manager.inspect()
    record_path = case.manager.directory / "installation.json"
    before_bytes = record_path.read_bytes() if record_path.exists() else None
    stable = case.manager.directory / installation._command_filename("fixture")
    before_command = stable.read_bytes() if stable.exists() else None
    before_slots = (
        set((case.manager.directory / "runtimes").iterdir())
        if replacement
        else set()
    )
    sentinel = (
        case.placement.appdata_dir / "user-data"
        if case.placement.appdata_dir is not None
        else None
    )
    if replacement:
        assert sentinel is not None
        sentinel.write_bytes(b"keep existing data")
    failure = InstallationError(f"controlled {boundary} failure")

    with monkeypatch.context() as patch:
        if boundary == "begin":
            original_begin = case.manager.begin_operation

            def fail_begin(plan: InstallPlan) -> InstallationInspection:
                original_begin(plan)
                raise failure

            patch.setattr(case.manager, "begin_operation", fail_begin)
        elif boundary == "prepare":

            def fail_prepare(*args, **kwargs):
                raise failure

            patch.setattr(installation, "_prepare_candidate", fail_prepare)
        elif boundary == "resources":
            original_initialize = case.manager.initialize

            def fail_resources(*, context):
                original_initialize(context=context)
                raise failure

            patch.setattr(case.manager, "initialize", fail_resources)
        elif boundary == "publication":
            original_publish = _command_publication._publish_stable_command

            def fail_publication(*args, **kwargs):
                original_publish(*args, **kwargs)
                raise failure

            patch.setattr(
                _command_publication,
                "_publish_stable_command",
                fail_publication,
            )
        else:

            def fail_activation(**kwargs):
                raise failure

            patch.setattr(case.manager, "commit_install", fail_activation)
        with pytest.raises(InstallationError) as caught:
            case.install()
        assert caught.value is failure
        assert (
            "AppRC installation changes were rolled back."
            in caught.value.__notes__
        )

    restored = case.manager.inspect()
    assert restored.record == before.record
    assert restored.revision == before.revision
    assert (
        record_path.read_bytes() if record_path.exists() else None
    ) == before_bytes
    assert (stable.read_bytes() if stable.exists() else None) == before_command
    slots = case.manager.directory / "runtimes"
    assert (set(slots.iterdir()) if slots.exists() else set()) == before_slots
    assert not tuple(case.manager.directory.glob(".publication-*"))
    if replacement:
        assert (
            sentinel is not None
            and sentinel.read_bytes() == b"keep existing data"
        )
    else:
        assert (
            case.placement.config_dir is not None
            and not case.placement.config_dir.exists()
        )
        assert (
            case.placement.appdata_dir is not None
            and not case.placement.appdata_dir.exists()
        )
        assert case.placement.state_dir is not None
        if case.placement.state_dir.exists():
            assert case.placement.logs_dir is not None
            assert {
                path.name for path in case.placement.state_dir.iterdir()
            } == {
                ".apprc-owner.json",
                managed_lock_path(case.placement.logs_dir).name,
            }
    assert case.install().status == "ready"


@pytest.mark.parametrize("boundary", ["commit-readback", "cleanup"])
def test_committed_installation_survives_followup_failure(
    native_case: _NativeCase,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    boundary: str,
) -> None:
    case = native_case
    if boundary == "commit-readback":
        original_commit = case.manager.commit_install

        def commit_then_raise(**kwargs):
            original_commit(**kwargs)
            raise OSError("controlled activation read-back failure")

        monkeypatch.setattr(case.manager, "commit_install", commit_then_raise)
    else:

        def cleanup_then_raise(*args):
            raise OSError("controlled cleanup failure")

        monkeypatch.setattr(
            _command_publication,
            "cleanup_publication_images",
            cleanup_then_raise,
        )
    result = case.install()
    assert result.status == "ready"
    assert result.record is not None and result.record.operation is None
    saved = case.manager.inspect().record
    assert (
        saved is not None
        and saved.active_runtime == result.record.active_runtime
    )
    assert "Installation succeeded" in caplog.text


@pytest.mark.parametrize(
    "obstruction",
    [
        "foreign-command",
        "resource-payload",
        "busy-candidate",
        "authority-write",
    ],
)
def test_failed_rollback_preserves_payload_and_both_errors(
    native_case: _NativeCase,
    monkeypatch: pytest.MonkeyPatch,
    obstruction: str,
) -> None:
    case = native_case
    stable = case.manager.directory / installation._command_filename("fixture")
    payload: Path | None = None
    failure = InstallationError("controlled activation failure")

    def fail_activation(**kwargs):
        nonlocal payload
        if obstruction == "foreign-command":
            stable.write_bytes(b"foreign command")
        elif obstruction == "resource-payload":
            assert case.placement.appdata_dir is not None
            payload = case.placement.appdata_dir / "application-data"
            payload.write_bytes(b"application-owned data")
        raise failure

    monkeypatch.setattr(case.manager, "commit_install", fail_activation)
    if obstruction == "busy-candidate":
        monkeypatch.setattr(
            installation, "try_retire_runtime_slot", lambda slot: False
        )
    elif obstruction == "authority-write":

        def fail_restore(**kwargs):
            raise OSError("controlled authority restoration failure")

        monkeypatch.setattr(case.manager, "rollback_installation", fail_restore)
    with pytest.raises(
        InstallationError, match="rollback is incomplete"
    ) as caught:
        case.install()
    assert "controlled activation failure" in str(caught.value)
    assert isinstance(caught.value.__cause__, BaseExceptionGroup)
    assert failure in caught.value.__cause__.exceptions
    incomplete = case.manager.inspect()
    assert incomplete.status == "incomplete"
    assert (
        incomplete.record is not None
        and incomplete.record.operation is not None
    )
    assert incomplete.record.operation.diagnostic is not None
    assert (
        "rollback is incomplete"
        in incomplete.record.operation.diagnostic.message
    )
    if obstruction == "foreign-command":
        assert stable.read_bytes() == b"foreign command"
    if payload is not None:
        assert payload.read_bytes() == b"application-owned data"


@pytest.mark.parametrize(
    "pending", (False, True), ids=("clean", "saved-incomplete")
)
def test_first_editable_probe_failure_is_clean_and_immediately_retryable(
    native_case: _NativeCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pending: bool,
) -> None:
    """Exercise registration rollback without writing into the running venv."""
    from apprc.definition import resolution

    project = tmp_path / "checkout"
    project.mkdir()
    project_file = project / "pyproject.toml"
    project_file.write_bytes(b"[project]\nname='fixture'\nversion='1.0'\n")
    source_bytes = project_file.read_bytes()
    environment = Path(sys.prefix).resolve(strict=True)
    configuration = environment / "pyvenv.cfg"
    environment_bytes = (
        configuration.read_bytes() if configuration.exists() else None
    )
    command = tmp_path / "fixture-command"
    command.write_bytes(b"developer command")
    commands = tmp_path / "commands"
    commands.mkdir()
    manager = InstallationManager(
        native_case.manager.spec,
        environment={"PATH": str(commands)},
        directory=native_case.manager.directory,
    )
    runtime = EditableCheckout(project, environment)
    monkeypatch.setattr(
        resolution, "resolve_editable_environment", lambda project: environment
    )
    monkeypatch.setattr(
        installation, "_validate_editable_metadata", lambda *args: None
    )
    monkeypatch.setattr(installation, "runtime_command", lambda *args: command)
    monkeypatch.setattr(
        installation,
        "_probe_runtime_observations",
        lambda *args, **kwargs: (runtime, {"version": "1.0"}),
    )

    def initialize(*args, **kwargs):
        return manager.initialize(context=args[4]).paths

    monkeypatch.setattr(installation, "_initialize_runtime", initialize)

    def register() -> InstallationInspection:
        return installation.register_editable_application(
            manager,
            native_case.identity,
            runtime,
            native_case.placement,
            command_name="fixture",
            uv=native_case.uv,
            command_directory=commands,
        )

    failure = InstallationError("controlled editable probe failure")
    with monkeypatch.context() as patch:

        def fail_probe(*args, **kwargs):
            raise failure

        patch.setattr(installation, "_probe_runtime_observations", fail_probe)
        with pytest.raises(InstallationError) as caught:
            register()
        assert caught.value is failure
    assert manager.inspect().status == "missing"
    assert not tuple(commands.iterdir())
    if pending:
        from apprc.definition.installation import InstallationDiagnostic

        plan = manager.plan_install(
            native_case.identity,
            runtime,
            native_case.placement,
            command_name="fixture",
        )
        started = manager.begin_operation(plan)
        assert started.revision is not None
        failed = manager.fail_operation(
            operation_id=plan.operation_id,
            expected_revision=started.revision,
            diagnostic=InstallationDiagnostic(
                "runtime-incomplete",
                "Earlier staging failure.",
                "Retry installation.",
            ),
        )
        other_project = tmp_path / "other-checkout"
        other_project.mkdir()
        (other_project / "pyproject.toml").write_bytes(source_bytes)
        with pytest.raises(InstallationError, match="another checkout"):
            installation.register_editable_application(
                manager,
                native_case.identity,
                replace(runtime, project=other_project),
                native_case.placement,
                command_name="fixture",
                uv=native_case.uv,
                command_directory=commands,
            )
        assert manager.inspect().record == failed.record
    registered = register()
    assert registered.status == "ready"
    assert (
        registered.record is not None
        and registered.record.active_runtime == runtime
    )
    assert project_file.read_bytes() == source_bytes
    assert (
        configuration.read_bytes() if configuration.exists() else None
    ) == environment_bytes


@pytest.mark.parametrize(
    "scenario",
    [
        "commit",
        "rollback",
        "path-failure",
        "occupied",
        "update",
        "changed-command",
        "linked-command",
        "linked-parent",
        "changed-authority",
    ],
)
def test_windows_default_command_is_transactional(
    native_case, monkeypatch, tmp_path, scenario
):
    import os
    from types import SimpleNamespace

    from apprc.distribution.runtime import _os_integration
    from apprc.distribution.runtime import _windows_command_path as windows
    from apprc.distribution.runtime._install_progress import (
        installation_progress,
    )

    bin_dir = tmp_path / "shared-bin"
    command = bin_dir / installation._command_filename("fixture")
    monkeypatch.setattr(windows, "enabled", lambda: True)
    monkeypatch.setattr(
        _os_integration, "os", SimpleNamespace(**(vars(os) | {"name": "nt"}))
    )
    monkeypatch.setattr(windows, "is_user_directory", lambda *args: True)
    monkeypatch.setattr(
        installation, "_default_command_directory", lambda *args: bin_dir
    )

    changes = []

    def persist(path, environment):
        assert command.is_file()
        assert native_case.manager.inspect().status == "ready"
        changes.append(path)
        if scenario == "path-failure":
            raise OSError("Registry denied")
        return True

    monkeypatch.setattr(windows, "ensure_user_path", persist)
    monkeypatch.setattr(windows, "notify_path_change", lambda: None)
    if scenario == "rollback":

        def fail(*args, **kwargs):
            raise OSError("Controlled activation failure")

        monkeypatch.setattr(InstallationManager, "commit_install", fail)
    if scenario == "occupied":
        bin_dir.mkdir()
        command.write_bytes(b"foreign")
    if scenario in {
        "changed-command",
        "linked-command",
        "linked-parent",
        "changed-authority",
    }:
        original_finish = installation._finish_installation

        def change_after_commit(manager, result):
            result = original_finish(manager, result)
            if scenario == "changed-command":
                command.write_bytes(b"replaced command")
            elif scenario == "linked-command":
                target = tmp_path / "other-command"
                target.write_bytes(command.read_bytes())
                command.unlink()
                command.symlink_to(target)
            elif scenario == "linked-parent":
                target = tmp_path / "other-bin"
                bin_dir.rename(target)
                bin_dir.symlink_to(target, target_is_directory=True)
            else:
                from apprc.user_files.installation.coordination import (
                    write_record,
                )

                assert result.record is not None
                write_record(
                    manager.directory,
                    replace(result.record, support_version="changed"),
                    expected_revision=result.revision,
                )
            return result

        monkeypatch.setattr(
            installation, "_finish_installation", change_after_commit
        )
    events = []
    with installation_progress(events.append):
        if scenario in {"rollback", "occupied"}:
            with pytest.raises((OSError, InstallationError)):
                native_case.install()
            assert not changes
            if scenario == "rollback":
                assert native_case.manager.inspect().status == "missing"
                assert not command.exists()
            else:
                assert command.read_bytes() == b"foreign"
            return
        assert native_case.install().status == "ready"
    if scenario in {
        "changed-command",
        "linked-command",
        "linked-parent",
        "changed-authority",
    }:
        assert not changes
        assert any(
            event.kind == "warning" and event.path == command
            for event in events
        )
        return
    if scenario == "update":
        monkeypatch.setattr(windows, "is_on_path", lambda *args: True)
        monkeypatch.setattr(
            installation,
            "_default_command_directory",
            lambda *args: pytest.fail("Reuse the existing bin"),
        )
        assert native_case.install().status == "ready"
    assert changes == [bin_dir] * (2 if scenario == "update" else 1)
    assert any(
        event.status == "PUBLISHED" and Path(event.path) == command
        for event in events
        if event.path is not None
    )
    if scenario == "path-failure":
        assert any(
            event.kind == "warning"
            and event.path == command
            and "Registry denied" in event.message
            for event in events
        )
    else:
        assert any(
            event.status == "UPDATED" and event.message == "User PATH"
            for event in events
        )


@pytest.mark.parametrize(
    ("original", "retry"),
    [
        ("default", "default"),
        ("explicit", "default"),
        ("default", "explicit"),
        ("default", "repair"),
        ("explicit", "repair"),
        ("stable-only", "default"),
    ],
)
def test_pending_windows_publication_preserves_path_intent(
    native_case, monkeypatch, tmp_path, original, retry
):
    import os
    from types import SimpleNamespace

    import apprc.utils as ut
    from apprc.distribution.runtime import _os_integration
    from apprc.distribution.runtime import _windows_command_path as windows

    case = native_case
    bin_dir = tmp_path / "shared-bin"
    bin_dir.mkdir()
    monkeypatch.setattr(windows, "enabled", lambda: True)
    monkeypatch.setattr(
        _os_integration, "os", SimpleNamespace(**(vars(os) | {"name": "nt"}))
    )
    monkeypatch.setattr(windows, "is_user_directory", lambda *args: True)
    monkeypatch.setattr(
        installation, "_default_command_directory", lambda *args: bin_dir
    )
    monkeypatch.setattr(
        installation, "_command_directory", lambda *args: bin_dir
    )
    changes = []
    monkeypatch.setattr(
        windows,
        "ensure_user_path",
        lambda path, env: changes.append(path) or True,
    )
    monkeypatch.setattr(windows, "notify_path_change", lambda: None)

    def attempt(selected=None):
        return installation.install_application(
            case.manager,
            case.identity,
            RuntimeSlot(
                uuid4(),
                ProjectSnapshot(
                    ut.sha256_file(case.archive), "b" * 64, "c" * 40
                ),
                RuntimeSelection("3.14"),
            ),
            case.placement,
            command_name="fixture",
            setup_version="1.0",
            project_archive=case.archive,
            manager_executable=case.setup,
            uv=case.uv,
            command_directory=selected,
        )

    with monkeypatch.context() as interrupt:
        if original == "stable-only":
            interrupt.setattr(windows, "enabled", lambda: False)

        def stop_before_publication(*args, **kwargs):
            raise SystemExit(91)

        interrupt.setattr(
            _command_publication,
            "_publish_stable_command",
            stop_before_publication,
        )
        interrupt.setattr(
            installation, "_failed_operation", stop_before_publication
        )
        with pytest.raises(SystemExit):
            attempt(bin_dir if original == "explicit" else None)
    pending = case.manager.inspect().record
    assert pending is not None and pending.operation is not None
    if original == "stable-only":
        assert len(pending.operation.publication) == 1
    else:
        assert pending.operation.publication[1].update_user_path is (
            original == "default"
        )
    assert not changes

    def reuse_prepared(manager, plan, runtime, *args, **kwargs):
        return replace(
            runtime, version="1.0", python_version="3.14"
        ), manager.inspect().revision

    monkeypatch.setattr(installation, "_prepare_candidate", reuse_prepared)
    if retry == "repair":
        pending = case.manager.inspect()
        assert pending.revision is not None
        with pytest.raises(InstallationError, match="changed before recovery"):
            installation._repair_managed_application(
                case.manager,
                manager_executable=case.setup,
                uv=case.uv,
                expected_revision="0" * 64,
            )
        assert case.manager.inspect() == pending
        result = installation._repair_managed_application(
            case.manager,
            manager_executable=case.setup,
            uv=case.uv,
            expected_revision=pending.revision,
        )
    else:
        result = attempt(bin_dir if retry == "explicit" else None)
    assert result.status == "ready"
    assert changes == (
        [bin_dir] if original == "default" and retry != "explicit" else []
    )
