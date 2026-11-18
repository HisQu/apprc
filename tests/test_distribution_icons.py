"""Verify managed icons remain owned support across runtime updates."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    OwnedOutput,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime import _icons
from apprc.distribution.runtime._uninstall_controller import _support_inventory
from apprc.distribution.runtime.uninstall_handoff import _remove_inventory
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation


def _runtime(directory: Path, content: bytes) -> RuntimeSlot:
    slot_id = uuid4()
    archive = directory / "runtimes" / str(slot_id) / "project.zip"
    archive.parent.mkdir(parents=True)
    with ZipFile(archive, "w") as snapshot:
        snapshot.writestr(
            "member/pyproject.toml",
            "[tool.apprc.distribution]\nicons = { linux = 'assets/icon.png' }\n",
        )
        snapshot.writestr("member/assets/icon.png", content)
    source = ProjectSnapshot(
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        "0" * 64,
        "a" * 40,
        "member",
    )
    return RuntimeSlot(
        slot_id,
        source,
        RuntimeSelection("3.13"),
        version="1",
        python_version="3.13.1",
    )


def _record(directory: Path) -> InstallationRecord:
    return InstallationRecord(
        3,
        InstallationIdentity(
            "fixture", "fixture", "fixture", None, ("fixture",)
        ),
        "fixture",
        uuid4(),
        "1",
        InstallationPlacement(Layout.native()),
        "ready",
        active_runtime=_runtime(directory, b"original"),
    )


def test_managed_icon_reuses_identical_bytes_and_uninstall_removes_its_outputs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(_icons, "sys", SimpleNamespace(platform="linux"))
    with installation_lock(tmp_path):
        write_record(tmp_path, _record(tmp_path), expected_revision=None)
        ready = inspect_installation(tmp_path, app_id="fixture")
        ready, original = _icons.ready_icon(ready, publish=True)
        assert original is not None and original.read_bytes() == b"original"
        assert _icons.ready_icon(ready) == (ready, original)
        assert _icons.ready_icon(ready, publish=True) == (ready, original)

        assert ready.record is not None
        updated = replace(
            ready.record, active_runtime=_runtime(tmp_path, b"updated")
        )
        write_record(tmp_path, updated, expected_revision=ready.revision)
        ready, latest = _icons.ready_icon(
            inspect_installation(tmp_path, app_id="fixture"), publish=True
        )
        assert latest is not None and latest.read_bytes() == b"updated"
        assert original.read_bytes() == b"original"
        assert ready.record is not None
        inventory, diagnostics = _support_inventory(
            ready.record, tmp_path, complete=False
        )
        assert {entry.path for entry in inventory} == {original, latest}
        assert not diagnostics
        _remove_inventory(inventory)
        assert not original.exists() and not latest.exists()


@pytest.mark.parametrize("failure", ["collision", "write"])
def test_icon_publication_failure_preserves_a_usable_install(
    tmp_path, monkeypatch, failure, caplog
):
    monkeypatch.setattr(_icons, "sys", SimpleNamespace(platform="linux"))
    digest = hashlib.sha256(b"original").hexdigest()
    destination = tmp_path / f"icon-{digest}.png"
    if failure == "collision":
        destination.write_bytes(b"other owner")
    with installation_lock(tmp_path):
        write_record(tmp_path, _record(tmp_path), expected_revision=None)
        ready = inspect_installation(tmp_path, app_id="fixture")
        with monkeypatch.context() as failed:
            if failure == "write":

                def fail(*args):
                    raise OSError("Controlled icon write failure")

                failed.setattr(_icons, "write_bytes_atomic", fail)
            result, icon = _icons.ready_icon(ready, publish=True)
        assert result.status == "ready"
        assert icon is None
        assert "Application icon was not installed" in caplog.text
        if failure == "collision":
            assert result == ready
            assert destination.read_bytes() == b"other owner"
        else:
            assert result.record is not None
            assert result.record.owned_outputs == (
                OwnedOutput("support", destination.name, digest),
            )
            assert _icons.ready_icon(result, publish=True) == (
                result,
                destination,
            )
