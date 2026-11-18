"""Caught installation failures restore authority and exact owned effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import sys
from uuid import uuid4

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
from apprc.distribution.runtime import installation
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

    def install(self) -> InstallationInspection:
        """Run the real controller with a fresh candidate and isolated effects."""
        return installation.install_application(
            self.manager,
            self.identity,
            RuntimeSlot(
                uuid4(),
                ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
                RuntimeSelection("3.14"),
            ),
            self.placement,
            command_name="fixture",
            project_archive=self.archive,
            manager_executable=self.setup,
            uv=self.uv,
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
) -> tuple[RuntimeSlot, str]:
    """Replace dependency acquisition while exercising real lifecycle writes."""
    slot = manager.directory / "runtimes" / str(runtime.slot_id)
    slot.mkdir(parents=True)
    (slot / "project.zip").write_bytes(archive.read_bytes())
    (slot / ".venv").mkdir()
    observed = replace(runtime, version="1.0", python_version="3.14")
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
            original_publish = installation._publish_stable_command

            def fail_publication(*args, **kwargs):
                original_publish(*args, **kwargs)
                raise failure

            patch.setattr(
                installation, "_publish_stable_command", fail_publication
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
            installation, "_cleanup_publication_images", cleanup_then_raise
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
