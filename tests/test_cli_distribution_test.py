"""Protect real-machine guided testing around uninstall and preflight boundaries."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
import typer
from typer._click import ClickException
from typer.core import TyperCommand

from apprc import AppRC
from apprc.definition.installation import (
    CleanupInventory,
    InventoryEntry,
    UninstallPlan,
    InstallationError,
    InstallationInspection,
)
from apprc.distribution.runtime._uninstall_controller import (
    UninstallPreparation,
)
from apprc.interfaces.cli import _distribution_test as guide
from apprc.interfaces.cli._distribution_command import CheckoutAuthoring
from apprc.services.installation import InstallationManager
from tests.support_installation import installation_record


def _manager(tmp_path: Path) -> InstallationManager:
    app = AppRC(
        app_id="coordination-fixture", command_name="coordination-fixture"
    )
    return InstallationManager(app.schema, directory=tmp_path / "installation")


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

    def inspect_after_cleanup() -> InstallationInspection:
        assert not pending.exists()
        return InstallationInspection(
            "missing", manager.directory, None, manager.spec.app_id
        )

    monkeypatch.setattr(guide.time, "sleep", finish_handoff)
    monkeypatch.setattr(manager, "inspect", inspect_after_cleanup)
    monkeypatch.setattr(guide, "_windows_entry", Mock())
    guide._await_uninstall(
        manager, staging, record, tmp_path / "command", "app"
    )
    assert sleeps


def test_handoff_timeout_preserves_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    staging = tmp_path / "handoff"
    (staging / "apprc-uninstall-job").mkdir(parents=True)
    monkeypatch.setattr(
        manager, "inspect", Mock(side_effect=AssertionError("still running"))
    )
    with pytest.raises(
        InstallationError, match="Uninstall did not finish"
    ) as failure:
        guide._await_uninstall(
            manager,
            staging,
            installation_record(),
            tmp_path / "command",
            "app",
            timeout=0,
        )
    assert str(staging) in str(failure.value)
    assert (staging / "apprc-uninstall-job").is_dir()


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
        guide._await_uninstall(
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
        guide._protected_paths((target,), (config,))


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
        guide,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            None, changed, (), (), False
        ),
    )
    execute = Mock(side_effect=AssertionError("must not launch uninstall"))
    monkeypatch.setattr(guide, "_run", execute)
    with pytest.raises(InstallationError, match="preview is unsafe"):
        guide._uninstall(
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
    monkeypatch.setattr(guide, "_uninstall", uninstall)
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
        guide,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            plan, expected, (), (), True
        ),
    )
    execute = Mock(side_effect=AssertionError("must preserve retained config"))
    monkeypatch.setattr(guide, "_run", execute)
    with pytest.raises(InstallationError, match="protected path"):
        guide._uninstall(
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


@pytest.mark.parametrize("declined", [False, True])
def test_uninstall_child_carries_accepted_revision_and_root_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declined: bool
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
        guide,
        "prepare_uninstall",
        lambda *args, **kwargs: UninstallPreparation(
            plan, expected, (), (), True
        ),
    )
    monkeypatch.setattr(guide, "_await_uninstall", lambda *args: expected)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def execute(
        command: list[str], *, cwd: Path, environment: dict[str, str]
    ) -> str:
        calls.append((command, environment))
        if declined:
            raise subprocess.CalledProcessError(1, command)
        return ""

    monkeypatch.setattr(guide, "_run", execute)
    report: dict[str, object] = {}
    outcome = (
        pytest.raises(subprocess.CalledProcessError)
        if declined
        else nullcontext()
    )
    with outcome:
        guide._uninstall(
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
    assert "uninstall_recovery" not in report
    assert not Path(environment["TMPDIR"]).exists()


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
