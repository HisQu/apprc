"""Optional setup dispatch preserves successful installation and runtime leases."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime import installation


@pytest.mark.parametrize("config_group", ["config", "settings"])
@pytest.mark.parametrize(
    "scenario", ["skip", "noninteractive", "success", "failure"]
)
def test_installed_setup_offer_dispatches_conditionally_and_releases_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
    config_group: str,
) -> None:
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
    inspection = InstallationInspection(
        "ready", directory, "revision", identity.app_id, record
    )
    monkeypatch.setattr(
        installation, "inspect_installation", lambda *args, **kwargs: inspection
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

    monkeypatch.setattr(installation, "acquire_runtime_lease", acquire)
    monkeypatch.setattr(installation.subprocess, "run", run)
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: scenario != "noninteractive")
    result = installation.offer_configuration_setup(
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
    assert record.status == "ready"
    assert capsys.readouterr().out == ""
