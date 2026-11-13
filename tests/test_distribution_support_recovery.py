"""Managed runtime preparation and publication preserve unknown state."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.distribution.runtime import installation
from apprc.distribution.runtime._integration import publish_global_command
from apprc.distribution.runtime._leases import try_retire_runtime_slot


def _runtime(source: ProjectSnapshot) -> RuntimeSlot:
    return RuntimeSlot(uuid4(), source, RuntimeSelection("3.12"))


def test_broken_pending_candidate_repair_waits_for_busy_runtime_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "installation"
    runtime = _runtime(ProjectSnapshot("a" * 64, "b" * 64, "c" * 40))
    slot = directory / "runtimes" / str(runtime.slot_id)
    source = slot / "source"
    environment = slot / ".venv"
    source.mkdir(parents=True)
    environment.mkdir()
    source_marker = source / "user-marker"
    environment_marker = environment / "environment-marker"
    source_marker.write_text("retained candidate source", encoding="utf-8")
    environment_marker.write_text("partially prepared", encoding="utf-8")
    archive = tmp_path / "retained.zip"
    archive.write_bytes(b"retained immutable project")
    uv = tmp_path / "uv"
    uv.write_bytes(b"uv test executable")
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )

    monkeypatch.setattr(
        installation,
        "try_acquire_runtime_quiescence",
        lambda _slot: None,
    )

    with pytest.raises(InstallationError, match="Candidate runtime is busy"):
        installation._rebuild_candidate_runtime(
            slot,
            archive,
            directory,
            identity,
            runtime,
            uv,
            {"PATH": os.environ.get("PATH", "")},
        )

    assert (
        source_marker.read_text(encoding="utf-8") == "retained candidate source"
    )
    assert (
        environment_marker.read_text(encoding="utf-8") == "partially prepared"
    )
    assert archive.read_bytes() == b"retained immutable project"


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication uses symlinks")
def test_global_command_rejection_preserves_unknown_symlink(
    tmp_path: Path,
) -> None:
    command = tmp_path / "commands" / "fixture"
    command.parent.mkdir()
    source = tmp_path / "runtime" / "bin" / "fixture"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"runtime command")
    unknown_target = tmp_path / "user-command"
    unknown_target.write_bytes(b"keep this user command")
    command.symlink_to(unknown_target)
    original_link = command.readlink()

    with pytest.raises(InstallationError, match="unowned"):
        publish_global_command(command, source)

    assert command.is_symlink()
    assert command.readlink() == original_link
    assert unknown_target.read_bytes() == b"keep this user command"


def test_stable_command_rejection_preserves_unknown_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "installation" / "fixture"
    destination.parent.mkdir()
    destination.write_bytes(b"user-owned command")
    source = tmp_path / "manager"
    source.write_bytes(b"new stable manager")

    with pytest.raises(InstallationError, match="unowned stable command"):
        installation._publish_stable_command(destination, source, previous=())

    assert destination.read_bytes() == b"user-owned command"
    assert tuple(destination.parent.iterdir()) == (destination,)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO synchronization")
def test_sync_delegate_holds_runtime_lease_after_driver_death(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    runtime = _runtime(ProjectSnapshot("a" * 64, "b" * 64, "c" * 40))
    slot = directory / "runtimes" / str(runtime.slot_id)
    project = slot / "source"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='1.0'\n",
        encoding="utf-8",
    )
    ready_fifo = tmp_path / "delegate-ready"
    release_fifo = tmp_path / "delegate-release"
    os.mkfifo(ready_fifo)
    os.mkfifo(release_fifo)
    ready_fd = os.open(ready_fifo, os.O_RDWR | os.O_NONBLOCK)
    release_fd = os.open(release_fifo, os.O_RDWR | os.O_NONBLOCK)
    done = tmp_path / "delegate-done"
    uv = tmp_path / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        f"ready = os.open({str(ready_fifo)!r}, os.O_WRONLY)\n"
        "os.write(ready, b'R')\nos.close(ready)\n"
        f"release = os.open({str(release_fifo)!r}, os.O_RDONLY)\n"
        "os.read(release, 1)\nos.close(release)\n"
        f"open({str(done)!r}, 'w', encoding='utf-8').write('done')\n",
        encoding="utf-8",
    )
    uv.chmod(0o700)
    driver = f"""
import os
from pathlib import Path
from uuid import UUID
from apprc.definition.installation import InstallationIdentity, ProjectSnapshot, RuntimeSelection, RuntimeSlot
from apprc.distribution.runtime.backend import sync_runtime_slot
directory = Path({str(directory)!r})
runtime = RuntimeSlot(UUID({str(runtime.slot_id)!r}), ProjectSnapshot('a'*64, 'b'*64, 'c'*40), RuntimeSelection('3.12'))
identity = InstallationIdentity('fixture', 'fixture', 'fixture', None, ('fixture',))
sync_runtime_slot(Path({str(uv)!r}), directory, identity, runtime, environment=dict(os.environ))
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    process: subprocess.Popen[str] | None = None
    released = False
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", driver],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            try:
                if os.read(ready_fd, 1) == b"R":
                    ready = True
                    break
            except BlockingIOError:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.01)
        assert ready, "UV delegate did not reach its controlled wait."
        process.kill()
        process.communicate(timeout=10)
        assert not try_retire_runtime_slot(slot)

        os.write(release_fd, b"R")
        released = True
        deadline = time.monotonic() + 10
        retired = False
        while time.monotonic() < deadline:
            if done.is_file() and try_retire_runtime_slot(slot):
                retired = True
                break
            time.sleep(0.01)
        assert retired, (
            "Runtime lease remained held after the UV delegate exited."
        )
    finally:
        if not released:
            os.write(release_fd, b"R")
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        os.close(ready_fd)
        os.close(release_fd)
        ready_fifo.unlink(missing_ok=True)
        release_fifo.unlink(missing_ok=True)
        if slot.exists():
            deadline = time.monotonic() + 10
            while slot.exists() and time.monotonic() < deadline:
                if try_retire_runtime_slot(slot):
                    break
                time.sleep(0.01)
