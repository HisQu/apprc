"""Opt-in recovery through the immutable native setup executable."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from apprc.distribution.models import DistributionSpec
from apprc.distribution.project import PreparedProject
from apprc.user_files.installation.discovery import installation_directory
from tests.support_pyapp import isolated_environment, run

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("APPRC_TEST_PYAPP") != "1",
        reason="Set APPRC_TEST_PYAPP=1 to enable native feasibility tests.",
    ),
    pytest.mark.skipif(
        sys.platform != "linux",
        reason="Native recovery process-group interruption is Linux-only.",
    ),
]


NativeProduct = tuple[Path, Path, Path, Path, DistributionSpec, PreparedProject]


@pytest.fixture(autouse=True)
def _require_serial_native_product(request: pytest.FixtureRequest) -> None:
    if hasattr(request.config, "workerinput"):
        pytest.fail("Run PyApp recovery serially with pytest -n 0.")


def _record(directory: Path) -> dict[str, object]:
    value = json.loads(
        (directory / "installation.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _active_slot(record: dict[str, object]) -> str:
    active = record.get("active_runtime")
    assert isinstance(active, dict)
    slot_id = active.get("slot_id")
    assert isinstance(slot_id, str)
    return slot_id


def _pending_slot(record: dict[str, object]) -> str:
    operation = record.get("operation")
    assert isinstance(operation, dict)
    intended = operation.get("intended")
    assert isinstance(intended, dict)
    runtime = intended.get("runtime")
    assert isinstance(runtime, dict)
    slot_id = runtime.get("slot_id")
    assert isinstance(slot_id, str)
    return slot_id


def _install_command(setup: Path, command_directory: Path) -> list[str]:
    return [
        str(setup),
        "app",
        "install",
        "--yes",
        "--skip-setup",
        "--command-directory",
        str(command_directory),
    ]


def _host_environment(root: Path) -> tuple[dict[str, str], Path]:
    environment = isolated_environment(root)
    command_directory = Path(environment["HOME"]).parent / "commands"
    command_directory.mkdir(exist_ok=True)
    environment["PATH"] = str(command_directory)
    return environment, command_directory


def _wait_for_initialization_gate(
    process: subprocess.Popen[str], ready: Path, *, timeout: float = 600
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready.is_file():
            return
        if process.poll() is not None:
            output = process.communicate()
            pytest.fail(
                "Native setup exited before the initialization barrier.\n"
                + (output[0] or "")
                + (output[1] or "")
            )
        time.sleep(0.05)
    pytest.fail("Native setup did not reach the initialization barrier in time.")


def _stop_process_group(
    process: subprocess.Popen[str], release: Path
) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    release.write_text("release", encoding="utf-8")
    try:
        process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=30)


def test_interrupted_initialized_candidate_resumes_exact_retained_slot(
    tmp_path: Path,
    native_product: NativeProduct,
) -> None:
    _project_root, _uv, setup, _checksums, spec, project = native_product
    environment, command_directory = _host_environment(tmp_path / "host")
    ready = tmp_path / "initialize-ready"
    release = tmp_path / "initialize-release"
    interrupted_environment = {
        **environment,
        "APPRC_FIXTURE_INITIALIZE_READY": str(ready),
        "APPRC_FIXTURE_INITIALIZE_RELEASE": str(release),
    }
    install = _install_command(setup, command_directory)
    process = subprocess.Popen(
        install,
        env=interrupted_environment,
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_for_initialization_gate(process, ready)
        directory = installation_directory(
            spec.metadata.identity.app_id,
            environment=environment,
        )
        interrupted = _record(directory)
        operation = interrupted.get("operation")
        assert isinstance(operation, dict)
        assert operation.get("kind") == "install"
        assert operation.get("phase") == "running"
        assert interrupted.get("active_runtime") is None
        steps = operation.get("steps")
        assert isinstance(steps, list)
        assert "runtime_validated" in steps
        assert "resources_ready" not in steps
        candidate_slot = _pending_slot(interrupted)
        slot = directory / "runtimes" / candidate_slot
        assert (slot / "project.zip").is_file()
        assert (slot / "source" / "uv.lock").is_file()
        assert (slot / ".venv").is_dir()
        placement = interrupted.get("placement")
        assert isinstance(placement, dict)
        config_directory = placement.get("config_dir")
        assert isinstance(config_directory, str)
        assert (Path(config_directory) / "native-hook.json").is_file()

        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == -signal.SIGKILL, (
            (stdout or "") + (stderr or "")
        )

        run(install, environment=environment, cwd=tmp_path)
        recovered = _record(directory)
        assert recovered.get("status") == "ready"
        assert recovered.get("operation") is None
        assert _active_slot(recovered) == candidate_slot
        active = recovered.get("active_runtime")
        assert isinstance(active, dict)
        source = active.get("source")
        assert isinstance(source, dict)
        assert source.get("digest") == project.source.digest
        assert source.get("lock_digest") == project.source.lock_digest
        assert source.get("commit") == project.source.commit
        assert source.get("project_path") == project.source.project_path
        assert hashlib.sha256((slot / "project.zip").read_bytes()).hexdigest() == (
            project.source.digest
        )
        runtime_slots = {
            path.name for path in (directory / "runtimes").iterdir()
            if path.is_dir()
        }
        assert runtime_slots == {candidate_slot}
    finally:
        _stop_process_group(process, release)


def test_failed_replacement_keeps_old_runtime_and_setup_recovers_without_stable_manager(
    tmp_path: Path,
    native_product: NativeProduct,
) -> None:
    _project_root, _uv, setup, _checksums, spec, _project = native_product
    command_name = spec.metadata.command_name
    assert command_name is not None
    environment, command_directory = _host_environment(tmp_path / "host")
    install = _install_command(setup, command_directory)
    run(install, environment=environment, cwd=tmp_path)

    directory = installation_directory(
        spec.metadata.identity.app_id,
        environment=environment,
    )
    initial = _record(directory)
    old_slot = _active_slot(initial)
    failed = run(
        install,
        environment={**environment, "FIXTURE_FAIL_INITIALIZE": "1"},
        cwd=tmp_path,
        check=False,
    )
    assert failed.returncode != 0, failed.stdout + failed.stderr
    incomplete = _record(directory)
    operation = incomplete.get("operation")
    assert isinstance(operation, dict)
    assert incomplete.get("status") == "incomplete"
    assert operation.get("kind") == "replace"
    assert operation.get("phase") == "failed"
    assert _active_slot(incomplete) == old_slot
    candidate_slot = _pending_slot(incomplete)
    assert candidate_slot != old_slot

    command = command_directory / command_name
    result = run(
        [str(command), "inspect", "after-failed-replacement"],
        environment=environment,
        cwd=tmp_path,
    )
    result_payload = json.loads(result.stdout)
    assert result_payload["marker"] == "committed-source"
    assert Path(result_payload["prefix"]).resolve() == (
        directory / "runtimes" / old_slot / ".venv"
    ).resolve()

    stable_manager = directory / command_name
    assert stable_manager.is_file()
    stable_manager.unlink()
    doctor = run(
        [str(setup), "app", "doctor", "--json"],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["details"]["application"]["host"]["application"] == (
        "fixture"
    )
    assert not stable_manager.exists()

    repair = run(
        [str(setup), "app", "repair", "--yes"],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert repair.returncode == 0, repair.stdout + repair.stderr
    repaired = _record(directory)
    assert repaired.get("status") == "ready"
    assert repaired.get("operation") is None
    assert _active_slot(repaired) == candidate_slot
    assert stable_manager.is_file()

    stable_manager.unlink()
    assert not stable_manager.exists()
    uninstall = run(
        [str(setup), "app", "uninstall", "--yes"],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert setup.is_file()
    assert not stable_manager.exists()
    assert not (directory / "runtimes" / candidate_slot).exists()
    assert not (command_directory / command_name).exists()
