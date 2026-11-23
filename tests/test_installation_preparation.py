"""Managed preparation verifies and checkpoints the exact runtime candidate."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest

import apprc as rc
from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    OperationStep,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.distribution.runtime import acquisition
from apprc.distribution.runtime._install_progress import (
    InstallProgress,
    installation_progress,
)
from apprc.distribution.runtime.installation import candidate
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.coordination import installation_lock


@pytest.mark.parametrize(
    ("prepared", "directories", "probe_failures", "builds", "probes"),
    [
        (False, False, 1, 1, 1),
        (True, True, 1, 1, 2),
        (True, True, 2, 1, 2),
        (True, False, 1, 1, 1),
        (True, True, 0, 0, 1),
    ],
)
def test_candidate_rebuild_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared: bool,
    directories: bool,
    probe_failures: int,
    builds: int,
    probes: int,
) -> None:
    app = rc.AppRC(app_id="preparation", paths=rc.Paths())
    manager = InstallationManager(
        app.schema, directory=tmp_path / "installation", environment={}
    )
    archive = tmp_path / "project.zip"
    lock = b"version = 1\n"
    with ZipFile(archive, "w") as snapshot:
        snapshot.writestr(
            "pyproject.toml",
            "[project]\nname = 'preparation'\nversion = '1.0'\n"
            "[project.scripts]\ndemo = 'preparation:main'\n",
        )
        snapshot.writestr("uv.lock", lock)
    identity = InstallationIdentity(
        "preparation",
        "preparation",
        "preparation",
        None,
        ("demo",),
    )
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "c" * 40,
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
        slot.mkdir(parents=True)
        (slot / "project.zip").write_bytes(archive.read_bytes())
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
        (slot / "source" / "retained-marker").touch()
    build_count = 0
    probe_count = 0
    events: list[InstallProgress] = []

    def sync(
        _uv: Path,
        _directory: Path,
        _identity: InstallationIdentity,
        _runtime: RuntimeSlot,
        *,
        environment: Mapping[str, str],
    ) -> None:
        nonlocal build_count
        assert any(event.status == "VERIFIED" for event in events)
        assert (slot / "source" / "uv.lock").read_bytes() == lock
        build_count += 1
        (slot / ".venv").mkdir()

    observed = replace(runtime, version="1.0", python_version="3.14")

    def probe(*args, **kwargs) -> tuple[RuntimeSlot, dict[str, object]]:
        nonlocal probe_count
        probe_count += 1
        if probe_count <= probe_failures:
            raise InstallationError("unrelated probe failure")
        return observed, {}

    def prepare() -> tuple[RuntimeSlot, str]:
        return candidate.prepare_candidate(
            manager,
            plan,
            runtime,
            archive,
            tmp_path / "uv",
            environment={},
            manager_executable=tmp_path / "manager",
        )

    monkeypatch.setattr(candidate, "sync_runtime_slot", sync)
    monkeypatch.setattr(candidate, "_probe_runtime_observations", probe)
    fails = probes <= probe_failures
    with (
        installation_progress(events.append),
        installation_lock(manager.directory),
    ):
        if fails:
            with pytest.raises(
                InstallationError, match="unrelated probe failure"
            ):
                prepare()
        else:
            result, revision = prepare()
            assert result == observed
            assert revision == manager.inspect().revision
            assert any(event.status == "VALIDATED" for event in events)
            assert any(event.status == "REUSED" for event in events) == (
                builds == 0
            )

    assert build_count == builds
    assert probe_count == probes
    assert (slot / "project.zip").read_bytes() == archive.read_bytes()
    assert (slot / "source" / "retained-marker").exists() == (builds == 0)
    current = manager.inspect()
    assert current.record is not None
    assert current.record.operation is not None
    expected_steps: tuple[OperationStep, ...] = (
        OperationStep.SOURCE_VERIFIED,
        OperationStep.RUNTIME_PREPARED,
    )
    if not fails:
        expected_steps += (
            OperationStep.RUNTIME_VALIDATED,
            OperationStep.RESOURCES_READY,
        )
    assert current.record.operation.steps == expected_steps


@pytest.mark.parametrize("rebuild", [False, True])
def test_managed_source_is_created_through_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rebuild: bool
) -> None:
    directory = tmp_path / "installation"
    acquisition.create_private_directory_if_missing(directory)
    slot_id = uuid4()
    slot = directory / "runtimes" / str(slot_id)
    slot.mkdir(parents=True)
    source_root = slot / "source"
    if rebuild:
        source_root.mkdir()
        (source_root / "retired").write_text("previous candidate")
    archive = slot / "project.zip"
    lock = b"version = 1\n"
    with ZipFile(archive, "w") as snapshot:
        snapshot.writestr("pyproject.toml", "[project]\nname = 'fixture'\n")
        snapshot.writestr("uv.lock", lock)
    runtime = RuntimeSlot(
        slot_id,
        ProjectSnapshot(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "c" * 40,
        ),
        RuntimeSelection("3.14"),
    )
    real_create = acquisition.create_private_directory_if_missing
    applied: set[Path] = set()

    def create(path: Path) -> None:
        was_missing = not path.exists()
        real_create(path)
        if was_missing:
            applied.add(path)

    monkeypatch.setattr(
        acquisition, "create_private_directory_if_missing", create
    )
    monkeypatch.setattr(
        acquisition,
        "_path_permissions_are_private",
        lambda path: path in applied,
    )
    monkeypatch.setattr(candidate, "sync_runtime_slot", lambda *a, **kw: None)
    candidate._rebuild_candidate_runtime(
        directory,
        archive,
        InstallationIdentity(
            "fixture", "fixture", "fixture", None, ("fixture",)
        ),
        runtime,
        tmp_path / "uv",
        {},
    )
    assert applied == {source_root}
    assert (source_root / "uv.lock").read_bytes() == lock
    assert not (source_root / "retired").exists()
