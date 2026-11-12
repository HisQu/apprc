"""Author inputs and generated artifact behavior, independent of installation."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    InstallationSource,
    InstalledSnapshot,
    OwnedOutput,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.distribution.artifacts import write_artifacts
from apprc.distribution.metadata import (
    inspect_capabilities,
    read_project_metadata,
)
from apprc.distribution.models import (
    Artifact,
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import (
    build_main_installer,
    install_support_files,
)
from apprc.user_files.installation.codec import encode_record
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


def test_bundle_repository_metadata_accepts_only_string_lists(
    tmp_path: Path,
) -> None:
    project = (
        '[project]\nname = "metadata-fixture"\nversion = "1.0.0"\n'
        '[project.scripts]\nmetadata-fixture = "fixture:main"\n'
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        project
        + "[tool.apprc.distribution]\n"
        + 'bundle-repositories = ["https://example.invalid/repo"]\n',
        encoding="utf-8",
    )
    assert read_project_metadata(tmp_path).bundle_repositories == (
        "https://example.invalid/repo",
    )
    for setting in (
        'bundle-repositories = "https://example.invalid/repo"',
        'bundle-repositories = ["https://example.invalid/repo", 1]',
        '[tool.apprc.distribution.bundle-repositories]\nurl = "https://example.invalid/repo"',
        'unknown = "value"',
    ):
        pyproject.write_text(
            project + "[tool.apprc.distribution]\n" + setting + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            read_project_metadata(tmp_path)


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
import json
import sys
from pathlib import Path
from uuid import uuid4
from apprc.distribution.runtime import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
    UvToolTarget,
    begin_operation,
    plan_install,
)
from apprc.distribution.runtime.controllers import default_cleanup_inventory
from apprc.definition.installation import InstallationRecord
from apprc.definition.paths import Layout
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation

try:
    importlib.metadata.distribution("apprc-core")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    raise RuntimeError("Test requires an environment without installed AppRC")
root = Path(sys.argv[1])
identity = InstallationIdentity(
    "standalone-fixture", "standalone-fixture", "fixture", None, ()
)
plan = plan_install(
    identity,
    InstallationSource("index", "standalone-fixture"),
    InstallationPlacement(Layout.native()),
    UvToolTarget(root / "uv", root / "tools", root / "bin"),
    inspection=inspect_installation(
        root / "installation", app_id=identity.app_id
    ),
)
begin_operation(plan)

saved_directory = root / "saved-installation"
saved_directory.mkdir(mode=0o700)
config_root = root / "saved-config"
config_root.mkdir(mode=0o700)
(config_root / ".apprc-owner.json").write_text(
    json.dumps(
        {"schema_version": 1, "app_id": "saved-fixture", "category": "config"}
    ),
    encoding="utf-8",
)
secret = config_root / "apprc.user.secret.env"
secret.write_text("TOKEN=private\\n", encoding="utf-8")
unknown = config_root / "custom.ini"
unknown.write_text("retain me\\n", encoding="utf-8")
placement = InstallationPlacement(
    Layout.native(),
    config_dir=config_root,
    capabilities=frozenset({"config"}),
)
record = InstallationRecord(
    schema_version=2,
    app_id="saved-fixture",
    generation_id=uuid4(),
    support_version="1",
    placement=placement,
    status="removed-retained",
)
with installation_lock(saved_directory):
    write_record(saved_directory, record, expected_revision=None)
saved = inspect_installation(saved_directory, app_id=record.app_id)
inventory = default_cleanup_inventory(
    saved,
    categories=frozenset({"config"}),
    forget_retained=False,
)
observed = {
    "entries": sorted(entry.path.name for entry in inventory.entries),
    "retained": [entry.path.name for entry in inventory.retained],
    "unknown_contents": unknown.read_text(encoding="utf-8"),
}
assert observed["entries"] == [".apprc-owner.json", "apprc.user.secret.env"]
assert observed["retained"] == ["saved-config"]
assert observed["unknown_contents"] == "retain me\\n"
(root / "inventory.json").write_text(json.dumps(observed), encoding="utf-8")
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


def test_release_spec_accepts_empty_runtime_closure_but_not_blank_rows(
    tmp_path: Path,
) -> None:
    identity = InstallationIdentity(
        "dependency-free", "dependency-free", "fixture", None, ()
    )
    spec = DistributionSpec(
        ProjectMetadata(tmp_path, identity, "1.0.0"),
        source_mode="release",
        repository_url="https://github.com/example/dependency-free",
        release_version="1.0.0",
        release_commit="a" * 40,
        release_asset="https://github.com/example/dependency-free/archive.tar.gz",
        release_digest="b" * 64,
    )
    assert spec.runtime_requirements == ()
    with pytest.raises(ValueError, match="individual PEP 508"):
        replace(spec, runtime_requirements=(" ",))


@pytest.mark.parametrize("format", ("script", "zipapp"))
def test_emitted_composition_runs_without_installed_apprc_with_saved_inventory(
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
                "--with",
                "packaging==26.2",
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
    inventory = json.loads(
        (output / "inventory.json").read_text(encoding="utf-8")
    )
    assert inventory == {
        "entries": [".apprc-owner.json", "apprc.user.secret.env"],
        "retained": ["saved-config"],
        "unknown_contents": "retain me\n",
    }


def _write_invalid_interpreter(path: Path, marker: Path, prefix: Path) -> None:
    """Write a marker-producing wrapper that reports an in-target interpreter.

    :param path: Executable path of the shell wrapper.
    :param marker: Side-effect file proving that the wrapper ran.
    :param prefix: Application prefix reported as both live prefixes.
    """
    identity = json.dumps([str(prefix), str(prefix)])
    path.write_text(
        "#!/bin/sh\n"
        f"printf 'ran' > {shlex.quote(str(marker))}\n"
        f"printf '%s\\n' {shlex.quote(identity)}\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _saved_management_authority_fixture(
    tmp_path: Path, base_python: Path
) -> tuple[Path, Path, bytes, Path, Path]:
    """Create complete schema-2 authority and owned support for saved actions.

    :param tmp_path: Isolated test data root.
    :param base_python: Bound interpreter path stored in management.json.
    :return: Installation path, authority path/bytes, metadata path and app marker.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("Saved management consumer scenario requires uv.")

    payload = _standalone_payload(tmp_path / "payload")
    identity = InstallationIdentity(
        "generation-fixture",
        "generation-fixture",
        "fixture",
        None,
        ("fixture",),
    )
    spec = DistributionSpec(
        ProjectMetadata(tmp_path / "author", identity, "1.0"),
    )
    support_files = install_support_files(spec, payload)
    directory = tmp_path / "saved-installation"
    directory.mkdir()
    application_marker = tmp_path / "application-side-effect"
    application = tmp_path / "bin" / "fixture"
    application.parent.mkdir()
    application.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\n"
        f"Path({str(application_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    application.chmod(0o700)

    management_path = PurePosixPath("management.py")
    metadata_path = PurePosixPath("management.json")
    inspection_path = PurePosixPath("inspection.py")
    uninstall_path = PurePosixPath("app-uninstall.py")
    management = support_files[management_path]
    metadata = json.dumps(
        {
            "app_id": identity.app_id,
            "command": "fixture",
            "base_python": str(base_python),
        },
        sort_keys=True,
    ).encode()
    inspection = support_files[inspection_path]
    uninstall = support_files[uninstall_path]
    for relative, content in (
        (management_path, management),
        (metadata_path, metadata),
        (inspection_path, inspection),
        (uninstall_path, uninstall),
    ):
        (directory / relative.name).write_bytes(content)
    owned_outputs = tuple(
        OwnedOutput(
            "support", relative.as_posix(), hashlib.sha256(content).hexdigest()
        )
        for relative, content in (
            (management_path, management),
            (metadata_path, metadata),
            (inspection_path, inspection),
            (uninstall_path, uninstall),
        )
    )
    placement = InstallationPlacement(Layout.native())
    backend = UvToolTarget(
        Path(uv).resolve(), tmp_path / "tools", tmp_path / "bin"
    )
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    snapshot = InstalledSnapshot(
        identity,
        "1.0",
        InstallationSource("editable", "fixture"),
        placement,
        backend,
        prefix,
        Path(sys.executable),
        (application,),
        owned_outputs=owned_outputs,
    )
    record = InstallationRecord(
        schema_version=2,
        app_id=identity.app_id,
        generation_id=uuid4(),
        support_version="1",
        placement=placement,
        status="ready",
        current=snapshot,
        owned_outputs=owned_outputs,
    )
    authority = directory / "installation.json"
    authority_bytes = encode_record(record)
    authority.write_bytes(authority_bytes)
    return (
        directory,
        authority,
        authority_bytes,
        directory / metadata_path.name,
        application_marker,
    )


@pytest.mark.skipif(
    os.name == "nt", reason="Sentinel interpreters use a POSIX shell wrapper."
)
@pytest.mark.parametrize("schema_version", (1, 3, 2.0, "2"))
@pytest.mark.parametrize("action", ("launch", "uninstall"))
def test_saved_management_rejects_non_schema_two_authority_before_side_effects(
    tmp_path: Path, schema_version: int | float | str, action: str
) -> None:
    prefix = tmp_path / "prefix"
    interpreter_marker = tmp_path / "interpreter-side-effect"
    interpreter = tmp_path / "bound-interpreter"
    _write_invalid_interpreter(interpreter, interpreter_marker, prefix)
    (
        directory,
        authority,
        _,
        _metadata_path,
        application_marker,
    ) = _saved_management_authority_fixture(tmp_path, interpreter)
    record = json.loads(authority.read_bytes())
    record["schema_version"] = schema_version
    invalid_authority = json.dumps(record, sort_keys=True).encode()
    authority.write_bytes(invalid_authority)

    result = subprocess.run(
        [
            sys.executable,
            str(directory / "management.py"),
            action,
            "--directory",
            str(directory),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not interpreter_marker.exists()
    assert not application_marker.exists()
    assert authority.read_bytes() == invalid_authority


@pytest.mark.skipif(
    os.name == "nt", reason="Sentinel interpreters use a POSIX shell wrapper."
)
def test_tampered_bound_interpreter_is_rejected_before_interpreter_side_effect(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "prefix"
    authorized_marker = tmp_path / "authorized-interpreter-ran"
    authorized_interpreter = tmp_path / "authorized-interpreter"
    _write_invalid_interpreter(
        authorized_interpreter, authorized_marker, prefix
    )
    (
        directory,
        authority,
        authority_bytes,
        metadata_path,
        application_marker,
    ) = _saved_management_authority_fixture(tmp_path, authorized_interpreter)
    launch_control = subprocess.run(
        [
            sys.executable,
            str(directory / "management.py"),
            "launch",
            "--directory",
            str(directory),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert launch_control.returncode == 0
    assert application_marker.is_file()
    application_marker.unlink()

    control = subprocess.run(
        [
            sys.executable,
            str(directory / "management.py"),
            "uninstall",
            "--directory",
            str(directory),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert control.returncode != 0
    assert authorized_marker.is_file()
    assert not application_marker.exists()
    assert authority.read_bytes() == authority_bytes
    authorized_marker.unlink()

    tampered_marker = tmp_path / "tampered-interpreter-ran"
    tampered_interpreter = tmp_path / "tampered-interpreter"
    _write_invalid_interpreter(tampered_interpreter, tampered_marker, prefix)
    metadata = json.loads(metadata_path.read_bytes())
    metadata["base_python"] = str(tampered_interpreter)
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(directory / "management.py"),
            "uninstall",
            "--directory",
            str(directory),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert not tampered_marker.exists()
    assert not application_marker.exists()
    assert authority.read_bytes() == authority_bytes
