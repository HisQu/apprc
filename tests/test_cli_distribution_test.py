"""Protect real-machine guided testing around uninstall and preflight boundaries."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import typer
from typer._click import ClickException
from typer.core import TyperCommand

from apprc import AppRC
from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstallationOperation,
    InventoryEntry,
    UninstallPlan,
)
from apprc.distribution.runtime import _uninstall_controller as removal
from apprc.distribution.runtime._uninstall_controller import (
    UninstallPreparation,
)
from apprc.interfaces.cli import _distribution_test as guide
from apprc.interfaces.cli._distribution_authoring import CheckoutAuthoring
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.codec import encode_record
from tests.support_installation import installation_record


def _manager(tmp_path: Path) -> InstallationManager:
    app = AppRC(
        app_id="coordination-fixture", command_name="coordination-fixture"
    )
    return InstallationManager(app.schema, directory=tmp_path / "installation")


def _write_handoff_plan(
    recovery: Path,
    directory: Path,
    app_id: str,
    generation_id: UUID,
    operation_id: UUID,
    staged_revision: str,
) -> None:
    (recovery.parent / "handoff.json").write_text(
        json.dumps(
            {
                "directory": str(directory),
                "app_id": app_id,
                "generation_id": str(generation_id),
                "operation_id": str(operation_id),
                "expected_revision": staged_revision,
                "original_pid": 1,
                "original_start": "started",
                "readiness_token": uuid4().hex,
                "recovery_directory": str(recovery),
                "wait": False,
                "complete": False,
                "categories": [],
                "forget_retained": False,
                "inventory": [],
                "retained": [],
                "manager_executable": None,
                "manager_executable_revision": None,
            }
        ),
        encoding="utf-8",
    )


def test_waits_for_handoff_staging_after_launcher_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    record = installation_record()
    staging = tmp_path / "handoff"
    staging.mkdir()
    pending = staging / "apprc-uninstall-job"
    pending.mkdir()
    sleeps: list[float] = []

    def finish_handoff(delay: float) -> None:
        sleeps.append(delay)
        pending.rmdir()

    def verify_after_cleanup(*args: object) -> None:
        assert not pending.exists()

    missing = InstallationInspection(
        "missing", manager.directory, None, manager.spec.app_id
    )
    verify = Mock(side_effect=verify_after_cleanup)
    monkeypatch.setattr(removal.time, "sleep", finish_handoff)
    monkeypatch.setattr(manager, "inspect", lambda: missing)
    monkeypatch.setattr(removal, "verify_windows_registration", verify)
    result = removal._await_uninstall(
        manager, staging, record, tmp_path / "command", "app"
    )
    assert sleeps
    assert result == missing
    verify.assert_called_once_with(manager, tmp_path / "command", None, "app")


def test_handoff_timeout_preserves_recovery(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    staging = tmp_path / "handoff"
    (staging / "apprc-uninstall-job").mkdir(parents=True)
    with pytest.raises(
        InstallationError, match="Uninstall did not finish"
    ) as failure:
        removal._await_uninstall(
            manager,
            staging,
            installation_record(),
            tmp_path / "command",
            "app",
            timeout=0,
        )
    assert str(staging) in str(failure.value)
    assert (staging / "apprc-uninstall-job").is_dir()


@pytest.mark.parametrize(
    "scenario",
    [
        "current",
        "stale",
        "retry-failed-again",
        "other-operation",
        "other-generation",
        "other-plan-generation",
        "other-kind",
        "other-app",
        "other-directory",
        "missing-plan",
    ],
)
def test_handoff_reports_only_attributable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    manager = _manager(tmp_path)
    previous = installation_record()
    staged_revision = "1" * 64
    operation_id = uuid4()
    staging = tmp_path / "handoff"
    pending = staging / "apprc-uninstall-job"
    recovery = pending / "recovery"
    recovery.mkdir(parents=True)
    diagnostic = InstallationDiagnostic(
        "uninstall-incomplete",
        "Application cleanup was blocked.",
        "Review the recorded cleanup effects before retrying.",
    )
    operation = InstallationOperation(
        operation_id=uuid4() if scenario == "other-operation" else operation_id,
        kind="repair" if scenario == "other-kind" else "uninstall",
        phase="failed",
        intended=None,
        placement=previous.placement,
        diagnostic=diagnostic,
    )
    record = replace(
        previous,
        generation_id=(
            uuid4()
            if scenario == "other-generation"
            else previous.generation_id
        ),
        status="incomplete",
        operation=operation,
    )
    failure = InstallationInspection(
        "incomplete",
        manager.directory,
        staged_revision if scenario == "stale" else "2" * 64,
        manager.spec.app_id,
        record,
    )
    if scenario != "missing-plan":
        _write_handoff_plan(
            recovery,
            tmp_path / "other-installation"
            if scenario == "other-directory"
            else manager.directory,
            "other-app" if scenario == "other-app" else manager.spec.app_id,
            uuid4()
            if scenario == "other-plan-generation"
            else previous.generation_id,
            operation_id,
            staged_revision,
        )
    inspect = (
        Mock(side_effect=[replace(failure, revision=staged_revision), failure])
        if scenario == "retry-failed-again"
        else Mock(return_value=failure)
    )
    sleep = Mock(
        side_effect=[None]
        if scenario == "retry-failed-again"
        else AssertionError("the handoff outcome is already known")
    )
    monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(removal.time, "sleep", sleep)

    attributable = scenario in {"current", "retry-failed-again"}
    message = diagnostic.message if attributable else "Uninstall did not finish"
    with pytest.raises(InstallationError, match=message) as error:
        removal._await_uninstall(
            manager,
            staging,
            previous,
            tmp_path / "command",
            "app",
            timeout=300 if attributable else 0,
        )
    if attributable:
        assert diagnostic.recovery in str(error.value)
    else:
        assert diagnostic.message not in str(error.value)
        assert str(staging) in str(error.value)
    assert sleep.call_count == (1 if scenario == "retry-failed-again" else 0)
    assert recovery.is_dir()


def test_handoff_does_not_accept_a_different_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    previous = installation_record()
    replacement = installation_record()
    current = InstallationInspection(
        "removed-retained",
        manager.directory,
        "new",
        manager.spec.app_id,
        replacement,
    )
    monkeypatch.setattr(manager, "inspect", lambda: current)
    with pytest.raises(InstallationError, match="expected installation"):
        removal._await_uninstall(
            manager, tmp_path, previous, tmp_path / "command", "app"
        )


@pytest.mark.parametrize("deletion", ["config", "ancestor", "child"])
def test_protected_configuration_blocks_overlapping_removal(
    tmp_path: Path, deletion: str
) -> None:
    config = tmp_path / "retained-config"
    target = {
        "config": config,
        "ancestor": tmp_path,
        "child": config / "settings",
    }[deletion]
    with pytest.raises(InstallationError, match="protected path"):
        removal.check_protected_removal_paths((target,), (config,))


def test_changed_uninstall_preview_never_starts_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    record = installation_record()
    expected = InstallationInspection(
        "removed-retained",
        manager.directory,
        "old",
        manager.spec.app_id,
        record,
    )
    changed = replace(expected, revision="changed")
    monkeypatch.setattr(
        removal,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            None, changed, (), (), False
        ),
    )
    execute = Mock(side_effect=AssertionError("must not launch uninstall"))
    monkeypatch.setattr(removal.subprocess, "run", execute)
    with pytest.raises(InstallationError, match="preview is unsafe"):
        removal.run_checked_uninstall(
            tmp_path / "command",
            "app",
            manager,
            expected,
            tmp_path / "published",
            (),
            keep_config=True,
            assume_yes=True,
            root=tmp_path,
            environment={},
            report={},
        )
    execute.assert_not_called()


@pytest.mark.parametrize("invalid_setup", [False, True])
def test_preflight_failure_leaves_personal_installation_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_setup: bool
) -> None:
    app = AppRC(
        app_id="coordination-fixture", command_name="coordination-fixture"
    )
    manager = _manager(tmp_path)
    record = installation_record()
    inspection = InstallationInspection(
        "removed-retained",
        manager.directory,
        "old",
        manager.spec.app_id,
        record,
    )
    monkeypatch.setattr(app, "installation", lambda **kwargs: manager)
    monkeypatch.setattr(manager, "inspect", lambda: inspection)
    prefix = tmp_path / "environment"
    command = (
        prefix
        / ("Scripts" if os.name == "nt" else "bin")
        / (
            "coordination-fixture.exe"
            if os.name == "nt"
            else "coordination-fixture"
        )
    )
    command.parent.mkdir(parents=True)
    command.touch()
    uv = tmp_path / "uv"
    uv.touch()
    monkeypatch.setattr(guide.sys, "prefix", str(prefix))
    monkeypatch.setattr(guide, "_revision", lambda root: "a" * 40)
    monkeypatch.setattr(guide.shutil, "which", lambda name: str(uv))
    if invalid_setup:
        monkeypatch.setattr(
            guide,
            "_check_setup_pair",
            Mock(side_effect=ValueError("Invalid checksum")),
        )
    uninstall = Mock(
        side_effect=AssertionError("must not uninstall existing installation")
    )
    monkeypatch.setattr(guide, "run_checked_uninstall", uninstall)
    expected_message = (
        "Invalid checksum" if invalid_setup else "pre-existing installation"
    )
    ctx = typer.Context(TyperCommand("dist-test"))
    with pytest.raises(ClickException, match=expected_message):
        guide.run_distribution_test(
            ctx,
            CheckoutAuthoring(tmp_path, "unused.backend"),
            app,
            "app",
            "coordination-fixture",
            managed=invalid_setup,
            update_from=None,
            assume_yes=True,
        )
    uninstall.assert_not_called()
    (report_file,) = (tmp_path / ".cache" / "apprc" / "dist-test").glob(
        "*.json"
    )
    report = json.loads(report_file.read_text())
    assert report["status"] == "failed"
    assert report["manual_observation"] == "not verified"


def test_retained_config_is_rechecked_against_final_uninstall_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    record = installation_record()
    expected = InstallationInspection(
        "removed-retained",
        manager.directory,
        "old",
        manager.spec.app_id,
        record,
    )
    config = tmp_path / "retained-config"
    plan = UninstallPlan(
        manager.directory,
        "old",
        record.generation_id,
        record.identity.app_id,
        uuid4(),
        record.placement,
        CleanupInventory(
            (InventoryEntry(config, "directory", None, "config"),)
        ),
    )
    monkeypatch.setattr(
        removal,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            plan, expected, (), (), True
        ),
    )
    execute = Mock(side_effect=AssertionError("must preserve retained config"))
    monkeypatch.setattr(removal.subprocess, "run", execute)
    with pytest.raises(InstallationError, match="protected path"):
        removal.run_checked_uninstall(
            tmp_path / "command",
            "app",
            manager,
            expected,
            tmp_path / "published",
            (config,),
            keep_config=True,
            assume_yes=True,
            root=tmp_path,
            environment={},
            report={},
        )
    execute.assert_not_called()


@pytest.mark.parametrize("changed_at", ["initial", "preview"])
def test_guided_uninstall_child_rejects_changed_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_at: str
) -> None:
    from typer.testing import CliRunner

    from apprc.definition.resolution import CliRuntimeOptions
    from apprc.distribution.runtime import _uninstall_controller as controller
    from apprc.interfaces.cli import installation_command
    from apprc.interfaces.cli.context import InstallationCommandContext

    manager = _manager(tmp_path)
    record = installation_record()
    expected = InstallationInspection(
        "removed-retained",
        manager.directory,
        "accepted",
        manager.spec.app_id,
        record,
    )
    current = (
        replace(expected, revision="changed")
        if changed_at == "initial"
        else expected
    )
    context = InstallationCommandContext(
        CliRuntimeOptions(),
        CliRuntimeOptions(),
        {"_APPRC_DIST_TEST_UNINSTALL_REVISION": "accepted"},
        current,
        manager,
    )
    monkeypatch.setattr(
        installation_command, "_inspection", lambda ctx: context
    )
    preview = Mock(
        return_value=UninstallPreparation(
            None, replace(expected, revision="changed"), (), (), False
        )
    )
    launch = Mock(
        side_effect=AssertionError("changed authority must not be removed")
    )
    monkeypatch.setattr(controller, "prepare_uninstall", preview)
    monkeypatch.setattr(controller, "start_uninstall_handoff", launch)
    app = typer.Typer()
    installation_command.mount_installation_group(
        app, installation_management=True
    )

    result = CliRunner().invoke(app, ["uninstall", "--yes"])
    assert result.exit_code != 0
    assert "Installation changed" in result.output
    launch.assert_not_called()
    assert preview.call_count == (0 if changed_at == "initial" else 1)


@pytest.mark.parametrize("uninstall_outcome", ["success", "declined", "failed"])
def test_uninstall_child_carries_accepted_revision_and_root_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uninstall_outcome: str
) -> None:
    manager = _manager(tmp_path)
    record = installation_record()
    expected = InstallationInspection(
        "removed-retained",
        manager.directory,
        "accepted",
        manager.spec.app_id,
        record,
    )
    plan = UninstallPlan(
        manager.directory,
        "accepted",
        record.generation_id,
        record.identity.app_id,
        uuid4(),
        record.placement,
        CleanupInventory(),
    )
    monkeypatch.setattr(
        removal,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            plan, expected, (), (), True
        ),
    )
    monkeypatch.setattr(removal.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(removal, "verify_windows_registration", Mock())
    calls: list[tuple[list[str], dict[str, str]]] = []
    diagnostic = InstallationDiagnostic(
        "uninstall-incomplete",
        "Application cleanup provider refused to uninstall.",
        "Review the application's recorded cleanup effects.",
    )
    declined = uninstall_outcome == "declined"

    if uninstall_outcome == "failed":
        monkeypatch.setattr(
            removal.time,
            "sleep",
            Mock(side_effect=AssertionError("failure should be prompt")),
        )

    def execute(
        command: list[str], *, cwd: Path, env: dict[str, str], check: bool
    ) -> str:
        assert check
        calls.append((command, env))
        if declined:
            raise subprocess.CalledProcessError(1, command)
        if uninstall_outcome == "failed":
            # > The child creates its own operation ID after the preview.
            operation = InstallationOperation(
                operation_id=uuid4(),
                kind="uninstall",
                phase="pending",
                intended=None,
                placement=record.placement,
            )
            pending = replace(record, status="incomplete", operation=operation)
            manager.directory.mkdir()
            authority = manager.directory / "installation.json"
            authority.write_bytes(encode_record(pending))
            staged_revision = manager.inspect().revision
            assert staged_revision is not None
            recovery = Path(env["TMPDIR"]) / "apprc-uninstall-job" / "recovery"
            recovery.mkdir(parents=True)
            _write_handoff_plan(
                recovery,
                manager.directory,
                manager.spec.app_id,
                record.generation_id,
                operation.operation_id,
                staged_revision,
            )
            failed = replace(operation, phase="failed", diagnostic=diagnostic)
            authority.write_bytes(
                encode_record(replace(pending, operation=failed))
            )
        return ""

    monkeypatch.setattr(removal.subprocess, "run", execute)
    report: dict[str, object] = {}
    if declined:
        outcome = pytest.raises(subprocess.CalledProcessError)
    elif uninstall_outcome == "failed":
        outcome = pytest.raises(InstallationError, match=diagnostic.message)
    else:
        outcome = nullcontext()
    with outcome:
        removal.run_checked_uninstall(
            tmp_path / "checkout-command",
            "app",
            manager,
            expected,
            tmp_path / "published",
            (),
            keep_config=True,
            assume_yes=not declined,
            root=tmp_path,
            environment={},
            report=report,
            root_arguments=(
                "--layout",
                "single-root",
                "--app-root",
                str(tmp_path / "resources"),
            ),
        )
    ((command, environment),) = calls
    assert command == [
        str(tmp_path / "checkout-command"),
        "--layout",
        "single-root",
        "--app-root",
        str(tmp_path / "resources"),
        "app",
        "uninstall",
        "--keep-config",
        *([] if declined else ["--yes"]),
    ]
    assert environment["_APPRC_DIST_TEST_UNINSTALL_REVISION"] == "accepted"
    staging = Path(environment["TMPDIR"])
    if uninstall_outcome == "failed":
        assert report["uninstall_recovery"] == str(staging)
        assert (staging / "apprc-uninstall-job" / "recovery").is_dir()
    else:
        assert "uninstall_recovery" not in report
        assert not staging.exists()


def test_distribution_capture_keeps_selectors_without_resolving_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.main import get_command

    from apprc.cli import CliRuntime
    from apprc.definition.paths import Layout
    from apprc.definition.resolution import CliRuntimeOptions
    from apprc.interfaces.cli._distribution_command import build_authoring_group

    app_rc = AppRC(
        app_id="coordination-fixture", command_name="coordination-fixture"
    )
    app = typer.Typer()
    app.add_typer(
        build_authoring_group(
            CheckoutAuthoring(tmp_path, "unused"),
            app_rc,
            "app",
            installation_management=True,
        ),
        name="dist",
    )
    runtime = CliRuntime(app_rc)
    command = get_command(app)
    ctx = typer.Context(command)
    ctx.invoked_subcommand = "dist"
    monkeypatch.chdir(tmp_path)
    layout = Layout.single_root(tmp_path / "resources")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "Capturing authoring selectors must not resolve resources"
        )

    monkeypatch.setattr(app_rc, "paths", forbidden)
    runtime.prepare(
        ctx,
        CliRuntimeOptions(env_files=(Path("selection.env"),), layout=layout),
    )
    captured = ctx.meta["apprc.distribution.runtime_options"]
    assert isinstance(captured, CliRuntimeOptions)
    assert captured.env_files == (tmp_path / "selection.env",)
    assert captured.layout == layout


def test_nonexecutable_setup_is_rejected_during_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = tmp_path / "setup"
    monkeypatch.setattr(
        guide, "_targets", lambda **kwargs: ("x86_64-unknown-linux-gnu",)
    )
    monkeypatch.setattr(guide, "_check", lambda *args, **kwargs: (setup,))
    monkeypatch.setattr(guide, "_inspect_native_setup", Mock())
    monkeypatch.setattr(CheckoutAuthoring, "backend", Mock())
    monkeypatch.setattr(guide.os, "access", lambda *args: False)

    with pytest.raises(InstallationError, match="not executable"):
        guide._check_setup_pair(
            CheckoutAuthoring(tmp_path, "unused"), "fixture", "a" * 40, None
        )
