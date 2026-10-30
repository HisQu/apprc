"""Author inputs and generated artifact behavior, independent of installation."""

import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Literal

import pytest

from apprc import AppRC, Paths
from apprc.distribution.artifacts import write_artifacts
from apprc.distribution.metadata import (
    inspect_capabilities,
    read_project_metadata,
)
from apprc.distribution.models import Artifact, PayloadTree
from apprc.definition.installation import InstallationIdentity
from apprc.distribution.models import DistributionSpec, ProjectMetadata
from apprc.distribution.rendering import build_main_installer
from apprc.user_files.installation.discovery import inspect_installation


def test_artifact_check_is_zero_write_and_names_drift(tmp_path: Path) -> None:
    root = tmp_path / "not-created"
    artifact = Artifact(PurePosixPath("nested/main.py"), b"first\n", True, root)
    with pytest.raises(ValueError, match="nested/main.py"):
        write_artifacts((artifact,), check=True)
    assert not root.exists()
    write_artifacts((artifact,))
    target = root / artifact.destination
    target.write_bytes(b"user changed generated artifact\n")
    before = target.stat().st_mtime_ns
    with pytest.raises(ValueError, match="drifted"):
        write_artifacts((artifact,), check=True)
    assert target.read_bytes() == b"user changed generated artifact\n"
    assert target.stat().st_mtime_ns == before
    write_artifacts((artifact,))
    assert target.read_bytes() == b"first\n"
    write_artifacts((artifact,), check=True)


def test_artifact_address_cannot_escape_project(tmp_path: Path) -> None:
    for destination in (
        "../outside",
        "/absolute",
        "C:/outside",
        "nested\\outside",
    ):
        with pytest.raises(ValueError):
            Artifact(PurePosixPath(destination), b"unsafe", False, tmp_path)


def test_payload_rejects_duplicate_and_missing_entry_modules(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        PayloadTree(tmp_path, (PurePosixPath("app_lifecycle/install.py"),) * 2)
    with pytest.raises(ValueError, match="does not include entry"):
        PayloadTree(tmp_path, (PurePosixPath("app_lifecycle/install.py"),))


def test_project_identities_are_distinct_and_no_app_import_is_needed(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "Package.Name"
version = "2.0.0"
[project.scripts]
cli-name = "unimportable_package.cli:main"
[tool.apprc.distribution]
app-id = "persistent-identity"
import-package = "unimportable_package"
apprc-reference = "unimportable_package.config:MyRC"
""",
        encoding="utf-8",
    )
    metadata = read_project_metadata(tmp_path)
    assert metadata.identity.app_id == "persistent-identity"
    assert metadata.identity.distribution == "package-name"
    assert metadata.identity.import_package == "unimportable_package"
    assert metadata.identity.commands == ("cli-name",)
    assert (
        metadata.identity.apprc_reference == "unimportable_package.config:MyRC"
    )


def test_capability_inspection_needs_no_settings_or_installation() -> None:
    app = AppRC(app_id="generation-fixture", paths=Paths(cache=True))
    capabilities = inspect_capabilities(app)
    assert capabilities.paths == Paths(cache=True)
    assert not capabilities.workspaces
    assert not app.installation().directory.exists()


def _standalone_payload(root: Path) -> PayloadTree:
    package = root / "app_lifecycle"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '"""Repository-owned composition."""\n'
    )
    (package / "install.py").write_text(
        """
import importlib.metadata
import sys
from pathlib import Path
from apprc.distribution.runtime import (
    InstallationIdentity, InstallationPlacement, InstallationSource, UvToolTarget,
    begin_operation, plan_install,
)
from apprc.definition.paths import Layout
from apprc.user_files.installation.discovery import inspect_installation

try:
    importlib.metadata.distribution("apprc-core")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    raise RuntimeError("Test requires an environment without installed AppRC")
root = Path(sys.argv[1])
identity = InstallationIdentity("standalone-fixture", "standalone-fixture", "fixture", None, ())
plan = plan_install(
    identity, InstallationSource("index", "standalone-fixture"),
    InstallationPlacement(Layout.native()),
    UvToolTarget(root / "uv", root / "tools", root / "bin"),
    inspection=inspect_installation(root / "installation", app_id=identity.app_id),
)
begin_operation(plan)
""",
        encoding="utf-8",
    )
    (package / "uninstall.py").write_text(
        '"""Repository cleanup composition."""\n'
    )
    return PayloadTree(
        root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in (
                "__init__.py",
                "install.py",
                "uninstall.py",
            )
        ),
    )


@pytest.mark.parametrize("format", ("script", "zipapp"))
def test_emitted_composition_runs_without_installed_apprc(
    tmp_path: Path, format: Literal["script", "zipapp"]
) -> None:
    uv = shutil.which("uv")
    assert uv is not None, (
        "Standalone consumer verification requires the supported uv command"
    )
    payload = _standalone_payload(tmp_path / "payload")
    spec = DistributionSpec(
        ProjectMetadata(
            tmp_path / "author",
            InstallationIdentity(
                "standalone-fixture", "standalone-fixture", "fixture", None, ()
            ),
            "1.0",
        ),
        payload_format=format,
    )
    artifact = build_main_installer(spec, payload)
    other = build_main_installer(
        replace(
            spec,
            metadata=replace(
                spec.metadata, project_root=tmp_path / "other-author"
            ),
        ),
        payload,
    )
    assert artifact.content == other.content
    write_artifacts((artifact,))
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    command = [
        uv,
        "run",
        "--isolated",
        "--no-project",
        "--python",
        sys.executable,
    ]
    path = artifact.project_root / artifact.destination
    output = tmp_path / "actual management result"
    if format == "script":
        command.extend(("--script", str(path), str(output)))
    else:
        command.extend(
            (
                "--with",
                "filelock==3.32.7",
                "--with",
                "platformdirs==4.10.0",
                "python",
                str(path),
                str(output),
            )
        )
    result = subprocess.run(
        command,
        env=environment,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = inspect_installation(
        output / "installation", app_id="standalone-fixture"
    )
    assert observed.status == "provisional"
    assert observed.record is not None and observed.record.operation is not None
    assert observed.record.operation.kind == "install"
