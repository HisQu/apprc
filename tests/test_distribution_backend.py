"""Managed runtime backend snapshot and rollback safety."""

from __future__ import annotations

import contextlib
import hashlib
import io
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    OwnedOutput,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime.backend import runtime_environment
from apprc.distribution.runtime.installation import (
    _backup_path,
    _discard_backup,
    _restore_owned_output,
    _snapshot_metadata,
    offer_configuration_setup,
)


def test_runtime_environment_removes_manager_and_python_injection_only() -> None:
    captured = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/injected",
        "PYTHONHOME": "/injected-home",
        "PYTHONWARNINGS": "ignore",
        "PYAPP": "unexpected-binary",
        "PYAPP_ARGS": "unexpected-options",
        "_APPRC_RUNTIME_LEASE_HANDLE": "1234",
        "_APPRC_NATIVE_MANAGER": "unexpected-manager",
        "_APPRC_NATIVE_EXECUTABLE": "/unexpected",
        "_APPRC_APPLICATION_DIAGNOSTICS": "unexpected",
        "UV_INDEX_URL": "https://index.example/simple",
        "API_TOKEN": "preserve-me",
    }

    cleaned = runtime_environment(captured)

    assert cleaned == {
        "PATH": "/usr/bin",
        "UV_INDEX_URL": "https://index.example/simple",
        "API_TOKEN": "preserve-me",
    }


def test_expected_version_comes_from_digest_verified_retained_archive(
    tmp_path: Path,
) -> None:
    project = tmp_path / "mutable-source"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='snapshot-fixture'\nversion='9.9.9'\n",
        encoding="utf-8",
    )
    retained_pyproject = (
        "[build-system]\nrequires=[]\nbuild-backend='setuptools.build_meta'\n"
        "[project]\nname='snapshot-fixture'\nversion='1.2.3'\n"
        "requires-python='>=3.12'\n"
        "[project.scripts]\nsnapshot-fixture='snapshot_fixture:main'\n"
    ).encode()
    lock = b"version = 1\n"
    archive = tmp_path / "retained.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", retained_pyproject)
        package.writestr("uv.lock", lock)
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "a" * 40,
        ),
        RuntimeSelection("3.12"),
    )
    identity = InstallationIdentity(
        "snapshot-fixture",
        "snapshot-fixture",
        "snapshot_fixture",
        None,
        ("snapshot-fixture",),
    )

    assert _snapshot_metadata(archive, runtime, identity) == "1.2.3"

    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(InstallationError, match="archive was modified"):
        _snapshot_metadata(archive, runtime, identity)


@pytest.mark.parametrize("third_party_change", (False, True))
def test_transaction_rollback_restores_only_its_exact_published_output(
    tmp_path: Path,
    third_party_change: bool,
) -> None:
    destination = tmp_path / "stable-command"
    destination.write_bytes(b"previous command")
    backup = _backup_path(destination)
    destination.write_bytes(b"new command")
    output = OwnedOutput(
        "command",
        str(destination),
        hashlib.sha256(b"new command").hexdigest(),
    )
    if third_party_change:
        destination.write_bytes(b"concurrent unknown command")

    restored = _restore_owned_output(destination, backup, output)

    if third_party_change:
        assert not restored
        assert destination.read_bytes() == b"concurrent unknown command"
    else:
        assert restored
        assert destination.read_bytes() == b"previous command"
    _discard_backup(backup)


def test_zero_resource_capabilities_do_not_offer_configuration_setup(
    tmp_path: Path,
) -> None:
    identity = InstallationIdentity("fixture", "fixture", "fixture", None, ("fixture",))
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.12"),
        version="1.0.0",
        python_version="3.12.0",
    )
    placement = InstallationPlacement(Layout.native())
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="fixture",
        generation_id=uuid4(),
        support_version="1",
        placement=placement,
        status="ready",
        active_runtime=runtime,
    )
    inspection = InstallationInspection(
        "ready", tmp_path / "installation", "revision", identity.app_id, record
    )
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        offered = offer_configuration_setup(
            inspection,
            skip=False,
            input_stream=io.StringIO(""),
        )

    assert not offered
    assert output.getvalue() == ""
