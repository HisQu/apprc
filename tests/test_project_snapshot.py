"""Integrity checks for immutable managed project snapshots."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import select
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

from filelock import Timeout
import pytest

import apprc as rc
from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.models import AppCapabilities, NativeBinding
from apprc.distribution.runtime import _leases
from apprc.distribution.runtime._manager import _forward
from apprc.distribution.runtime.acquisition import materialize_project_snapshot
from apprc.distribution.runtime.backend import runtime_command, runtime_environment
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)


def _retirement_probe_worker(
    directory: Path,
    slot: Path,
    connection: Connection,
) -> None:
    """Probe lifecycle-lock contention and runtime retirement from a process."""
    try:
        if connection.recv() != "check-selection":
            return
        try:
            with installation_lock(directory, timeout=0.25):
                pass
        except Timeout:
            connection.send("selection-blocked")
        else:
            connection.send("selection-lock-free")

        if connection.recv() != "check-child":
            return
        try:
            with installation_lock(directory, timeout=0.5):
                pass
        except Timeout:
            connection.send("child-lock-still-held")
        else:
            connection.send(("retired", try_retire_runtime_slot(slot)))
    except BaseException as error:
        connection.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


@pytest.mark.skipif(
    os.name == "nt", reason="Managed lease inheritance uses POSIX descriptors."
)
def test_native_forward_selection_handoff_releases_namespace_before_child_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the selected slot protected without holding the lifecycle lock."""
    app_id = "forward-lease-fixture"
    command_name = "forward-lease-fixture"
    directory = tmp_path / "installation"
    declaration = rc.AppRC(app_id=app_id, command_name=command_name)
    manager = InstallationManager(
        declaration.schema,
        environment={"PATH": os.environ.get("PATH", "")},
        directory=directory,
    )
    identity = InstallationIdentity(
        app_id, app_id, "forward_lease_fixture", None, (command_name,)
    )
    source = ProjectSnapshot("a" * 64, "b" * 64, "c" * 40)
    selection = RuntimeSelection(sys.executable)
    runtime = RuntimeSlot(
        uuid4(),
        source,
        selection,
        version="1.0.0",
        python_version=sys.version.split()[0],
    )
    binding = NativeBinding(
        identity=identity,
        command_name=command_name,
        display_name="Forward lease fixture",
        version="1.0.0",
        source=source,
        selection=selection,
        capabilities=AppCapabilities(),
        layout=Layout.native(),
        bootstrap_env_prefix="APPRC",
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=command_name,
        generation_id=uuid4(),
        support_version="0.34.0",
        placement=InstallationPlacement(Layout.native()),
        status="ready",
        active_runtime=runtime,
    )
    slot = directory / "runtimes" / str(runtime.slot_id)
    prefix_bin = slot / ".venv" / "bin"
    prefix_bin.mkdir(parents=True)
    resource = slot / "slot-resource.txt"
    resource.write_text("selected slot", encoding="utf-8")
    ready_fifo = tmp_path / "forward-child-ready"
    release_fifo = tmp_path / "forward-child-release"
    os.mkfifo(ready_fifo)
    os.mkfifo(release_fifo)
    ready_fd = os.open(ready_fifo, os.O_RDWR | os.O_NONBLOCK)
    release_fd = os.open(release_fifo, os.O_RDWR | os.O_NONBLOCK)
    result = tmp_path / "forward-child-result"
    command = runtime_command(directory, runtime, command_name)
    command.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        f"ready = os.open({str(ready_fifo)!r}, os.O_WRONLY)\n"
        "os.write(ready, b'R')\nos.close(ready)\n"
        f"release = os.open({str(release_fifo)!r}, os.O_RDONLY)\n"
        "os.read(release, 1)\nos.close(release)\n"
        f"data = open({str(resource)!r}, encoding='utf-8').read()\n"
        f"open({str(result)!r}, 'w', encoding='utf-8').write(data)\n",
        encoding="utf-8",
    )
    command.chmod(0o700)
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)

    acquisition_paused = Event()
    continue_selection = Event()
    child_ready = Event()
    parent_lease_closed = Event()
    acquire_lease = _leases.acquire_runtime_lease_locked

    def pause_before_lease(
        selected_slot: Path,
    ) -> _leases.RuntimeLease:
        acquisition_paused.set()
        if not continue_selection.wait(timeout=5):
            raise RuntimeError("Timed out waiting to continue runtime selection.")
        lease = acquire_lease(selected_slot)

        def close_parent_lease_after_child_starts() -> None:
            if child_ready.wait(timeout=5):
                lease.close()
                parent_lease_closed.set()

        Thread(target=close_parent_lease_after_child_starts, daemon=True).start()
        return lease

    monkeypatch.setattr(
        _leases, "acquire_runtime_lease_locked", pause_before_lease
    )
    process_context = multiprocessing.get_context("spawn")
    parent, child = process_context.Pipe()
    retirer = process_context.Process(
        target=_retirement_probe_worker,
        args=(directory, slot, child),
    )
    retirer.start()
    child.close()
    executor = ThreadPoolExecutor(max_workers=1)
    forward = None

    try:
        forward = executor.submit(_forward, binding, manager, ["probe"])
        assert acquisition_paused.wait(timeout=5)
        parent.send("check-selection")
        assert parent.poll(timeout=2), "Retirer did not report selection lock state."
        assert parent.recv() == "selection-blocked"

        continue_selection.set()
        assert select.select([ready_fd], [], [], 5)[0], (
            "Forwarded child did not signal that it was ready."
        )
        assert os.read(ready_fd, 1) == b"R"
        child_ready.set()
        assert parent_lease_closed.wait(timeout=2)
        parent.send("check-child")
        assert parent.poll(timeout=2), "Retirer did not report child lock state."
        assert parent.recv() == ("retired", False)
        retirer.join(timeout=2)
        assert not retirer.is_alive()

        os.write(release_fd, b"X")
        assert forward.result(timeout=10) == 0
        assert result.read_text(encoding="utf-8") == "selected slot"
        assert try_retire_runtime_slot(slot)
    finally:
        child_ready.set()
        continue_selection.set()
        try:
            os.write(release_fd, b"X")
        except OSError:
            pass
        if forward is not None:
            try:
                forward.result(timeout=10)
            except BaseException:
                pass
        executor.shutdown(wait=True)
        if retirer.is_alive():
            try:
                parent.send("stop")
            except (BrokenPipeError, EOFError, OSError):
                pass
            retirer.join(timeout=2)
        if retirer.is_alive():
            retirer.terminate()
            retirer.join(timeout=2)
        parent.close()
        if slot.exists():
            assert try_retire_runtime_slot(slot)
        os.close(ready_fd)
        os.close(release_fd)
        ready_fifo.unlink(missing_ok=True)
        release_fifo.unlink(missing_ok=True)


def _snapshot(archive: Path, *, project_path: str = ".") -> ProjectSnapshot:
    with ZipFile(archive) as package:
        lock = package.read("uv.lock")
    return ProjectSnapshot(
        digest=hashlib.sha256(archive.read_bytes()).hexdigest(),
        lock_digest=hashlib.sha256(lock).hexdigest(),
        commit="a" * 40,
        project_path=project_path,
    )


def test_materialization_keeps_complete_snapshot_and_lock_unchanged(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "project.zip"
    lock = b"version = 1\n"
    with ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", '[project]\nname="fixture"\n')
        package.writestr("uv.lock", lock)
        package.writestr("workspace/member/pyproject.toml", "[project]\n")
        package.writestr("workspace/member/source.py", "VALUE = 7\n")
    destination = tmp_path / "slot-source"
    materialize_project_snapshot(archive, destination, _snapshot(archive))
    assert (destination / "uv.lock").read_bytes() == lock
    assert (destination / "workspace/member/source.py").read_text() == "VALUE = 7\n"


def test_materialization_rejects_changed_lock_before_extraction(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "project.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", '[project]\nname="fixture"\n')
        package.writestr("uv.lock", "original")
    snapshot = replace(_snapshot(archive), lock_digest="b" * 64)
    destination = tmp_path / "slot-source"
    with pytest.raises(InstallationError, match="lock SHA-256 differs"):
        materialize_project_snapshot(archive, destination, snapshot)
    assert not destination.exists()


def test_materialization_rejects_archive_digest_mismatch_before_extraction(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "project.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", '[project]\nname="fixture"\n')
        package.writestr("uv.lock", "lock")
    snapshot = _snapshot(archive)
    archive.write_bytes(archive.read_bytes() + b"tampering")
    destination = tmp_path / "slot-source"
    with pytest.raises(InstallationError, match="SHA-256 does not match"):
        materialize_project_snapshot(archive, destination, snapshot)
    assert not destination.exists()



def test_materialization_selects_nested_workspace_project_and_shared_lock(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "workspace.zip"
    lock = b"shared workspace lock"
    with ZipFile(archive, "w") as package:
        package.writestr(
            "pyproject.toml", "[tool.uv.workspace]\nmembers=['apps/*']\n"
        )
        package.writestr("uv.lock", lock)
        package.writestr(
            "apps/fixture/pyproject.toml", '[project]\nname="fixture"\n'
        )
        package.writestr("apps/fixture/app.py", "VALUE = 3\n")
    snapshot = _snapshot(archive, project_path="apps/fixture")
    destination = tmp_path / "slot-source"
    materialize_project_snapshot(archive, destination, snapshot)
    assert (destination / "apps/fixture/app.py").read_text() == "VALUE = 3\n"
    assert (destination / "uv.lock").read_bytes() == lock



def test_runtime_environment_removes_interpreter_injection_only() -> None:
    captured = runtime_environment(
        {
            "VIRTUAL_ENV": "/foreign",
            "PYTHONHOME": "/foreign",
            "PYTHONPATH": "/foreign",
            "UV_ACTIVE": "1",
            "UV_TOOL_DIR": "/foreign",
            "PYAPP_BOOTSTRAP": "foreign",
            "UV_INDEX_URL": "https://index.invalid",
            "HTTPS_PROXY": "https://proxy.invalid",
        }
    )
    assert captured == {
        "UV_INDEX_URL": "https://index.invalid",
        "HTTPS_PROXY": "https://proxy.invalid",
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX inherited descriptor semantics")
def test_child_inherits_runtime_lease_after_parent_closes(tmp_path: Path) -> None:
    slot = tmp_path / "installation" / "runtimes" / str(uuid4())
    slot.mkdir(parents=True)
    lease = acquire_runtime_lease(slot)
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
            stdin=subprocess.PIPE,
            env=lease.environment(dict(os.environ)),
            **lease.subprocess_options(),
        )
    except BaseException:
        lease.close()
        raise
    try:
        lease.close()
        assert not try_retire_runtime_slot(slot)
    finally:
        if process.poll() is None:
            assert process.stdin is not None
            process.stdin.close()
        assert process.wait(timeout=10) == 0
    assert try_retire_runtime_slot(slot)


def test_materialization_rejects_embedded_nul_member_name_before_extraction(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "nul-member.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", '[project]\nname="fixture"\n')
        package.writestr("uv.lock", "lock")
        member = ZipInfo("placeholder")
        member.filename = "unsafe\x00tail"
        package.writestr(member, "unsafe")

    destination = tmp_path / "nul-source"
    with pytest.raises(InstallationError, match="Unsafe source archive member"):
        materialize_project_snapshot(archive, destination, _snapshot(archive))
    assert not destination.exists()
    assert not (tmp_path / "unsafe").exists()


def test_materialization_rejects_archive_traversal_before_extraction(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "project.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", '[project]\nname="fixture"\n')
        package.writestr("uv.lock", "lock")
        package.writestr("../escape", "unsafe")
    destination = tmp_path / "slot-source"
    with pytest.raises(InstallationError, match="Unsafe source archive member"):
        materialize_project_snapshot(archive, destination, _snapshot(archive))
    assert not destination.exists()
    assert not (tmp_path / "escape").exists()
