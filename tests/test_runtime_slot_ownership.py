"""Editable runtime paths and exact global-command ownership."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationTarget,
    OwnedOutput,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime._integration import (
    publish_global_command,
    remove_owned_command,
)
from apprc.distribution.runtime._leases import try_retire_runtime_slot
from apprc.distribution.runtime.backend import (
    runtime_command,
    runtime_interpreter,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.operations import plan_repair


def test_repair_resumes_pending_managed_candidate_before_active_editable_guidance(
    tmp_path: Path,
) -> None:
    identity = InstallationIdentity(
        "repair-fixture", "repair-fixture", "app", None, ("app",)
    )
    placement = InstallationPlacement(Layout.native())
    editable = EditableCheckout(
        tmp_path / "checkout", tmp_path / "checkout" / ".venv"
    )
    candidate = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.12", ("feature",)),
    )
    target = InstallationTarget(identity, placement, candidate)
    operation_id = uuid4()
    generation_id = uuid4()
    operation = InstallationOperation(
        operation_id, "replace", "failed", target, placement
    )
    record = InstallationRecord(
        3,
        identity,
        "app",
        generation_id,
        "1",
        placement,
        "incomplete",
        active_runtime=editable,
        operation=operation,
    )
    inspection = InstallationInspection(
        "incomplete",
        tmp_path / "installation",
        "revision",
        identity.app_id,
        record,
    )

    resumed = plan_repair(identity, candidate, placement, inspection=inspection)

    assert resumed.operation_id == operation_id
    assert resumed.target == target
    assert isinstance(resumed.target.runtime, RuntimeSlot)
    assert resumed.target.runtime.source == candidate.source
    assert resumed.target.runtime.selection == candidate.selection
    assert resumed.target.runtime.slot_id == candidate.slot_id

    pure_editable = InstallationRecord(
        3,
        identity,
        "app",
        generation_id,
        "1",
        placement,
        "ready",
        active_runtime=editable,
    )
    with pytest.raises(InstallationError, match="uv sync --locked"):
        plan_repair(
            identity,
            candidate,
            placement,
            inspection=InstallationInspection(
                "ready",
                tmp_path / "installation",
                "revision",
                identity.app_id,
                pure_editable,
            ),
        )


def test_editable_runtime_uses_recorded_environment_without_copying_checkout(
    tmp_path: Path,
) -> None:
    project = tmp_path / "checkout"
    environment = project / ".venv"
    project.mkdir()
    environment.mkdir()
    sentinel = project / "tracked.py"
    sentinel.write_text("VALUE = 1\n", encoding="utf-8")
    runtime = EditableCheckout(project, environment)

    assert runtime_interpreter(tmp_path / "installation", runtime) == (
        environment
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    assert runtime_command(tmp_path / "installation", runtime, "fixture") == (
        environment
        / ("Scripts/fixture.exe" if os.name == "nt" else "bin/fixture")
    )
    assert sentinel.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert set(project.iterdir()) == {environment, sentinel}
    with pytest.raises(InstallationError):
        runtime_command(tmp_path / "installation", runtime, "../outside")


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX global commands are symlinks"
)
def test_global_command_removal_requires_exact_recorded_symlink(
    tmp_path: Path,
) -> None:
    source = tmp_path / "checkout" / ".venv" / "bin" / "fixture"
    source.parent.mkdir(parents=True)
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    commands = tmp_path / "commands"
    commands.mkdir()
    command = commands / "fixture"
    output = publish_global_command(command, source)
    assert command.is_symlink()
    assert command.readlink() == source

    with pytest.raises(
        InstallationError, match="Refusing to replace an unowned command"
    ):
        publish_global_command(command, source)
    assert remove_owned_command(output)
    assert not command.exists()


def test_retirement_unlinks_slot_symlinks_without_touching_external_target(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    create_private_directory_if_missing(directory)
    slot = directory / "runtimes" / str(uuid4())
    outside = tmp_path / "user-data"
    outside.mkdir(parents=True)
    marker = outside / "keep.txt"
    marker.write_text("user-owned", encoding="utf-8")
    slot.mkdir(parents=True)
    (slot / "external-link").symlink_to(outside, target_is_directory=True)
    (slot / "owned-file").write_text("managed", encoding="utf-8")

    assert try_retire_runtime_slot(slot)
    assert not slot.exists()
    assert marker.read_text(encoding="utf-8") == "user-owned"


def test_modified_global_command_is_not_removed(tmp_path: Path) -> None:
    command = tmp_path / "commands" / "fixture"
    command.parent.mkdir()
    command.write_text("user command", encoding="utf-8")
    output = OwnedOutput("command", str(command), "a" * 64)

    with pytest.raises(InstallationError, match="modified global command"):
        remove_owned_command(output)
    assert command.read_text(encoding="utf-8") == "user command"
