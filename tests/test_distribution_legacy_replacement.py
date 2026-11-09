"""Real uv-tool replacement of arbitrary-origin historical installations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import shutil
import sys
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TypedDict
from uuid import UUID

import pytest

from apprc.definition.installation import (
    CleanupInventory,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationSource,
    MigrationInventory,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.distribution import install_support_files
from apprc.distribution.models import (
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.runtime import (
    LegacyReplacementPlan,
    LegacyReceiptInspection,
    PreparedSource,
    execute_legacy_replacement,
    inspect_legacy_receipt,
    is_pending_legacy_replacement,
    plan_legacy_replacement,
    prepare_source,
    resume_legacy_replacement,
)
from apprc.distribution.runtime import legacy_replacement, installed_probe
from apprc.distribution.runtime.backend import (
    external_base_python,
    install_uv_tool,
    select_uv_target,
)
from apprc.distribution.runtime.probe import probe_installed_tool
from apprc.user_files.installation.discovery import inspect_installation
import apprc.user_files.installation.migration as migration


_DISTRIBUTION = "apprc-legacy-replacement-fixture"
_COMMAND = "legacy-replacement-fixture"
_IDENTITY = InstallationIdentity(
    "legacy-replacement-fixture",
    _DISTRIBUTION,
    "legacy_replacement_fixture",
    None,
    (_COMMAND,),
)


_AUTHORED_RECOVERY_ENTRY = b"""import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["APPRC_TEST_IMPORT_ROOT"])
from apprc.distribution.runtime import installed_probe, resume_legacy_replacement
from apprc.user_files.installation.discovery import inspect_installation

directory = Path(os.environ["APPRC_TEST_INSTALLATION"])
inspection = inspect_installation(directory, app_id=os.environ["APPRC_TEST_APP_ID"])
record = inspection.record
if record is None or record.operation is None or inspection.revision is None:
    raise RuntimeError("No pending replacement metadata is available.")
operation = record.operation
resume_legacy_replacement(
    directory,
    operation_id=operation.operation_id,
    expected_revision=inspection.revision,
    quiescent=True,
    environment=dict(os.environ),
    probe_path=Path(installed_probe.__file__).absolute(),
    python_requirement=os.environ["APPRC_TEST_PYTHON_REQUIREMENT"],
)
"""


def _write_recovery_support(
    scenario: _Scenario,
    support_root: Path,
) -> None:
    support = dict(scenario["support_files"])
    support[PurePosixPath("legacy-recovery.py")] = _AUTHORED_RECOVERY_ENTRY
    scenario["support_files"] = support
    for relative, content in support.items():
        path = support_root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    scenario["environment"].update(
        APPRC_TEST_APP_ID=_IDENTITY.app_id,
        APPRC_TEST_IMPORT_ROOT=str(Path(installed_probe.__file__).parents[3]),
        APPRC_TEST_INSTALLATION=str(scenario["directory"]),
        APPRC_TEST_PREPARED_ROOT=str(
            scenario["tmp_path"] / "recovery prepared"
        ),
        APPRC_TEST_PYTHON_REQUIREMENT=">=3.12",
        APPRC_TEST_SUPPORT_ROOT=str(support_root),
    )


class _Scenario(TypedDict):
    archive: Path
    backend: UvToolTarget
    directory: Path
    environment: dict[str, str]
    legacy: LegacyReceiptInspection
    plan: LegacyReplacementPlan
    prepared: PreparedSource
    source: InstallationSource
    support_files: dict[PurePosixPath, bytes]
    tmp_path: Path


def _legacy_receipt_path(scenario: _Scenario) -> Path:
    receipt = scenario["legacy"].receipt
    assert receipt is not None
    return receipt.path


def _project(
    path: Path,
    version: str,
    *,
    distribution: str = _DISTRIBUTION,
    command: str = _COMMAND,
) -> None:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        "\n".join(
            (
                "[build-system]",
                'requires = ["setuptools>=80"]',
                'build-backend = "setuptools.build_meta"',
                "[project]",
                f'name = "{distribution}"',
                f'version = "{version}"',
                'requires-python = ">=3.12"',
                "[project.scripts]",
                f'{command} = "legacy_replacement_fixture:main"',
                "[tool.setuptools]",
                'py-modules = ["legacy_replacement_fixture"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    (path / "legacy_replacement_fixture.py").write_text(
        f'def main(): print("{version}")\n', encoding="utf-8"
    )


def _sdist(
    project: Path, destination: Path, *, version: str = "2.0.0"
) -> InstallationSource:
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(project.iterdir()):
            archive.add(path, arcname=f"{project.name}/{path.name}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return InstallationSource(
        "release-sdist", str(destination), version=version, digest=digest
    )


def _scenario(tmp_path: Path) -> _Scenario:
    uv = shutil.which("uv")
    assert uv is not None
    environment = dict(os.environ)
    environment.update(
        UV_TOOL_DIR=str(tmp_path / "tool environments"),
        UV_TOOL_BIN_DIR=str(tmp_path / "tool commands"),
        UV_CACHE_DIR=str(tmp_path / "uv cache"),
        LOCALAPPDATA=str(tmp_path / "Local AppData"),
        USERPROFILE=str(tmp_path / "User Profile"),
        HOME=str(tmp_path / "Home"),
        XDG_DATA_HOME=str(tmp_path / "XDG Data"),
    )
    backend = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    old_staging = tmp_path / "deleted arbitrary old staging"
    _project(old_staging, "1.0.0")
    install_uv_tool(
        backend,
        InstallationSource("index", str(old_staging), version="1.0.0"),
        environment=environment,
        python_requirement=">=3.12",
    )
    new_project = tmp_path / "replacement project"
    _project(new_project, "2.0.0")
    archive = tmp_path / "replacement source.tar.gz"
    source = _sdist(new_project, archive)

    payload_root = tmp_path / "replacement payload"
    payload_package = payload_root / "app_lifecycle"
    payload_package.mkdir(parents=True)
    (payload_package / "__init__.py").write_text("", encoding="utf-8")
    (payload_package / "install.py").write_text(
        "from pathlib import Path\n"
        "def main(): Path(__file__).with_name('installed').write_text('yes')\n",
        encoding="utf-8",
    )
    (payload_package / "uninstall.py").write_text(
        "from pathlib import Path\n"
        "def main(): Path(__file__).with_name('installed').unlink(missing_ok=True)\n",
        encoding="utf-8",
    )
    spec = DistributionSpec(
        ProjectMetadata(
            new_project,
            _IDENTITY,
            "2.0.0",
            launcher_command=_COMMAND,
        )
    )
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    support_files = install_support_files(spec, payload)
    placement = InstallationPlacement(Layout.native())
    old_observation = probe_installed_tool(
        backend,
        _IDENTITY,
        InstallationSource("index", str(old_staging), version="1.0.0"),
        placement,
        probe_path=Path(installed_probe.__file__).absolute(),
        environment=environment,
    )
    old_record_digest = old_observation.distribution_record_digest
    assert old_record_digest is not None
    shutil.rmtree(old_staging)

    directory = (
        Path(environment["XDG_DATA_HOME"]) / _IDENTITY.app_id / "installation"
    )
    directory.mkdir(mode=0o700, parents=True)
    legacy_root = directory
    (legacy_root / "uninstall.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8"
    )
    (legacy_root / "lifecycle.py").write_text(
        "raise SystemExit\n", encoding="utf-8"
    )
    base_python = external_base_python(backend.tool_dir / _DISTRIBUTION)
    receipt = legacy_root / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "distribution": _DISTRIBUTION,
                "command": _COMMAND,
                "version": "1.0.0",
                "source_ref": "https://example.invalid/arbitrary/old-source",
                "python": str(base_python),
                "uv": str(backend.executable),
                "tool_dir": str(backend.tool_dir),
                "tool_bin_dir": str(backend.bin_dir),
                "appdata_supported": False,
                "uv_bootstrapped": False,
                "package_removed": False,
                "uv_binaries": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    legacy = inspect_legacy_receipt(
        receipt, distribution=_DISTRIBUTION, command=_COMMAND
    )
    assert legacy.compatible
    directory = legacy_root
    inspection = inspect_installation(directory, app_id=_IDENTITY.app_id)
    inventory = MigrationInventory(directory, directory)
    plan = plan_legacy_replacement(
        inspection,
        _IDENTITY,
        source,
        placement,
        legacy=legacy,
        inventory=inventory,
        expected_record_digest=old_record_digest,
        quiescent=True,
    )
    prepared = prepare_source(
        source, tmp_path / "prepared content-addressed source"
    )
    return {
        "archive": archive,
        "backend": backend,
        "directory": directory,
        "environment": environment,
        "legacy": legacy,
        "plan": plan,
        "prepared": prepared,
        "source": source,
        "support_files": support_files,
        "tmp_path": tmp_path,
    }


def _run(
    scenario: _Scenario,
    *,
    plan: LegacyReplacementPlan | None = None,
    python_requirement: str = ">=3.12",
) -> InstallationInspection:
    plan = plan or scenario["plan"]
    return execute_legacy_replacement(
        plan,
        scenario["prepared"],
        environment=scenario["environment"],
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files=scenario["support_files"],
        python_requirement=python_requirement,
    )


def _resume_matching_entry(
    scenario: _Scenario,
    *,
    support_files: dict[PurePosixPath, bytes] | None = None,
) -> InstallationInspection:
    inspection = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    record = inspection.record
    revision = inspection.revision
    assert record is not None and revision is not None
    operation = record.operation
    if operation is None or operation.kind == "migrate":
        assert record.migration is not None
        operation_id = record.migration.operation_id
        assert operation_id is not None
        return migration.resume_migration(
            scenario["directory"],
            operation_id=operation_id,
            expected_revision=revision,
        )
    assert operation.kind == "replace" and operation.intended is not None
    prepared = prepare_source(
        operation.intended.source,
        scenario["tmp_path"] / "recovery sources" / str(operation.operation_id),
    )
    return resume_legacy_replacement(
        scenario["directory"],
        prepared,
        operation_id=operation.operation_id,
        expected_revision=revision,
        quiescent=True,
        environment=scenario["environment"],
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files=(
            scenario["support_files"]
            if support_files is None
            else support_files
        ),
        python_requirement=">=3.12",
    )


def test_real_uv_replaces_deleted_arbitrary_origin_and_preserves_payload(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    user_data = scenario["directory"].parent / "appdata"
    user_data.mkdir()
    payload = user_data / "workspace.txt"
    payload.write_text("keep", encoding="utf-8")
    result = _run(scenario, python_requirement=">=3.12rc1,<4")

    assert result.status == "ready"
    assert result.record is not None
    assert result.record.current is not None
    assert result.record.current.version == "2.0.0"
    assert result.record.current.source.digest == scenario["source"].digest
    saved_python = scenario["legacy"].base_python
    assert saved_python is not None
    saved_base = subprocess.run(
        [
            str(saved_python),
            "-I",
            "-c",
            "import sys; print(sys.prefix)",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    installed_base = subprocess.run(
        [
            str(result.record.current.interpreter),
            "-I",
            "-c",
            "import sys; print(sys.base_prefix)",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    assert (
        Path(saved_base.stdout.strip()).resolve()
        == Path(installed_base.stdout.strip()).resolve()
    )
    if os.name == "nt":
        pytest.skip("The real-uv launcher assertion is POSIX-specific.")
    assert scenario["support_files"][PurePosixPath("launch.sh")]
    launcher = subprocess.run(
        [str(scenario["directory"] / "launch.sh")],
        capture_output=True,
        check=True,
        env=scenario["environment"],
        text=True,
    )
    assert launcher.stdout == "2.0.0\n"
    assert payload.read_text(encoding="utf-8") == "keep"
    assert scenario["archive"].is_file()
    assert not _legacy_receipt_path(scenario).exists()


def test_legacy_replacement_refuses_wrong_record_and_unknown_namespace(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    plan = scenario["plan"]
    with pytest.raises(InstallationError, match="RECORD"):
        plan_legacy_replacement(
            inspect_installation(
                plan.install.directory, app_id=_IDENTITY.app_id
            ),
            _IDENTITY,
            scenario["source"],
            plan.install.target.placement,
            legacy=scenario["legacy"],
            inventory=plan.inventory,
            expected_record_digest="0" * 64,
            quiescent=True,
        )

    unknown = _legacy_receipt_path(scenario).parent / "user notes.txt"
    unknown.write_text("untouched", encoding="utf-8")
    with pytest.raises(InstallationError, match="Unknown legacy"):
        plan_legacy_replacement(
            inspect_installation(
                plan.install.directory, app_id=_IDENTITY.app_id
            ),
            _IDENTITY,
            scenario["source"],
            plan.install.target.placement,
            legacy=inspect_legacy_receipt(
                _legacy_receipt_path(scenario),
                distribution=_DISTRIBUTION,
                command=_COMMAND,
            ),
            inventory=plan.inventory,
            expected_record_digest=plan.expected_record_digest,
            quiescent=True,
        )
    assert unknown.read_text(encoding="utf-8") == "untouched"
    assert _legacy_receipt_path(scenario).exists()


def test_foreign_same_version_sources_are_refused_before_either_tool_changes(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    foreign_name = "legacy-replacement-foreign"
    foreign_command = "legacy-replacement-foreign-command"
    foreign_project = tmp_path / "installed unrelated project"
    _project(
        foreign_project,
        "2.0.0",
        distribution=foreign_name,
        command=foreign_command,
    )
    foreign_source = InstallationSource(
        "index", str(foreign_project), version="2.0.0"
    )
    install_uv_tool(
        scenario["backend"],
        foreign_source,
        environment=scenario["environment"],
        python_requirement=">=3.12",
    )
    foreign_entry = scenario["backend"].bin_dir / foreign_command
    legacy_entry = scenario["backend"].bin_dir / _COMMAND
    foreign_before = subprocess.run(
        [str(foreign_entry)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    legacy_before = subprocess.run(
        [str(legacy_entry)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    old_record = scenario["plan"].record_entry.path.read_bytes()
    foreign_identity = InstallationIdentity(
        "legacy-replacement-foreign",
        foreign_name,
        "legacy_replacement_fixture",
        None,
        (foreign_command,),
    )
    foreign_snapshot = probe_installed_tool(
        scenario["backend"],
        foreign_identity,
        foreign_source,
        scenario["plan"].install.target.placement,
        probe_path=Path(installed_probe.__file__).absolute(),
        environment=scenario["environment"],
    )
    assert foreign_snapshot.distribution_record_digest is not None
    foreign_record_digest = foreign_snapshot.distribution_record_digest
    dist_info = f"{foreign_name.replace('-', '_')}-2.0.0.dist-info"
    module_name = "legacy_replacement_foreign_fixture"
    wheel_files = {
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {foreign_name}\nVersion: 2.0.0\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode(),
        f"{dist_info}/entry_points.txt": (
            f"[console_scripts]\n{foreign_command} = {module_name}:main\n"
        ).encode(),
        f"{module_name}.py": b'def main(): print("2.0.0")\n',
    }
    record_lines = []
    for name, content in wheel_files.items():
        digest_record = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        record_lines.append(f"{name},sha256={digest_record},{len(content)}")
    record_lines.append(f"{dist_info}/RECORD,,")
    wheel_files[f"{dist_info}/RECORD"] = (
        "\n".join(record_lines) + "\n"
    ).encode()
    wheel_path = (
        tmp_path / f"{foreign_name.replace('-', '_')}-2.0.0-py3-none-any.whl"
    )
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        for name, content in wheel_files.items():
            wheel.writestr(name, content)
    digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    source = InstallationSource(
        "wheel", str(wheel_path), version="2.0.0", digest=digest
    )
    prepared = prepare_source(source, tmp_path / "foreign wheel preparation")
    plan = plan_legacy_replacement(
        inspect_installation(scenario["directory"], app_id=_IDENTITY.app_id),
        _IDENTITY,
        source,
        scenario["plan"].install.target.placement,
        legacy=scenario["legacy"],
        inventory=scenario["plan"].inventory,
        expected_record_digest=scenario["plan"].expected_record_digest,
        quiescent=True,
    )
    with pytest.raises(InstallationError, match="distribution differs"):
        execute_legacy_replacement(
            plan,
            prepared,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )

    assert scenario["plan"].record_entry.path.read_bytes() == old_record
    assert _legacy_receipt_path(scenario).is_file()
    assert (
        subprocess.run(
            [str(legacy_entry)],
            check=True,
            capture_output=True,
            text=True,
            env=scenario["environment"],
        ).stdout
        == legacy_before.stdout
        == "1.0.0\n"
    )
    assert (
        subprocess.run(
            [str(foreign_entry)],
            check=True,
            capture_output=True,
            text=True,
            env=scenario["environment"],
        ).stdout
        == foreign_before.stdout
        == "2.0.0\n"
    )
    foreign_snapshot_after = probe_installed_tool(
        scenario["backend"],
        foreign_identity,
        foreign_source,
        scenario["plan"].install.target.placement,
        probe_path=Path(installed_probe.__file__).absolute(),
        environment=scenario["environment"],
    )
    assert (
        foreign_snapshot_after.distribution_record_digest
        == foreign_record_digest
    )

    foreign_sdist = _sdist(
        foreign_project,
        tmp_path / "foreign same-version project.tar.gz",
        version="2.0.0",
    )
    foreign_sdist_prepared = prepare_source(
        foreign_sdist, tmp_path / "foreign same-version project preparation"
    )
    sdist_plan = plan_legacy_replacement(
        inspect_installation(scenario["directory"], app_id=_IDENTITY.app_id),
        _IDENTITY,
        foreign_sdist,
        scenario["plan"].install.target.placement,
        legacy=scenario["legacy"],
        inventory=scenario["plan"].inventory,
        expected_record_digest=scenario["plan"].expected_record_digest,
        quiescent=True,
    )
    with pytest.raises(InstallationError, match="distribution differs"):
        execute_legacy_replacement(
            sdist_plan,
            foreign_sdist_prepared,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )
    assert scenario["plan"].record_entry.path.read_bytes() == old_record
    assert _legacy_receipt_path(scenario).is_file()
    assert (
        probe_installed_tool(
            scenario["backend"],
            foreign_identity,
            foreign_source,
            scenario["plan"].install.target.placement,
            probe_path=Path(installed_probe.__file__).absolute(),
            environment=scenario["environment"],
        ).distribution_record_digest
        == foreign_record_digest
    )


def test_historical_replacement_refuses_a_stolen_uv_command(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    foreign_project = tmp_path / "command-taking unrelated project"
    _project(
        foreign_project,
        "2.0.0",
        distribution="legacy-replacement-command-taker",
        command=_COMMAND,
    )
    install_uv_tool(
        scenario["backend"],
        InstallationSource("index", str(foreign_project), version="2.0.0"),
        environment=scenario["environment"],
        python_requirement=">=3.12",
    )
    foreign_command = scenario["backend"].bin_dir / _COMMAND
    foreign_before = subprocess.run(
        [str(foreign_command)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    old_record = scenario["plan"].record_entry.path.read_bytes()
    with pytest.raises(InstallationError, match="Console command"):
        plan_legacy_replacement(
            inspect_installation(
                scenario["directory"], app_id=_IDENTITY.app_id
            ),
            _IDENTITY,
            scenario["source"],
            scenario["plan"].install.target.placement,
            legacy=scenario["legacy"],
            inventory=scenario["plan"].inventory,
            expected_record_digest=scenario["plan"].expected_record_digest,
            quiescent=True,
        )

    assert _legacy_receipt_path(scenario).is_file()
    assert scenario["plan"].record_entry.path.read_bytes() == old_record
    foreign_after = subprocess.run(
        [str(foreign_command)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    assert foreign_after.stdout == foreign_before.stdout == "2.0.0\n"


def test_historical_record_association_ignores_prefix_related_uv_tool(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    related_project = tmp_path / "prefix-related unrelated project"
    _project(
        related_project,
        "1.0.0",
        distribution=f"{_DISTRIBUTION}-extra",
        command="legacy-replacement-related-command",
    )
    install_uv_tool(
        scenario["backend"],
        InstallationSource("index", str(related_project), version="1.0.0"),
        environment=scenario["environment"],
        python_requirement=">=3.12",
    )
    plan = plan_legacy_replacement(
        inspect_installation(scenario["directory"], app_id=_IDENTITY.app_id),
        _IDENTITY,
        scenario["source"],
        scenario["plan"].install.target.placement,
        legacy=scenario["legacy"],
        inventory=scenario["plan"].inventory,
        expected_record_digest=scenario["plan"].expected_record_digest,
        quiescent=True,
    )
    target_prefix = scenario["backend"].tool_dir / _DISTRIBUTION
    assert plan.record_entry.path.is_relative_to(target_prefix)
    assert plan.record_entry.path == scenario["plan"].record_entry.path


def test_historical_target_metadata_ambiguity_is_refused(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    original_info = scenario["plan"].record_entry.path.parent
    duplicate_info = original_info.with_name(
        f"{_DISTRIBUTION.replace('-', '_')}-duplicate-1.0.0.dist-info"
    )
    shutil.copytree(original_info, duplicate_info)
    duplicate_record = duplicate_info / "RECORD"
    duplicate_record.write_text(
        duplicate_record.read_text(encoding="utf-8").replace(
            original_info.name, duplicate_info.name
        ),
        encoding="utf-8",
    )
    with pytest.raises(InstallationError, match="ambiguous"):
        plan_legacy_replacement(
            inspect_installation(
                scenario["directory"], app_id=_IDENTITY.app_id
            ),
            _IDENTITY,
            scenario["source"],
            scenario["plan"].install.target.placement,
            legacy=scenario["legacy"],
            inventory=scenario["plan"].inventory,
            expected_record_digest=scenario["plan"].expected_record_digest,
            quiescent=True,
        )


def test_immutable_source_version_mismatch_is_rejected_before_backend_mutation(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    wrong_project = tmp_path / "wrong immutable source project"
    _project(wrong_project, "3.0.0")
    wrong_source = _sdist(
        wrong_project,
        tmp_path / "wrong immutable source.tar.gz",
        version="2.0.0",
    )
    prepared = prepare_source(
        wrong_source, tmp_path / "prepared wrong immutable source"
    )
    plan = plan_legacy_replacement(
        inspect_installation(scenario["directory"], app_id=_IDENTITY.app_id),
        _IDENTITY,
        wrong_source,
        scenario["plan"].install.target.placement,
        legacy=scenario["legacy"],
        inventory=scenario["plan"].inventory,
        expected_record_digest=scenario["plan"].expected_record_digest,
        quiescent=True,
    )
    with pytest.raises(
        InstallationError, match="differs from the selected source"
    ):
        execute_legacy_replacement(
            plan,
            prepared,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )

    assert _legacy_receipt_path(scenario).exists()
    assert (
        hashlib.sha256(plan.record_entry.path.read_bytes()).hexdigest()
        == plan.expected_record_digest
    )


def test_invalid_python_requirement_is_rejected_before_pending_authority(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    with pytest.raises(InstallationError, match="Cannot verify"):
        execute_legacy_replacement(
            scenario["plan"],
            scenario["prepared"],
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement="=>3.12",
        )
    inspection = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert inspection.record is None
    assert _legacy_receipt_path(scenario).exists()


def test_incompatible_recorded_base_python_is_rejected_before_pending_authority(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    with pytest.raises(
        InstallationError, match="does not satisfy the declared requirement"
    ):
        execute_legacy_replacement(
            scenario["plan"],
            scenario["prepared"],
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=99",
        )

    inspection = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert inspection.record is None
    assert _legacy_receipt_path(scenario).exists()
    assert (
        hashlib.sha256(
            scenario["plan"].record_entry.path.read_bytes()
        ).hexdigest()
        == scenario["plan"].expected_record_digest
    )


@pytest.mark.parametrize("recovery_content", (None, b""))
def test_replacement_requires_a_nonempty_authored_recovery_entry(
    tmp_path: Path,
    recovery_content: bytes | None,
) -> None:
    scenario = _scenario(tmp_path)
    support_files = {
        path: content
        for path, content in scenario["support_files"].items()
        if path.name not in {"repair-installer.py", "legacy-recovery.py"}
    }
    if recovery_content is not None:
        support_files[PurePosixPath("legacy-recovery.py")] = recovery_content

    with pytest.raises(
        InstallationError, match="nonempty authored recovery entry"
    ):
        execute_legacy_replacement(
            scenario["plan"],
            scenario["prepared"],
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=support_files,
            python_requirement=">=3.12",
        )

    inspection = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert inspection.record is None
    assert _legacy_receipt_path(scenario).is_file()
    assert scenario["plan"].record_entry.path.is_file()
    assert (
        hashlib.sha256(
            scenario["plan"].record_entry.path.read_bytes()
        ).hexdigest()
        == scenario["plan"].expected_record_digest
    )
    old_output = subprocess.run(
        [str(scenario["backend"].bin_dir / _COMMAND)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    assert old_output.stdout == "1.0.0\n"


@pytest.mark.parametrize(
    "barrier",
    (
        "before-backend",
        "after-backend",
        "before-retire",
        "after-retire",
        "before-activation",
        "after-activation",
    ),
)
def test_real_uv_replacement_resumes_recorded_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    barrier: str,
) -> None:
    scenario = _scenario(tmp_path)
    original_install = legacy_replacement.install_uv_tool
    original_retire = migration._retire_legacy_controllers
    original_promote = migration._promote_staged_support
    original_write_record = migration.write_record
    interrupted = False

    def install_barrier(*args, **kwargs):
        nonlocal interrupted
        if barrier == "before-backend" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted before-backend")
        result = original_install(*args, **kwargs)
        if barrier == "after-backend" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after-backend")
        return result

    def retirement_barrier(*args, **kwargs):
        nonlocal interrupted
        if barrier == "before-retire" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted before-retire")
        return original_retire(*args, **kwargs)

    def retire_barrier(*args, **kwargs):
        nonlocal interrupted
        if barrier == "after-retire" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after-retire")
        return original_promote(*args, **kwargs)

    def activation_barrier(directory, record, *, expected_revision):
        nonlocal interrupted
        before_activation = (
            barrier == "before-activation"
            and record.operation is None
            and record.migration is not None
            and record.migration.phase == "activated"
            and not interrupted
        )
        if before_activation:
            interrupted = True
            raise RuntimeError("interrupted before-activation")
        result = original_write_record(
            directory, record, expected_revision=expected_revision
        )
        after_activation = (
            barrier == "after-activation"
            and record.migration is not None
            and record.migration.phase == "activated"
            and not interrupted
        )
        if after_activation:
            interrupted = True
            raise RuntimeError("interrupted after-activation")
        return result

    monkeypatch.setattr(legacy_replacement, "install_uv_tool", install_barrier)
    monkeypatch.setattr(
        migration, "_retire_legacy_controllers", retirement_barrier
    )
    monkeypatch.setattr(migration, "_promote_staged_support", retire_barrier)
    monkeypatch.setattr(migration, "write_record", activation_barrier)
    with pytest.raises(Exception):
        _run(scenario)
    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )

    assert pending.record is not None
    assert (
        pending.record.generation_id == scenario["plan"].install.generation_id
    )
    operation = pending.record.operation
    if operation is not None and operation.kind == "replace":
        assert is_pending_legacy_replacement(pending)
        ordinary_replacement = replace(
            pending,
            record=replace(
                pending.record,
                operation=replace(operation, inventory=CleanupInventory()),
            ),
        )
        assert not is_pending_legacy_replacement(ordinary_replacement)
        damaged_record = replace(
            pending,
            record=replace(
                pending.record,
                operation=replace(
                    operation,
                    inventory=replace(
                        operation.inventory,
                        retained=tuple(
                            item
                            for item in operation.inventory.retained
                            if item.path.name != "RECORD"
                        ),
                    ),
                ),
            ),
        )
        assert is_pending_legacy_replacement(damaged_record)
    else:
        assert not is_pending_legacy_replacement(pending)
    if operation is not None:
        assert operation.operation_id == scenario["plan"].install.operation_id
        assert pending.record.last_successful is None
        assert pending.record.current is None or (
            pending.record.current.version == "2.0.0"
        )
    else:
        assert pending.record.status == "ready"
        assert pending.record.current is not None
        assert pending.record.current.version == "2.0.0"
    result = _resume_matching_entry(scenario)
    assert not is_pending_legacy_replacement(result)
    assert result.status == "ready"
    assert result.revision is not None
    repeated = migration.resume_migration(
        scenario["directory"],
        operation_id=scenario["plan"].install.operation_id,
        expected_revision=result.revision,
    )
    assert repeated.record == result.record
    assert result.record is not None and result.record.current is not None
    assert result.record.current.version == "2.0.0"
    assert _legacy_receipt_path(scenario).exists() is False
    assert interrupted


@pytest.mark.parametrize(
    "interruption",
    ("after-backend", "during-final-staging", "after-initial-authority"),
)
def test_authored_recovery_entry_resumes_after_deleted_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    scenario = _scenario(tmp_path)
    payload = scenario["directory"].parent / "appdata" / "workspace.txt"
    payload.parent.mkdir()
    payload.write_text("keep", encoding="utf-8")
    support_root = tmp_path / "authored recovery support"
    _write_recovery_support(scenario, support_root)
    interrupted = False
    if interruption == "after-initial-authority":
        original_write_record = legacy_replacement.write_record

        def fail_after_initial_authority(*args, **kwargs):
            nonlocal interrupted
            result = original_write_record(*args, **kwargs)
            record = args[1]
            if (
                record.operation is not None
                and record.operation.kind == "replace"
                and not interrupted
            ):
                interrupted = True
                raise RuntimeError("interrupted after initial authority write")
            return result

        monkeypatch.setattr(
            legacy_replacement, "write_record", fail_after_initial_authority
        )
    elif interruption == "after-backend":
        original_install = legacy_replacement.install_uv_tool

        def fail_after_backend_replacement(*args, **kwargs):
            nonlocal interrupted
            result = original_install(*args, **kwargs)
            if not interrupted:
                interrupted = True
                raise RuntimeError("interrupted after backend replacement")
            return result

        monkeypatch.setattr(
            legacy_replacement,
            "install_uv_tool",
            fail_after_backend_replacement,
        )
    else:
        original_write = legacy_replacement.write_bytes_atomic

        def fail_during_final_staging(path, content, **kwargs):
            nonlocal interrupted
            result = original_write(path, content, **kwargs)
            if Path(path).name.startswith("final-") and not interrupted:
                interrupted = True
                raise RuntimeError("interrupted during final support staging")
            return result

        monkeypatch.setattr(
            legacy_replacement,
            "write_bytes_atomic",
            fail_during_final_staging,
        )
    with pytest.raises(Exception):
        _run(scenario)
    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.record is not None
    assert pending.record.operation is not None
    assert pending.record.operation.kind == "replace"
    assert (
        pending.record.operation.operation_id
        == scenario["plan"].install.operation_id
    )
    assert (
        pending.record.generation_id == scenario["plan"].install.generation_id
    )
    assert _legacy_receipt_path(scenario).is_file()
    if interruption == "after-backend":
        assert pending.record.current is None
    elif interruption == "during-final-staging":
        assert pending.record.current is not None
        assert pending.record.current.version == "2.0.0"
    else:
        assert pending.record.current is None
        assert (
            pending.record.operation.intended == scenario["plan"].install.target
        )
    if interruption == "after-initial-authority":
        old_command = scenario["backend"].bin_dir / _COMMAND
        old_output = subprocess.run(
            [str(old_command)],
            check=True,
            capture_output=True,
            text=True,
            env=scenario["environment"],
        )
        assert old_output.stdout == "1.0.0\n"

    prepared = scenario["prepared"]
    if prepared.archive is not None:
        prepared.archive.unlink()
    if prepared.source_root is not None:
        shutil.rmtree(prepared.source_root)
    scenario["archive"].unlink()
    shutil.rmtree(support_root)
    if prepared.archive is not None:
        shutil.rmtree(prepared.archive.parent)
    shutil.rmtree(tmp_path / "replacement project")
    retained = tuple(
        item.path
        for item in pending.record.operation.inventory.retained
        if item.path.is_relative_to(scenario["directory"] / "migration-staged")
    )
    raw_retained = tuple(
        path for path in retained if not path.name.startswith("final-")
    )
    assert raw_retained
    assert all(path.is_file() for path in raw_retained)
    if interruption == "during-final-staging":
        assert any(path.name.startswith("final-") for path in retained)

    recovery_entry = scenario["directory"] / "legacy-recovery.py"
    assert recovery_entry.is_file()
    assert recovery_entry.read_bytes() == _AUTHORED_RECOVERY_ENTRY
    subprocess.run(
        [sys.executable, str(recovery_entry)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )

    recovered = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert recovered.record is not None
    assert recovered.record.status == "ready"
    assert recovered.record.operation is None
    assert (
        recovered.record.generation_id == scenario["plan"].install.generation_id
    )
    assert recovered.record.current is not None
    assert recovered.record.current.source == scenario["source"]
    assert recovered.record.current.backend == scenario["backend"]
    assert (
        recovered.record.current.placement
        == scenario["plan"].install.target.placement
    )
    assert recovered.record.current.distribution_record_digest is not None
    verified = probe_installed_tool(
        scenario["backend"],
        _IDENTITY,
        scenario["source"],
        scenario["plan"].install.target.placement,
        probe_path=Path(installed_probe.__file__).absolute(),
        environment=scenario["environment"],
        expected_record_digest=(
            recovered.record.current.distribution_record_digest
        ),
    )
    assert (
        recovered.record.current.distribution_record_digest
        == verified.distribution_record_digest
    )
    assert payload.read_text(encoding="utf-8") == "keep"
    commands = recovered.record.current.commands
    assert len(commands) == 1
    launched = subprocess.run(
        [str(commands[0])],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    assert launched.stdout == "2.0.0\n"
    assert (scenario["directory"] / "legacy-recovery.py").read_bytes() == (
        _AUTHORED_RECOVERY_ENTRY
    )
    assert _legacy_receipt_path(scenario).exists() is False
    assert interrupted


def test_interrupted_initial_recovery_entry_publication_preserves_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(tmp_path)
    support_root = tmp_path / "authored recovery support"
    _write_recovery_support(scenario, support_root)
    original_write = legacy_replacement.write_bytes_atomic
    interrupted = False

    def fail_after_recovery_entry_write(path, content, **kwargs):
        nonlocal interrupted
        result = original_write(path, content, **kwargs)
        if Path(path).name == "legacy-recovery.py" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after initial recovery entry write")
        return result

    monkeypatch.setattr(
        legacy_replacement,
        "write_bytes_atomic",
        fail_after_recovery_entry_write,
    )
    with pytest.raises(Exception, match="initial recovery entry"):
        _run(scenario)

    inspection = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert inspection.record is None
    assert inspection.status == "missing"
    assert _legacy_receipt_path(scenario).is_file()
    assert scenario["plan"].record_entry.path.is_file()
    assert (
        hashlib.sha256(
            scenario["plan"].record_entry.path.read_bytes()
        ).hexdigest()
        == scenario["plan"].expected_record_digest
    )
    assert not (scenario["directory"] / "legacy-recovery.py").exists()
    assert not (
        scenario["directory"]
        / "migration-staged"
        / str(scenario["plan"].install.generation_id)
    ).exists()
    assert not (scenario["directory"] / "migration-staged").exists()
    assert interrupted
    assert (scenario["directory"] / "locks" / "operation.lock").is_file()
    retried = _run(scenario)
    assert retried.record is not None
    assert retried.record.status == "ready"
    assert _legacy_receipt_path(scenario).exists() is False


@pytest.mark.parametrize(
    "interruption", ("after-observation", "during-final-staging")
)
def test_checkpointed_replacement_resumes_without_reinstalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    scenario = _scenario(tmp_path)
    interrupted = False
    if interruption == "after-observation":
        original_record_step = legacy_replacement.record_step

        def interrupt_after_saved_observation(*args, **kwargs):
            nonlocal interrupted
            result = original_record_step(*args, **kwargs)
            if (
                kwargs.get("step")
                is legacy_replacement.OperationStep.PACKAGE_CHANGED
                and kwargs.get("observed") is not None
            ):
                interrupted = True
                raise RuntimeError(
                    "interrupted after saved package observation"
                )
            return result

        monkeypatch.setattr(
            legacy_replacement,
            "record_step",
            interrupt_after_saved_observation,
        )
        interruption_message = "saved package observation"
    else:
        original_write = legacy_replacement.write_bytes_atomic

        def interrupt_during_final_support(path, content, **kwargs):
            nonlocal interrupted
            result = original_write(path, content, **kwargs)
            if Path(path).name.startswith("final-") and not interrupted:
                interrupted = True
                raise RuntimeError("interrupted during final support staging")
            return result

        monkeypatch.setattr(
            legacy_replacement,
            "write_bytes_atomic",
            interrupt_during_final_support,
        )
        interruption_message = "final support staging"
    with pytest.raises(Exception, match=interruption_message):
        _run(scenario)
    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.record is not None and pending.record.current is not None
    assert pending.revision is not None
    saved = pending.record.current
    assert saved.distribution_record_digest is not None
    command = saved.commands[0]
    command_bytes = command.read_bytes()
    launched_before = subprocess.run(
        [str(command)],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    assert launched_before.stdout == "2.0.0\n"
    fresh = prepare_source(
        scenario["source"], tmp_path / "fresh recovery preparation elsewhere"
    )
    monkeypatch.setattr(
        legacy_replacement,
        "install_uv_tool",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("observed successful replacement was reinstalled")
        ),
    )
    ready = resume_legacy_replacement(
        scenario["directory"],
        fresh,
        operation_id=scenario["plan"].install.operation_id,
        expected_revision=pending.revision,
        quiescent=True,
        environment=scenario["environment"],
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files=scenario["support_files"],
        python_requirement=">=3.12",
    )
    assert ready.status == "ready"
    assert ready.record is not None and ready.record.current is not None
    assert (
        ready.record.current.distribution_record_digest
        == saved.distribution_record_digest
    )
    assert ready.record.current.commands[0].read_bytes() == command_bytes
    launched_after = subprocess.run(
        [str(ready.record.current.commands[0])],
        check=True,
        capture_output=True,
        text=True,
        env=scenario["environment"],
    )
    assert launched_after.stdout == "2.0.0\n"
    assert interrupted


def test_unclaimed_equal_final_stage_bytes_are_not_adopted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(tmp_path)
    original_record_step = legacy_replacement.record_step
    interrupted = False

    def interrupt_with_unclaimed_equal_stage(*args, **kwargs):
        nonlocal interrupted
        result = original_record_step(*args, **kwargs)
        if (
            kwargs.get("step")
            is legacy_replacement.OperationStep.PACKAGE_CHANGED
            and kwargs.get("observed") is not None
        ):
            bound = legacy_replacement.bind_install_support(
                scenario["support_files"],
                kwargs["observed"],
                scenario["directory"],
            )
            relative, content = next(iter(bound.items()))
            stage_root = (
                scenario["directory"]
                / "migration-staged"
                / str(scenario["plan"].install.generation_id)
            )
            unclaimed = legacy_replacement._final_support_source(
                stage_root, relative
            )
            unclaimed.parent.mkdir(parents=True, exist_ok=True)
            unclaimed.write_bytes(content)
            interrupted = True
            raise RuntimeError("inserted unclaimed equal final-stage bytes")
        return result

    monkeypatch.setattr(
        legacy_replacement, "record_step", interrupt_with_unclaimed_equal_stage
    )
    with pytest.raises(Exception, match="unclaimed equal"):
        _run(scenario)
    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.record is not None and pending.record.current is not None
    assert pending.revision is not None
    with pytest.raises(InstallationError, match="Unknown content"):
        resume_legacy_replacement(
            scenario["directory"],
            operation_id=scenario["plan"].install.operation_id,
            expected_revision=pending.revision,
            quiescent=True,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )
    assert interrupted


def test_pending_replacement_requires_matching_operation_and_quiescence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario(tmp_path)
    monkeypatch.setattr(
        legacy_replacement,
        "install_uv_tool",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("interrupted before install")
        ),
    )
    with pytest.raises(RuntimeError, match="interrupted before install"):
        _run(scenario)
    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.record is not None and pending.record.operation is not None
    assert pending.record.current is None
    assert pending.revision is not None
    with pytest.raises(InstallationError, match="Stop legacy consumers"):
        resume_legacy_replacement(
            scenario["directory"],
            scenario["prepared"],
            operation_id=pending.record.operation.operation_id,
            expected_revision=pending.revision,
            quiescent=False,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )

    operation_id = pending.record.operation.operation_id
    with pytest.raises(InstallationError, match="operation"):
        resume_legacy_replacement(
            scenario["directory"],
            scenario["prepared"],
            operation_id=UUID(int=0),
            expected_revision=pending.revision,
            quiescent=True,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )

    wrong_project = tmp_path / "wrong replacement project"
    _project(wrong_project, "3.0.0")
    wrong_source = _sdist(
        wrong_project,
        tmp_path / "wrong replacement source.tar.gz",
        version="3.0.0",
    )
    wrong_prepared = prepare_source(
        wrong_source, tmp_path / "prepared wrong content-addressed source"
    )
    with pytest.raises(InstallationError, match="differs from pending"):
        resume_legacy_replacement(
            scenario["directory"],
            wrong_prepared,
            operation_id=operation_id,
            expected_revision=pending.revision,
            quiescent=True,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=scenario["support_files"],
            python_requirement=">=3.12",
        )

    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.revision is not None
    changed_support = dict(scenario["support_files"])
    changed_support[PurePosixPath("launch.sh")] = b"#!/bin/sh\nexit 3\n"
    with pytest.raises(InstallationError, match="authored pending generation"):
        resume_legacy_replacement(
            scenario["directory"],
            scenario["prepared"],
            operation_id=operation_id,
            expected_revision=pending.revision,
            quiescent=True,
            environment=scenario["environment"],
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=changed_support,
            python_requirement=">=3.12",
        )

    pending = inspect_installation(
        scenario["directory"], app_id=_IDENTITY.app_id
    )
    assert pending.record is not None and pending.record.operation is not None
    assert pending.revision is not None
    monkeypatch.undo()
    result = _resume_matching_entry(scenario)
    assert result.status == "ready"
    assert result.record is not None and result.record.current is not None
    assert result.record.current.version == "2.0.0"
    assert _legacy_receipt_path(scenario).exists() is False
