"""One preparation attempt never rebuilds a freshly prepared candidate twice."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

import apprc as rc
from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationError,
    ProjectSnapshot,
    RuntimeSlot,
    RuntimeSelection,
    OperationStep,
)
from apprc.distribution.runtime import installation
from apprc.distribution.runtime._install_progress import (
    InstallProgress,
    installation_progress,
)
from apprc.services.installation import InstallationManager


@pytest.mark.parametrize(
    ("prepared", "directories", "probe_fails", "builds", "probes"),
    [
        (False, False, True, 1, 1),
        (True, True, True, 1, 2),
        (True, False, True, 1, 1),
        (True, True, False, 0, 1),
    ],
)
def test_candidate_rebuild_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared: bool,
    directories: bool,
    probe_fails: bool,
    builds: int,
    probes: int,
) -> None:
    app = rc.AppRC(app_id="preparation", paths=rc.Paths())
    manager = InstallationManager(
        app.schema, directory=tmp_path / "installation", environment={}
    )
    archive = tmp_path / "project.zip"
    archive.write_bytes(b"snapshot")
    identity = InstallationIdentity(
        "preparation",
        "preparation",
        "preparation",
        "preparation:APP_RC",
        ("demo",),
    )
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot(
            hashlib.sha256(b"snapshot").hexdigest(), "b" * 64, "c" * 40
        ),
        RuntimeSelection("3.14"),
    )
    placement = InstallationPlacement(layout=rc.Layout.native())
    plan = manager.plan_install(
        identity, runtime, placement, command_name="demo"
    )
    current = manager.begin_operation(plan)
    slot = manager.directory / "runtimes" / str(runtime.slot_id)
    if prepared:
        for step in (
            OperationStep.SOURCE_VERIFIED,
            OperationStep.RUNTIME_PREPARED,
        ):
            assert current.revision is not None
            current = manager.record_step(
                operation_id=plan.operation_id,
                expected_revision=current.revision,
                step=step,
            )
    if directories:
        (slot / "source").mkdir(parents=True)
        (slot / ".venv").mkdir()
    counts = {"build": 0, "probe": 0}
    events: list[InstallProgress] = []

    def rebuild(*args, **kwargs):
        assert any(event.status == "VERIFIED" for event in events)
        counts["build"] += 1
        (slot / "source").mkdir(exist_ok=True)
        (slot / ".venv").mkdir(exist_ok=True)

    observed = replace(runtime, version="1.0", python_version="3.14")

    def probe(*args, **kwargs):
        counts["probe"] += 1
        if probe_fails and counts["probe"] == 1:
            raise InstallationError("unrelated probe failure")
        return observed, {}

    monkeypatch.setattr(installation, "_snapshot_metadata", lambda *args: "1.0")
    monkeypatch.setattr(installation, "_rebuild_candidate_runtime", rebuild)
    monkeypatch.setattr(installation, "_probe_runtime_observations", probe)
    monkeypatch.setattr(
        installation, "_initialize_runtime", lambda *args, **kwargs: ()
    )
    with (
        installation_progress(events.append),
        installation.installation_lock(manager.directory),
    ):
        if probe_fails and not (prepared and directories):
            with pytest.raises(
                InstallationError, match="unrelated probe failure"
            ):
                installation._prepare_candidate(
                    manager,
                    plan,
                    runtime,
                    archive,
                    tmp_path / "uv",
                    environment={},
                    manager_executable=tmp_path / "manager",
                )
        else:
            result, _revision = installation._prepare_candidate(
                manager,
                plan,
                runtime,
                archive,
                tmp_path / "uv",
                environment={},
                manager_executable=tmp_path / "manager",
            )
            assert result == observed
            assert any(event.status == "VALIDATED" for event in events)
            assert any(event.status == "REUSED" for event in events) == (
                builds == 0
            )
    assert counts == {"build": builds, "probe": probes}
