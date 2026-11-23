"""Optional setup dispatch preserves successful installation and runtime leases."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import CliRuntimeOptions
from apprc.distribution.runtime.installation import post_install
from apprc.interfaces.cli.config_command._handlers import ConfigCommandHandlers
from apprc.interfaces.cli.mount import mount_app_cli


@pytest.fixture
def ready_inspection(tmp_path: Path) -> InstallationInspection:
    directory = tmp_path / "installation"
    directory.mkdir(mode=0o700)
    identity = InstallationIdentity(
        "offer-demo", "offer-demo", "offer_demo", None, ("demo",)
    )
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.14"),
        version="1",
        python_version="3.14",
    )
    resources = tmp_path / "resources"
    placement = InstallationPlacement(
        Layout.single_root(resources),
        config_dir=resources / "config",
        capabilities=frozenset({"config"}),
    )
    record = InstallationRecord(
        3,
        identity,
        "demo",
        uuid4(),
        "1",
        placement,
        "ready",
        active_runtime=runtime,
    )
    return InstallationInspection(
        "ready", directory, "revision", identity.app_id, record
    )


@pytest.mark.parametrize("config_group", ["config", "settings"])
@pytest.mark.parametrize(
    "scenario", ["skip", "noninteractive", "success", "failure"]
)
def test_installed_setup_offer_dispatches_conditionally_and_releases_lease(
    ready_inspection: InstallationInspection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
    config_group: str,
) -> None:
    inspection = ready_inspection
    monkeypatch.setattr(
        post_install, "inspect_installation", lambda *args, **kwargs: inspection
    )
    events: list[str] = []

    class Lease:
        def environment(self, environment):
            return dict(environment)

        def subprocess_options(self):
            return {}

        def close(self):
            events.append("closed")

    def acquire(*args, **kwargs):
        events.append("leased")
        return Lease()

    def run(argv, **kwargs):
        events.append("dispatched")
        assert argv[1:] == [config_group, "setup", "--offer-missing"]
        assert kwargs["check"] is True
        if scenario == "failure":
            raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(post_install, "acquire_runtime_lease", acquire)
    monkeypatch.setattr(post_install.subprocess, "run", run)
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: scenario != "noninteractive")
    result = post_install.offer_configuration_setup(
        inspection,
        skip=scenario == "skip",
        input_stream=stream,
        config_group_name=config_group,
    )
    assert result is (scenario == "success")
    assert events == (
        []
        if scenario in {"skip", "noninteractive"}
        else ["leased", "dispatched", "closed"]
    )
    assert inspection.record is not None
    assert inspection.record.status == "ready"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "error",
    [OSError("cannot start"), subprocess.CalledProcessError(1, "setup")],
)
def test_setup_offer_can_report_process_failure(
    ready_inspection, monkeypatch, error
):
    monkeypatch.setattr(
        post_install, "inspect_installation", lambda *a, **k: ready_inspection
    )

    class Lease:
        def environment(self, environment):
            return dict(environment)

        def subprocess_options(self):
            return {}

        def close(self):
            pass

    monkeypatch.setattr(
        post_install, "acquire_runtime_lease", lambda *a, **k: Lease()
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(post_install.subprocess, "run", fail)
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    with pytest.raises(type(error)):
        post_install.offer_configuration_setup(
            ready_inspection,
            skip=False,
            input_stream=stream,
            raise_on_failure=True,
        )


@pytest.mark.parametrize(
    ("load_layers", "captured_token", "expected_token", "expected_layer"),
    [
        (True, None, "file-token", "managed-layer"),
        (True, "captured-token", "file-token", "managed-layer"),
        (False, "captured-token", "captured-token", "default-layer"),
    ],
)
def test_setup_offer_uses_captured_sources_and_recorded_placement(
    ready_inspection: InstallationInspection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    load_layers: bool,
    captured_token: str | None,
    expected_token: str,
    expected_layer: str,
) -> None:
    """A supplied required value suppresses setup using the install's selectors."""
    record = ready_inspection.record
    assert record is not None
    app_rc = rc.AppRC(
        app_id=record.identity.app_id,
        command_name=record.command_name,
        paths=Paths(config=True),
        layout=record.placement.layout,
        user_dotenv=rc.UserDotenv(),
    )

    @app_rc.config("settings", prefix="OFFER_")
    class Settings(rc.Config):
        token: str = rc.field("OFFER_TOKEN", required=True)
        layer: str = rc.field("OFFER_LAYER", default="default-layer")
        captured: str = rc.field("OFFER_CAPTURED", default="absent")

    manager = app_rc.manage(environment={})
    manager.setup()
    manager.apply_edit(
        manager.plan_update("OFFER_LAYER", "managed-layer", scope="user")
    )
    env_file = tmp_path / "invocation.env"
    env_file.write_text("OFFER_TOKEN=file-token\n", encoding="utf-8")
    captured_environment = {"OFFER_CAPTURED": "captured-value"}
    if captured_token is not None:
        captured_environment["OFFER_TOKEN"] = captured_token
    monkeypatch.delenv("OFFER_TOKEN", raising=False)
    monkeypatch.setenv("OFFER_CAPTURED", "later-value")
    monkeypatch.setattr(
        post_install,
        "inspect_installation",
        lambda *args, **kwargs: ready_inspection,
    )
    events: list[str] = []

    class Lease:
        def environment(self, environment):
            return dict(environment)

        def subprocess_options(self):
            return {}

        def close(self):
            events.append("closed")

    monkeypatch.setattr(
        post_install, "acquire_runtime_lease", lambda *args: Lease()
    )
    app = typer.Typer()
    child_arguments: list[str] = []
    mount_app_cli(
        app,
        app_rc,
        config_group_name="settings",
        args_provider=lambda: child_arguments,
    )
    original_setup = ConfigCommandHandlers.setup

    def setup(self, ctx, **kwargs):
        effective = self.manager(ctx)
        fields = {
            item.field.name: item.value for item in effective.inspect().fields
        }
        assert fields == {
            "token": expected_token,
            "layer": expected_layer,
            "captured": "captured-value",
        }
        assert effective.paths.require("config") == record.placement.config_dir
        events.append("resolved")
        with monkeypatch.context() as child_patch:
            child_patch.setattr(sys.stdin, "isatty", lambda: True)
            original_setup(self, ctx, **kwargs)

    monkeypatch.setattr(ConfigCommandHandlers, "setup", setup)

    def unexpected_prompt(*args, **kwargs):
        pytest.fail("An env-file-supplied required setting must not prompt")

    monkeypatch.setattr(typer, "confirm", unexpected_prompt)

    def run(argv, **kwargs):
        child_arguments[:] = argv[1:]
        result = CliRunner().invoke(app, child_arguments, env=kwargs["env"])
        assert result.exit_code == 0, (result.output, result.exception)
        assert result.output == ""

    monkeypatch.setattr(post_install.subprocess, "run", run)
    before = {
        path: path.read_bytes()
        for path in manager.paths.require("config").rglob("*")
        if path.is_file()
    }
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    assert post_install.offer_configuration_setup(
        ready_inspection,
        skip=False,
        config_group_name="settings",
        runtime_options=CliRuntimeOptions(
            env_files=(env_file,),
            env_file_overrides_os_environ=True,
            load_dotenv_layers=load_layers,
            layout=Layout.single_root(tmp_path / "unrecorded"),
        ),
        environment=captured_environment,
        input_stream=stream,
    )
    assert events == ["resolved", "closed"]
    assert {
        path: path.read_bytes()
        for path in manager.paths.require("config").rglob("*")
        if path.is_file()
    } == before
    assert not (tmp_path / "unrecorded").exists()
