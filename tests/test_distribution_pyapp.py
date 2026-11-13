"""Opt-in native end-to-end installation, ownership, and editable acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile
from typing import Any

import pytest

from apprc.distribution import build_native_distribution
from apprc.distribution.models import DistributionSpec, decode_native_binding
from apprc.distribution.project import PreparedProject
from apprc.user_files.installation.discovery import installation_directory
from tests.support_pyapp import authoring_environment, isolated_environment, run

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("APPRC_TEST_PYAPP") != "1",
        reason="Set APPRC_TEST_PYAPP=1 to enable native feasibility tests.",
    ),
    pytest.mark.skipif(
        sys.platform != "linux",
        reason="The native managed lifecycle fixture uses Linux setup artifacts.",
    ),
]

NativeProduct = tuple[Path, Path, Path, Path, DistributionSpec, PreparedProject]


@pytest.fixture(autouse=True)
def _require_serial_native_product(request: pytest.FixtureRequest) -> None:
    if hasattr(request.config, "workerinput"):
        pytest.fail("Run native PyApp tests serially with pytest -n 0.")


def _record(directory: Path) -> dict[str, Any]:
    result = json.loads((directory / "installation.json").read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _active_slot(record: dict[str, Any]) -> str:
    active = record.get("active_runtime")
    assert isinstance(active, dict)
    slot = active.get("slot_id")
    assert isinstance(slot, str)
    return slot


def _pending_slot(record: dict[str, Any]) -> str:
    operation = record.get("operation")
    assert isinstance(operation, dict)
    intended = operation.get("intended")
    assert isinstance(intended, dict)
    runtime = intended.get("runtime")
    assert isinstance(runtime, dict)
    slot = runtime.get("slot_id")
    assert isinstance(slot, str)
    return slot


def _host(root: Path) -> tuple[dict[str, str], Path]:
    environment = isolated_environment(root)
    command_directory = Path(environment["HOME"]).parent / "commands"
    command_directory.mkdir(exist_ok=True)
    environment["PATH"] = str(command_directory)
    return environment, command_directory


def _install(setup: Path, command_directory: Path) -> list[str]:
    return [
        str(setup), "app", "install", "--yes", "--skip-setup",
        "--command-directory", str(command_directory),
    ]


def _inspect(command: Path, environment: dict[str, str], cwd: Path) -> dict[str, Any]:
    result = run([str(command), "inspect"], environment=environment, cwd=cwd)
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _package_metadata(
    project: Path, environment: dict[str, str]
) -> dict[str, str | None]:
    code = (
        "import importlib.metadata as metadata\n"
        "import json\n"
        "from importlib.metadata import PackageNotFoundError\n"
        "names = ('fixture-feature-dependency', 'fixture-dev-dependency')\n"
        "result = {}\n"
        "for name in names:\n"
        "    try:\n"
        "        result[name] = metadata.version(name)\n"
        "    except PackageNotFoundError:\n"
        "        result[name] = None\n"
        "print(json.dumps(result, sort_keys=True))\n"
    )
    output = run(
        [str(project / ".venv" / "bin" / "python"), "-I", "-c", code],
        environment=environment,
        cwd=project,
    ).stdout
    payload = json.loads(output)
    assert isinstance(payload, dict)
    return payload


def test_native_authoring_fails_closed_on_stale_source_and_binding(
    tmp_path: Path, native_product: NativeProduct
) -> None:
    project_root, uv, _setup, checksums, spec, project = native_product
    original_checksums = checksums.read_bytes()
    original_lock = (project_root / "uv.lock").read_bytes()
    with pytest.raises(ValueError):
        build_native_distribution(
            spec,
            replace(project, source=replace(project.source, lock_digest="0" * 64)),
            uv=uv,
            workspace=tmp_path / "stale-lock",
            environment=authoring_environment(),
            extras=("native-feature",),
        )
    assert checksums.read_bytes() == original_checksums
    assert (project_root / "uv.lock").read_bytes() == original_lock
    with pytest.raises(ValueError):
        build_native_distribution(
            replace(spec, metadata=replace(spec.metadata, version="9.0.0")),
            project,
            uv=uv,
            workspace=tmp_path / "stale-binding",
            environment=authoring_environment(),
            extras=("native-feature",),
        )
    assert checksums.read_bytes() == original_checksums


def test_native_managed_update_bridge_doctor_and_editable_lifecycle(
    tmp_path: Path, native_product: NativeProduct, request: pytest.FixtureRequest
) -> None:
    project_root, uv, setup_a, checksums_a, spec, project = native_product
    command_name = spec.metadata.command_name
    assert command_name is not None
    setup_b = (
        project_root.parent / "fixture-b" / "dist"
        / f"{spec.metadata.identity.app_id}-setup-linux-x86_64"
    )
    assert setup_b.is_file()
    checksums_b = project_root.parent / "fixture-b" / "dist" / "SHA256SUMS"
    expected_outputs = {
        f"{spec.metadata.identity.app_id}-setup-linux-x86_64",
        f"{spec.metadata.identity.app_id}-setup-windows-x86_64.exe",
    }
    for checksums in (checksums_a, checksums_b):
        manifest = {
            name: digest
            for digest, name in (
                line.split("  ", 1)
                for line in checksums.read_text(encoding="ascii").splitlines()
            )
        }
        assert set(manifest) == expected_outputs
        for name, expected_digest in manifest.items():
            with (checksums.parent / name).open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == expected_digest
    with ZipFile(setup_a) as native_archive:
        binding = decode_native_binding(native_archive.read("binding.json"))
        assert binding.identity == spec.metadata.identity
        assert binding.source == project.source
        assert binding.selection.extras == ("native-feature",)

    environment, command_directory = _host(tmp_path / "host")
    installer = _install(setup_a, command_directory)
    run(installer, environment=environment, cwd=tmp_path)
    directory = installation_directory(
        spec.metadata.identity.app_id, environment=environment
    )
    first = _record(directory)
    slot_a = _active_slot(first)
    runtime_a = directory / "runtimes" / slot_a
    assert hashlib.sha256((runtime_a / "project.zip").read_bytes()).hexdigest() == (
        project.source.digest
    )
    assert (runtime_a / "project.zip").is_file()
    assert (runtime_a / "source" / "uv.lock").read_bytes() == (
        project_root / "uv.lock"
    ).read_bytes()
    initialize_event = json.loads(
        (Path(_record(directory)["placement"]["config_dir"]) / "native-hook.json")
        .read_text(encoding="utf-8")
    )
    assert initialize_event["operation_id"]
    assert initialize_event["generation_id"] == first["generation_id"]
    assert initialize_event["directory"] == str(directory)
    assert checksums_a.read_text(encoding="utf-8")
    placement = first.get("placement")
    assert isinstance(placement, dict)
    config_directory = Path(placement["config_dir"])
    resource_sentinel = config_directory / "user-sentinel.txt"
    resource_sentinel.write_text("retain me", encoding="utf-8")

    manager = directory / command_name
    outside = tmp_path / "outside-checkout"
    outside.mkdir()
    conflicting = {
        **environment,
        "VIRTUAL_ENV": str(tmp_path / "unrelated-venv"),
        "PYTHONPATH": str(tmp_path / "unrelated-pythonpath"),
        "FIXTURE_SENTINEL": "captured-environment",
    }
    inspected = _inspect(manager, conflicting, outside)
    active_a = first["active_runtime"]
    assert inspected["marker"] == "committed-source"
    assert inspected["distribution"] == spec.metadata.identity.distribution
    assert inspected["version"] == active_a["version"] == "1.0.0"
    assert inspected["python_version"] == active_a["python_version"]
    assert Path(inspected["interpreter"]) == (
        runtime_a / ".venv" / "bin" / "python"
    )
    assert Path(inspected["prefix"]).resolve() == (runtime_a / ".venv").resolve()
    assert inspected["commands"] == [command_name]
    assert active_a["selection"]["extras"] == ["native-feature"]
    assert inspected["capabilities"] == {
        "config": True, "appdata": True, "cache": False, "state": False
    }
    assert inspected["paths"] == {
        "config": placement["config_dir"],
        "appdata": placement["appdata_dir"],
        "cache": None,
        "state": None,
    }
    assert Path(inspected["cwd"]) == outside
    assert inspected["environment"] == "captured-environment"
    assert inspected["feature_version"] == "1.0.0"
    assert inspected["dev_version"] is None
    assert inspected["argv"] == ["inspect"]
    failed_command = run(
        [str(manager), "inspect", "--fail"],
        environment=conflicting,
        cwd=outside,
        check=False,
    )
    assert failed_command.returncode == 23, failed_command.stdout + failed_command.stderr

    healthy_doctor = run(
        [str(setup_a), "app", "doctor", "--json"],
        environment=environment,
        cwd=tmp_path,
    )
    doctor_json = json.loads(healthy_doctor.stdout)
    assert "details" not in doctor_json
    verbose_doctor = run(
        [str(setup_a), "app", "doctor", "--json", "--verbose"],
        environment=environment,
        cwd=tmp_path,
    )
    assert json.loads(verbose_doctor.stdout)["details"]["host"]["application"] == "fixture"
    failed_doctor = run(
        [str(setup_a), "app", "doctor", "--json"],
        environment={**environment, "FIXTURE_DOCTOR_FAILURE": "1"},
        cwd=tmp_path,
        check=False,
    )
    assert failed_doctor.returncode == 1
    assert "controlled application diagnostic failure" in failed_doctor.stdout
    assert json.loads(failed_doctor.stdout)

    before_tampering = (directory / "installation.json").read_bytes()
    tampered_setup = tmp_path / "tampered-setup"
    shutil.copy2(setup_a, tampered_setup)
    with tampered_setup.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        original_byte = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes((original_byte[0] ^ 1,)))
    rejected = run(
        _install(tampered_setup, command_directory),
        environment=environment,
        cwd=outside,
        check=False,
    )
    assert rejected.returncode != 0
    assert (directory / "installation.json").read_bytes() == before_tampering
    assert resource_sentinel.read_text(encoding="utf-8") == "retain me"

    # > A missing managed venv is recovered from the retained authenticated archive.
    shutil.rmtree(runtime_a / ".venv")
    unavailable = run(
        [str(setup_a), "app", "doctor", "--json"],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert unavailable.returncode != 0
    unavailable_report = json.loads(unavailable.stdout)
    assert unavailable_report["status"] != "ok"
    assert "checks" in unavailable_report
    repair = run(
        [str(setup_a), "app", "repair", "--yes"],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert repair.returncode == 0, repair.stdout + repair.stderr
    assert _inspect(manager, conflicting, outside)["version"] == "1.0.0"
    repaired = _record(directory)
    slot_a = _active_slot(repaired)
    runtime_a = directory / "runtimes" / slot_a

    marker = tmp_path / "active-child-ready"
    child = subprocess.Popen(
        [str(manager), "hold", str(marker)],
        env=conflicting,
        cwd=outside,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert child.stdout is not None and child.stdin is not None
        assert child.stdout.readline().strip() == "ready"
        child_identity = json.loads(marker.read_text(encoding="utf-8"))
        forwarding_pid = child_identity["forwarder"]
        assert isinstance(forwarding_pid, int)
        assert forwarding_pid not in {os.getpid(), child_identity["process"]}
        before_b_lock = (project_root.parent / "fixture-b" / "uv.lock").read_bytes()
        failed_update = run(
            _install(setup_b, command_directory),
            environment={**environment, "FIXTURE_FAIL_INITIALIZE": "1"},
            cwd=tmp_path,
            check=False,
        )
        assert failed_update.returncode != 0
        pending = _record(directory)
        assert pending.get("status") == "incomplete"
        assert pending.get("active_runtime") is not None
        assert _active_slot(pending) == slot_a
        candidate_slot = _pending_slot(pending)
        assert candidate_slot != slot_a
        candidate = directory / "runtimes" / candidate_slot
        assert (candidate / "project.zip").is_file()
        assert (candidate / ".venv").is_dir()
        assert pending["operation"]["kind"] == "replace"
        assert pending["operation"]["phase"] == "failed"
        assert resource_sentinel.read_text(encoding="utf-8") == "retain me"
        assert _inspect(manager, conflicting, outside)["version"] == "1.0.0"
        # > The app child must protect its slot after its forwarding parent dies.
        os.kill(forwarding_pid, signal.SIGKILL)
        assert child.wait(timeout=30) != 0

        run(_install(setup_b, command_directory), environment=environment, cwd=tmp_path)
        updated = _record(directory)
        slot_b = _active_slot(updated)
        assert slot_b != slot_a
        assert slot_a in updated.get("retiring_runtime_ids", [])
        assert (project_root.parent / "fixture-b" / "uv.lock").read_bytes() == before_b_lock
        after_b = _inspect(manager, conflicting, outside)
        active_b = updated["active_runtime"]
        assert after_b["distribution"] == spec.metadata.identity.distribution
        assert after_b["version"] == active_b["version"] == "2.0.0"
        assert after_b["python_version"] == active_b["python_version"]
        assert Path(after_b["interpreter"]) == (
            directory / "runtimes" / slot_b / ".venv" / "bin" / "python"
        )
        assert Path(after_b["prefix"]).resolve() == (
            directory / "runtimes" / slot_b / ".venv"
        ).resolve()
        assert after_b["commands"] == [command_name]
        assert active_b["selection"]["extras"] == ["native-feature"]
        assert after_b["capabilities"] == {
            "config": True, "appdata": True, "cache": False, "state": False
        }
        assert after_b["paths"]["config"] == str(config_directory)
        assert after_b["feature_version"] == "1.0.0"
        assert after_b["dev_version"] is None
        assert (directory / "runtimes" / slot_a).is_dir()
        child.stdin.write("continue\n")
        child.stdin.flush()
        running_old = json.loads(child.stdout.readline())
        assert running_old["version"] == "1.0.0"
        assert Path(running_old["prefix"]).resolve() == (
            runtime_a / ".venv"
        ).resolve()
        assert resource_sentinel.read_text(encoding="utf-8") == "retain me"
    finally:
        if child.stdin is not None:
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass
            child.stdin = None
        try:
            child.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate(timeout=30)
        if child.stdout is not None:
            child.stdout.close()
        if child.stderr is not None:
            child.stderr.close()
    run(_install(setup_b, command_directory), environment=environment, cwd=tmp_path)
    after_child_exit = _record(directory)
    assert slot_a not in after_child_exit.get("retiring_runtime_ids", [])
    assert not (directory / "runtimes" / slot_a).exists()

    # * Exact provider inventory and explicit retained-data consent let purge
    # * remove only the provider's file while preserving unrelated user files.
    provider_file = config_directory / "provider-owned.json"
    unrelated_file = config_directory / "unrelated-user.json"
    provider_file.write_text('{"owned":true}', encoding="utf-8")
    unrelated_file.write_text("keep", encoding="utf-8")
    uninstall = [
        str(manager), "app", "uninstall", "--complete", "--category", "config",
        "--yes", "--forget-retained",
    ]
    no_consent = run(
        [
            str(manager), "app", "uninstall", "--complete", "--category", "config",
            "--forget-retained",
        ],
        environment=environment,
        cwd=tmp_path,
        check=False,
    )
    assert no_consent.returncode != 0
    assert provider_file.is_file() and unrelated_file.is_file()
    preflight = run(
        uninstall,
        environment={**environment, "FIXTURE_FAIL_INVENTORY": "1"},
        cwd=tmp_path,
        check=False,
    )
    assert preflight.returncode != 0
    assert provider_file.is_file() and unrelated_file.is_file()
    cleanup_failure = run(
        uninstall,
        environment={**environment, "FIXTURE_FAIL_CLEANUP": "1"},
        cwd=tmp_path,
        check=False,
    )
    assert cleanup_failure.returncode != 0
    assert provider_file.is_file() and unrelated_file.is_file()
    failed_record = _record(directory)
    assert failed_record.get("status") == "incomplete"
    hook_event = json.loads(
        (config_directory / "cleanup-hook.json").read_text(encoding="utf-8")
    )
    assert hook_event["operation_id"] == failed_record["operation"]["operation_id"]
    assert hook_event["generation_id"] == failed_record["generation_id"]
    assert hook_event["directory"] == str(directory)
    completed = run(uninstall, environment=environment, cwd=tmp_path, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not provider_file.exists()
    assert unrelated_file.read_text(encoding="utf-8") == "keep"
    assert resource_sentinel.read_text(encoding="utf-8") == "retain me"

    # > Program-only uninstall works even when the application venv is absent.
    new_host, new_commands = _host(tmp_path / "program-only")
    run(_install(setup_a, new_commands), environment=new_host, cwd=tmp_path)
    new_directory = installation_directory(
        spec.metadata.identity.app_id, environment=new_host
    )
    new_record = _record(new_directory)
    active = new_directory / "runtimes" / _active_slot(new_record)
    shutil.rmtree(active / ".venv")
    unknown_command = new_commands / "unrelated-command"
    unknown_command.write_text("preserve unrelated command", encoding="utf-8")
    unknown_installation_file = new_directory / "unrelated-file"
    unknown_installation_file.write_text("preserve unrelated file", encoding="utf-8")
    program_only = run(
        [str(setup_a), "app", "uninstall", "--yes"],
        environment=new_host,
        cwd=tmp_path,
        check=False,
    )
    assert program_only.returncode == 0, program_only.stdout + program_only.stderr
    assert not (new_commands / command_name).exists()
    assert (new_directory / "installation.json").is_file()
    assert unknown_command.read_text(encoding="utf-8") == "preserve unrelated command"
    assert unknown_installation_file.read_text(encoding="utf-8") == "preserve unrelated file"

    # * Editable registration uses the developer's existing environment.
    # * Preserve its package baseline and restore the source after the test.
    editable_host, editable_commands = _host(tmp_path / "editable-host")
    editable_host["PATH"] += os.pathsep + str(uv.parent)
    run(
        [str(uv), "sync", "--locked", "--no-default-groups"],
        environment=editable_host,
        cwd=project_root,
    )
    baseline_packages = _package_metadata(project_root, editable_host)
    environment_root = project_root / ".venv"
    sentinel = environment_root / "user-sentinel.txt"
    sentinel.write_text("keep this environment", encoding="utf-8")
    original_source = (project_root / "fixture_app.py").read_bytes()
    request.addfinalizer(
        lambda: (project_root / "fixture_app.py").write_bytes(original_source)
    )
    editable_register = run(
        [
            str(uv), "run", "--locked", "--no-sync", "fixture-app", "app", "install", "-e",
            "--yes", "--command-directory", str(editable_commands),
        ],
        environment=editable_host,
        cwd=project_root,
        check=False,
    )
    assert editable_register.returncode == 0, (
        editable_register.stdout + editable_register.stderr
    )
    editable_directory = installation_directory(
        spec.metadata.identity.app_id, environment=editable_host
    )
    editable_record = _record(editable_directory)
    editable_runtime = editable_record.get("active_runtime")
    assert isinstance(editable_runtime, dict)
    assert editable_runtime.get("project") == str(project_root)
    assert editable_runtime.get("environment") == str(environment_root)
    assert environment_root.is_dir() and sentinel.read_text(encoding="utf-8") == (
        "keep this environment"
    )
    assert _package_metadata(project_root, editable_host) == baseline_packages
    editable_command = editable_commands / command_name
    editable_outside = _inspect(editable_command, editable_host, outside)
    assert Path(editable_outside["prefix"]).resolve() == environment_root.resolve()
    assert Path(editable_outside["cwd"]) == outside
    changed_source = original_source.replace(
        b"'marker': 'committed-source'", b"'marker': 'editable-change'"
    )
    assert changed_source != original_source
    (project_root / "fixture_app.py").write_bytes(changed_source)
    assert _inspect(editable_command, editable_host, outside)["marker"] == (
        "editable-change"
    )
    refresh = run(
        [
            str(uv), "run", "--locked", "--no-sync", "fixture-app", "app", "install", "-e",
            "--yes", "--command-directory", str(editable_commands),
        ],
        environment=editable_host,
        cwd=project_root,
        check=False,
    )
    assert refresh.returncode == 0, refresh.stdout + refresh.stderr
    refreshed_record = _record(editable_directory)
    assert refreshed_record["generation_id"] == editable_record["generation_id"]
    assert refreshed_record["active_runtime"] == editable_record["active_runtime"]
    assert _package_metadata(project_root, editable_host) == baseline_packages
    unrelated_editable_command = editable_commands / "unrelated-command"
    unrelated_editable_command.write_text("keep unrelated command", encoding="utf-8")
    assert sentinel.read_text(encoding="utf-8") == "keep this environment"

    unregistered = run(
        [str(editable_command), "app", "uninstall", "--yes"],
        environment=editable_host,
        cwd=outside,
        check=False,
    )
    assert unregistered.returncode == 0, unregistered.stdout + unregistered.stderr
    assert not editable_command.exists() and not editable_command.is_symlink()
    assert (project_root / "fixture_app.py").read_bytes() == changed_source
    assert sentinel.read_text(encoding="utf-8") == "keep this environment"
    assert _package_metadata(project_root, editable_host) == baseline_packages
    assert unrelated_editable_command.read_text(encoding="utf-8") == "keep unrelated command"
    run(
        [
            str(environment_root / "bin" / command_name), "app", "install", "-e",
            "--yes", "--command-directory", str(editable_commands),
        ],
        environment=editable_host,
        cwd=project_root,
    )

    editable_config = Path(_record(editable_directory)["placement"]["config_dir"])
    editable_provider = editable_config / "provider-owned.json"
    editable_unrelated = editable_config / "unrelated-user.json"
    editable_provider.write_text('{"owned":true}', encoding="utf-8")
    editable_unrelated.write_text("preserve", encoding="utf-8")
    editable_uninstall = run(
        [
            str(uv), "run", "--locked", "--no-sync", "fixture-app", "app", "uninstall",
            "--complete", "--category", "config", "--yes", "--forget-retained",
        ],
        environment=editable_host,
        cwd=project_root,
        check=False,
    )
    assert editable_uninstall.returncode == 0, (
        editable_uninstall.stdout + editable_uninstall.stderr
    )
    assert not editable_provider.exists()
    assert editable_unrelated.read_text(encoding="utf-8") == "preserve"
    assert (project_root / "fixture_app.py").read_bytes() == changed_source
    assert environment_root.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep this environment"
    assert _package_metadata(project_root, editable_host) == baseline_packages


def test_native_appdata_purge_executes_provider_and_preserves_unknown_data(
    tmp_path: Path, native_product: NativeProduct,
) -> None:
    _project_root, _uv, setup, _checksums, spec, _project = native_product
    environment, commands = _host(tmp_path / "host")
    run(_install(setup, commands), environment=environment, cwd=tmp_path)
    directory = installation_directory(
        spec.metadata.identity.app_id, environment=environment
    )
    record = _record(directory)
    appdata = Path(record["placement"]["appdata_dir"])
    config = Path(record["placement"]["config_dir"])
    provider = appdata / "provider-owned.json"
    unrelated = appdata / "unrelated-user.json"
    provider.write_text('{"owned":true}', encoding="utf-8")
    unrelated.write_text("keep unrelated data", encoding="utf-8")
    removal = run(
        [
            str(setup), "app", "uninstall", "--complete", "--category", "appdata",
            "--yes", "--forget-retained",
        ],
        environment=environment, cwd=tmp_path, check=False,
    )
    assert removal.returncode == 0, removal.stdout + removal.stderr
    event = json.loads((config / "cleanup-hook.json").read_text(encoding="utf-8"))
    assert event["generation_id"] == record["generation_id"]
    assert event["directory"] == str(directory)
    assert not provider.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep unrelated data"
    assert not (commands / str(spec.metadata.command_name)).exists()


def test_failed_editable_switch_restores_real_global_command_and_authority(
    tmp_path: Path, native_product: NativeProduct,
) -> None:
    from apprc.definition.installation import EditableCheckout
    from apprc.distribution.runtime import _manager
    from apprc.services.installation import InstallationManager

    project_a, uv, setup, _checksums, _spec, _project = native_product
    project_b = project_a.parent / "fixture-b"
    environment, commands = _host(tmp_path / "host")
    environment["PATH"] += os.pathsep + str(uv.parent)
    for project in (project_a, project_b):
        run(
            [str(uv), "sync", "--locked", "--no-default-groups"],
            environment=environment, cwd=project,
        )
    with ZipFile(setup) as archive:
        binding = decode_native_binding(archive.read("binding.json"))
    manager = InstallationManager(
        _manager._application(binding).schema, environment=environment
    )
    runtime_a = EditableCheckout(project_a, project_a / ".venv", binding.hooks)
    runtime_b = EditableCheckout(project_b, project_b / ".venv", binding.hooks)
    run(
        [
            str(runtime_a.environment / "bin" / binding.command_name),
            "app", "install", "-e", "--yes", "--skip-setup",
            "--command-directory", str(commands),
        ],
        environment=environment, cwd=project_a,
    )
    initial = manager.inspect().record
    assert initial is not None
    command = commands / binding.command_name
    old_target = os.readlink(command)

    activation = tmp_path / "activation-attempted"
    driver = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from apprc.definition.installation import EditableCheckout, InstallationError\n"
        "from apprc.distribution.runtime.installation import register_editable_application\n"
        "from fixture_config import APP_RC\n"
        "manager = APP_RC.installation(environment=dict(os.environ))\n"
        "record = manager.inspect().record\n"
        "assert record is not None and record.active_runtime is not None\n"
        "project, uv, command_directory, marker = map(Path, sys.argv[1:])\n"
        "runtime = EditableCheckout(project, Path(sys.prefix), record.active_runtime.hooks)\n"
        "def fail_activation(**kwargs):\n"
        " command = command_directory / record.command_name\n"
        " assert command.resolve() == Path(sys.prefix) / 'bin' / record.command_name\n"
        " marker.write_text('activation attempted', encoding='utf-8')\n"
        " raise InstallationError('controlled editable activation failure')\n"
        "manager.commit_install = fail_activation\n"
        "try:\n"
        " register_editable_application(manager, record.identity, runtime, record.placement, "
        "command_name=record.command_name, uv=uv, command_directory=command_directory, assume_yes=True)\n"
        "except InstallationError:\n"
        " raise SystemExit(23)\n"
        "raise SystemExit('activation failure was not injected')\n"
    )
    rejected = run(
        [
            str(runtime_b.environment / "bin" / "python"), "-I", "-c", driver,
            str(project_b), str(uv), str(commands), str(activation),
        ],
        environment=environment, cwd=project_b, check=False,
    )
    assert rejected.returncode == 23, rejected.stdout + rejected.stderr
    assert activation.read_text(encoding="utf-8") == "activation attempted"
    failed = manager.inspect().record
    assert failed is not None
    assert failed.active_runtime == initial.active_runtime == runtime_a
    assert failed.operation is not None and failed.operation.intended is not None
    assert failed.operation.intended.runtime == runtime_b
    assert os.readlink(command) == old_target
    observed = _inspect(command, environment, tmp_path)
    assert observed["version"] == "1.0.0"
    assert Path(observed["prefix"]).resolve() == runtime_a.environment.resolve()
    assert runtime_a.environment.is_dir() and runtime_b.environment.is_dir()


def test_real_workspace_member_registration_uses_composed_hooks(
    tmp_path: Path, native_product: NativeProduct,
) -> None:
    source, uv, _setup, _checksums, spec, _project = native_product
    workspace = tmp_path / "virtual-workspace"
    member = workspace / "applications" / "selected-member"
    member.parent.mkdir(parents=True)
    shutil.copytree(
        source, member,
        ignore=shutil.ignore_patterns(".git", ".venv", ".cache", "dist"),
    )
    (workspace / "pyproject.toml").write_text(
        "[tool.uv.workspace]\nmembers = ['applications/*']\n",
        encoding="utf-8",
    )
    metadata = member / "pyproject.toml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "[tool.apprc.distribution.hooks]\n"
            "initialize = 'fixture_app:initialize'\n"
            "inventory = 'fixture_app:inventory'\n"
            "cleanup = 'fixture_app:cleanup'\n",
            "",
        ),
        encoding="utf-8",
    )
    (member / "uv.lock").unlink()
    environment, commands = _host(tmp_path / "host")
    environment["PATH"] += os.pathsep + str(uv.parent)
    run(
        [str(uv), "lock", "--project", str(member)],
        environment=environment, cwd=workspace,
    )
    run(
        [
            str(uv), "sync", "--locked", "--no-default-groups",
            "--project", str(member), "--python", sys.executable,
        ],
        environment=environment, cwd=workspace,
    )
    environment_root = workspace / ".venv"
    original_environment = environment_root.stat().st_ino
    sentinel = environment_root / "developer-sentinel"
    sentinel.write_bytes(b"developer-owned environment")
    original_lock = (workspace / "uv.lock").read_bytes()
    command_name = spec.metadata.command_name
    assert command_name is not None
    member_command = environment_root / "bin" / command_name
    registration = run(
        [
            str(member_command), "app", "install", "-e", "--yes",
            "--skip-setup", "--command-directory", str(commands),
        ],
        environment=environment, cwd=workspace, check=False,
    )
    assert registration.returncode == 0, registration.stdout + registration.stderr
    directory = installation_directory(
        spec.metadata.identity.app_id, environment=environment
    )
    record = _record(directory)
    assert record["active_runtime"]["project"] == str(member)
    assert record["active_runtime"]["environment"] == str(environment_root)
    run(
        [
            str(member_command), "app", "install", "-e", "--yes",
            "--skip-setup", "--command-directory", str(commands),
        ],
        environment=environment, cwd=member,
    )
    refreshed = _record(directory)
    assert refreshed["active_runtime"] == record["active_runtime"]
    assert refreshed["generation_id"] == record["generation_id"]
    global_command = commands / command_name
    observed = _inspect(global_command, environment, tmp_path)
    assert Path(observed["prefix"]).resolve() == environment_root.resolve()
    assert environment_root.stat().st_ino == original_environment
    assert (workspace / "uv.lock").read_bytes() == original_lock
    config = Path(record["placement"]["config_dir"])
    provider = config / "provider-owned.json"
    unrelated = config / "unrelated-user.json"
    provider.write_text('{"owned":true}', encoding="utf-8")
    unrelated.write_text("preserve unknown config", encoding="utf-8")
    removal = run(
        [
            str(global_command), "app", "uninstall", "--complete",
            "--category", "config", "--forget-retained", "--yes",
        ],
        environment=environment, cwd=tmp_path, check=False,
    )
    assert removal.returncode == 0, removal.stdout + removal.stderr
    assert not provider.exists()
    event = json.loads((config / "cleanup-hook.json").read_text(encoding="utf-8"))
    assert event["generation_id"] == record["generation_id"]
    assert unrelated.read_text(encoding="utf-8") == "preserve unknown config"
    assert sentinel.read_bytes() == b"developer-owned environment"
    assert member_command.is_file() and (member / "fixture_app.py").is_file()
    assert not global_command.exists() and not global_command.is_symlink()