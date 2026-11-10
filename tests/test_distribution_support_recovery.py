"""Support publication remains authorized only by saved digest evidence."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationSource,
    InstalledSnapshot,
    InstallPlan,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.distribution.models import (
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import render_saved_support
from apprc.distribution.runtime import installation, installed_probe
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    prepare_source,
)
from apprc.distribution.runtime.backend import external_base_python
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import plan_install, plan_repair


def _scenario(
    tmp_path: Path,
    *,
    source: InstallationSource | None = None,
    native_backend: bool = False,
) -> tuple[Path, InstallPlan, InstalledSnapshot, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    source = source or InstallationSource("editable", str(project))
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture-command",)
    )
    placement = InstallationPlacement(Layout.native())
    backend = UvToolTarget(
        Path(shutil.which("uv") or "uv"),
        tmp_path / "tools",
        tmp_path / "commands",
    )
    directory = tmp_path / "installation"
    plan = plan_install(
        identity,
        source,
        placement,
        backend,
        inspection=inspect_installation(directory, app_id=identity.app_id),
    )
    create_private_directory_if_missing(backend.bin_dir)
    command = backend.bin_dir / (
        "fixture-command.exe" if os.name == "nt" else "fixture-command"
    )
    if not native_backend:
        command.write_text("#!/bin/sh\n")
        command.chmod(0o700)
    snapshot = InstalledSnapshot(
        identity,
        "1.0",
        source,
        placement,
        backend,
        tmp_path / "tools" / "fixture",
        tmp_path / "tools" / "fixture" / "python",
        (command,),
    )
    environment = {"PATH": os.environ.get("PATH", "")}
    return directory, plan, snapshot, environment


def _run(
    plan: InstallPlan,
    environment: dict[str, str],
    support: dict[PurePosixPath, bytes],
    *,
    prepared_source: PreparedSource | None = None,
    python_requirement: str = ">=3.12",
) -> InstallationInspection:
    prepared = prepared_source or PreparedSource(
        plan.target.source.requirement, None, plan.target.source
    )
    return installation.install_application(
        plan,
        environment=environment,
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files=support,
        python_requirement=python_requirement,
        prepared_source=prepared,
    )


def _stub_backend(
    monkeypatch: pytest.MonkeyPatch, snapshot: InstalledSnapshot
) -> None:
    monkeypatch.setattr(
        installation,
        "inspect_uv_tools",
        lambda target, *, environment: frozenset(),
    )
    monkeypatch.setattr(
        installation,
        "install_uv_tool",
        lambda target, source, *, environment, python_requirement, constraints: (
            None
        ),
    )
    monkeypatch.setattr(
        installation,
        "probe_installed_tool",
        lambda target, identity, source, placement, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        installation,
        "external_base_python",
        lambda prefix, **kwargs: Path(sys.executable),
    )
    monkeypatch.setattr(
        installation,
        "_register_windows",
        lambda *args, **kwargs: None,
    )


@pytest.mark.parametrize("edit_after_interruption", (False, True))
def test_repair_handles_interrupted_address_bound_support_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit_after_interruption: bool,
) -> None:
    directory, plan, snapshot, environment = _scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    monkeypatch.setattr(
        installation, "external_base_python", external_base_python
    )
    support = {
        PurePosixPath("management.json"): json.dumps(
            {
                "app_id": "fixture",
                "command": "fixture-command",
                "base_python": None,
            }
        ).encode(),
    }
    original_write = installation.write_bytes_atomic

    def publish_then_interrupt(path: Path, content: bytes, *, private: bool):
        original_write(path, content, private=private)
        if path.name == "management.json":
            raise RuntimeError(
                "interrupted after address-bound support publication"
            )

    monkeypatch.setattr(
        installation, "write_bytes_atomic", publish_then_interrupt
    )
    with pytest.raises(RuntimeError, match="address-bound support publication"):
        _run(plan, environment, support)

    pending = inspect_installation(directory, app_id="fixture")
    assert pending.record is not None and pending.record.operation is not None
    repair = plan_repair(
        plan.target.identity,
        plan.target.source,
        plan.target.placement,
        plan.target.backend,
        inspection=pending,
    )
    binding = directory / "management.json"
    if edit_after_interruption:
        binding.write_bytes(b"edited management binding")
        with pytest.raises(InstallationError):
            _run(repair, environment, support)
        assert binding.read_bytes() == b"edited management binding"
        return

    monkeypatch.setattr(installation, "write_bytes_atomic", original_write)
    repaired = _run(repair, environment, support)
    assert repaired.status == "ready"
    interpreter = Path(json.loads(binding.read_bytes())["base_python"])
    assert not interpreter.resolve().is_relative_to(snapshot.prefix.resolve())
    probe = subprocess.run(
        [
            str(interpreter),
            "-I",
            "-c",
            "import sys; raise SystemExit(sys.prefix != sys.base_prefix)",
        ],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr


@pytest.mark.parametrize("authorized_bound_input", (True, False))
def test_saved_repair_reuses_only_owned_bound_management_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authorized_bound_input: bool,
) -> None:
    directory, plan, snapshot, environment = _scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    monkeypatch.setattr(
        installation, "external_base_python", external_base_python
    )
    support = {
        PurePosixPath("management.json"): json.dumps(
            {
                "app_id": "fixture",
                "command": "fixture-command",
                "base_python": None,
            }
        ).encode(),
    }
    installed = _run(plan, environment, support)
    assert installed.status == "ready"
    bound_path = directory / "management.json"
    authorized_bytes = bound_path.read_bytes()
    binding = json.loads(authorized_bytes)
    assert Path(binding["base_python"]).is_absolute()

    repair = plan_repair(
        plan.target.identity,
        plan.target.source,
        plan.target.placement,
        plan.target.backend,
        inspection=installed,
    )
    repair_support = dict(support)
    repair_support[PurePosixPath("management.json")] = (
        authorized_bytes
        if authorized_bound_input
        else json.dumps(binding, indent=2).encode()
    )
    if authorized_bound_input:
        repaired = _run(repair, environment, repair_support)
        assert repaired.status == "ready"
        assert bound_path.read_bytes() == authorized_bytes
    else:
        with pytest.raises(InstallationError):
            _run(repair, environment, repair_support)
        assert bound_path.read_bytes() == authorized_bytes


def test_saved_release_repair_recovers_owned_installation_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    source_archive = tmp_path / "fixture-1.0.tar.gz"
    project = (
        "[build-system]\n"
        'requires = ["setuptools>=80"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "[project]\n"
        'name = "fixture"\n'
        'version = "1.0"\n'
        "[project.scripts]\n"
        'fixture-command = "fixture:main"\n'
        "[tool.setuptools]\n"
        'py-modules = ["fixture"]\n'
    ).encode()
    module = b"def main():\n    return None\n"
    with tarfile.open(source_archive, "w:gz") as archive:
        for name, content in (
            ("fixture-1.0/pyproject.toml", project),
            ("fixture-1.0/fixture.py", module),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    digest = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    source = InstallationSource(
        "release-sdist",
        str(source_archive),
        version="1.0",
        digest=digest,
        runtime_requirements=(),
    )
    staging = tmp_path / "private source"
    create_private_directory_if_missing(staging)
    prepared = prepare_source(source, staging)
    directory, plan, _, environment = _scenario(
        tmp_path, source=source, native_backend=True
    )
    private_home = tmp_path / "test home ü %2F"
    create_private_directory_if_missing(private_home)
    environment = dict(os.environ)
    environment["HOME"] = str(private_home)
    environment["USERPROFILE"] = str(private_home)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    for variable, name in (
        ("UV_TOOL_DIR", "tools"),
        ("UV_TOOL_BIN_DIR", "commands"),
        ("UV_CACHE_DIR", "uv cache"),
        ("UV_PYTHON_INSTALL_DIR", "uv python"),
        ("UV_PYTHON_BIN_DIR", "python commands"),
        ("UV_CONFIG_DIR", "uv config"),
        ("TMPDIR", "temporary"),
        ("TMP", "temporary"),
        ("TEMP", "temporary"),
    ):
        root = tmp_path / name
        create_private_directory_if_missing(root)
        environment[variable] = str(root)
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temporary"))
    monkeypatch.setattr(
        installation,
        "external_base_python",
        lambda prefix, **kwargs: Path(sys.executable),
    )
    monkeypatch.setattr(
        installation,
        "_register_windows",
        lambda *args, **kwargs: None,
    )

    package = tmp_path / "payload" / "app_lifecycle"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Saved release fixture."""\n')
    (package / "install.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from apprc.user_files.installation.discovery import inspect_installation\n"
        "\n"
        "def main():\n"
        "    inspection = inspect_installation(\n"
        "        Path(os.environ['INSTALLATION_DIRECTORY']), app_id='fixture'\n"
        "    )\n"
        "    assert inspection.status == 'ready'\n"
        "    record = inspection.record\n"
        "    assert record is not None and record.current is not None\n"
        "    source = record.current.source\n"
        "    assert source.requirement == os.environ['SOURCE_REQUIREMENT']\n"
        "    assert source.digest == os.environ['SOURCE_DIGEST']\n"
        "    outputs = {item.path: item.digest for item in record.current.owned_outputs}\n"
        "    assert outputs['repair-installer.py'] == os.environ['REPAIR_DIGEST']\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    (package / "uninstall.py").write_text("def main():\n    return 0\n")
    payload = PayloadTree(
        package.parent,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    spec = DistributionSpec(
        ProjectMetadata(tmp_path, plan.target.identity, "1.0"),
        source_mode="release",
        repository_url="https://github.com/example/fixture",
        release_version="1.0",
        release_commit="a" * 40,
        release_asset=(
            "https://github.com/example/fixture/releases/download/v1.0/"
            "fixture-1.0.tar.gz"
        ),
        release_digest=digest,
    )
    repair = next(
        artifact
        for artifact in render_saved_support(spec, payload)
        if artifact.destination.name == "repair-installer.py"
    )
    support = {
        PurePosixPath("management.json"): json.dumps(
            {
                "app_id": "fixture",
                "command": "fixture-command",
                "base_python": None,
            }
        ).encode(),
        PurePosixPath("repair-installer.py"): repair.content,
    }
    original_write = installation.write_bytes_atomic

    def interrupt_after_saved_repair(
        path: Path, content: bytes, *, private: bool
    ) -> None:
        original_write(path, content, private=private)
        if path.name == "repair-installer.py":
            raise RuntimeError("interrupted after saved release repair")

    monkeypatch.setattr(
        installation, "write_bytes_atomic", interrupt_after_saved_repair
    )
    with pytest.raises(RuntimeError, match="saved release repair"):
        _run(
            plan,
            environment,
            support,
            prepared_source=prepared,
            python_requirement=sys.executable,
        )

    pending = inspect_installation(directory, app_id="fixture")
    assert pending.record is not None and pending.record.current is not None
    assert pending.record.current.distribution_record_digest is not None
    assert pending.record.current.source == source
    repair_output = next(
        output
        for output in pending.record.current.owned_outputs
        if output.path == "repair-installer.py"
    )
    assert repair_output.digest == hashlib.sha256(repair.content).hexdigest()

    monkeypatch.setattr(installation, "write_bytes_atomic", original_write)
    resume = plan_repair(
        plan.target.identity,
        source,
        plan.target.placement,
        plan.target.backend,
        inspection=pending,
    )
    result = _run(
        resume,
        environment,
        support,
        prepared_source=prepared,
        python_requirement=sys.executable,
    )
    assert result.status == "ready"
    assert result.record is not None and result.record.current is not None
    assert result.record.current.source == source
    assert (directory / "repair-installer.py").read_bytes() == repair.content

    repair_environment = dict(
        environment,
        INSTALLATION_DIRECTORY=str(directory),
        SOURCE_REQUIREMENT=source.requirement,
        SOURCE_DIGEST=source.digest or "",
        REPAIR_DIGEST=hashlib.sha256(repair.content).hexdigest(),
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
    )
    subprocess.run(
        [sys.executable, str(directory / "repair-installer.py")],
        env=repair_environment,
        check=True,
        capture_output=True,
    )

    (directory / "repair-installer.py").write_bytes(b"edited saved repair")
    tampered_inspection = inspect_installation(directory, app_id="fixture")
    tampered_repair = plan_repair(
        plan.target.identity,
        source,
        plan.target.placement,
        plan.target.backend,
        inspection=tampered_inspection,
    )
    with pytest.raises(InstallationError, match="unowned support output"):
        _run(
            tampered_repair,
            environment,
            support,
            prepared_source=prepared,
            python_requirement=sys.executable,
        )


def test_existing_support_matching_desired_bytes_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, plan, snapshot, environment = _scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    destination = directory / "controller.py"
    create_private_directory_if_missing(destination.parent)
    destination.write_bytes(b"desired controller")

    with pytest.raises(InstallationError, match="unowned support output"):
        _run(
            plan,
            environment,
            {PurePosixPath("controller.py"): b"desired controller"},
        )

    assert destination.read_bytes() == b"desired controller"
