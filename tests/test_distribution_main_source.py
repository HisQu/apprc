"""Install pre-acquired immutable-main archives through the actual uv consumer."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import replace
from io import BytesIO, StringIO
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime import (
    SourceSelection,
    install_prepared_application,
    plan_install,
    plan_repair,
)
from apprc.distribution.runtime import installed_probe
from apprc.distribution.runtime.backend import (
    backend_environment,
    inspect_uv_tools,
    install_uv_tool,
    remove_uv_tool,
    select_uv_target,
)
import apprc.distribution.runtime.installation as lifecycle_installation
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.discovery import inspect_installation


_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_DISTRIBUTION = "apprc-main-archive-fixture"
_MODULE = "main_archive_fixture"
_VERSION = "2.3.4"


def _write_project(
    archive: ZipFile,
    project: str,
    version: str,
    marker: str = "original",
) -> None:
    """Add a package whose installed command exposes its archive contents.

    :param archive: Owned fixture archive receiving the application files.
    :param project: Archive-relative project directory, including its wrapper.
    :param version: Distinguish the intended project from a decoy root.
    :param marker: Identify a same-version package replacement.
    """
    archive.writestr(
        f"{project}/pyproject.toml",
        f"""[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "{_DISTRIBUTION}"
version = "{version}"
requires-python = ">=3.12"
[project.scripts]
{_DISTRIBUTION} = "{_MODULE}:main"
[tool.setuptools]
py-modules = ["{_MODULE}"]
""",
    )
    archive.writestr(
        f"{project}/{_MODULE}.py",
        "import importlib.metadata\n"
        "import importlib.util\n"
        "import json\n"
        "import sys\n"
        "\n"
        "def main():\n"
        f"    distribution = importlib.metadata.distribution({_DISTRIBUTION!r})\n"
        "    print(json.dumps({\n"
        '        "distribution": distribution.metadata["Name"],\n'
        '        "version": distribution.version,\n'
        '        "entry_points": {entry.name: entry.value for entry in distribution.entry_points\n'
        '                         if entry.group == "console_scripts"},\n'
        '        "module": __file__,\n'
        '        "prefix": sys.prefix,\n'
        '        "argv": sys.argv[1:],\n'
        '        "apprc_available": importlib.util.find_spec("apprc") is not None,\n'
        f'        "archive_marker": {marker!r},\n'
        "    }))\n",
    )
    archive.writestr(
        f"{project}/PKG-INFO",
        f"Metadata-Version: 2.1\nName: {_DISTRIBUTION}\nVersion: {version}\n",
    )
    egg_info = _DISTRIBUTION.replace("-", "_") + ".egg-info"
    archive.writestr(
        f"{project}/{egg_info}/PKG-INFO",
        f"Metadata-Version: 2.1\nName: {_DISTRIBUTION}\nVersion: {version}\n",
    )
    archive.writestr(
        f"{project}/{egg_info}/SOURCES.txt",
        f"{_MODULE}.py\npyproject.toml\n",
    )


def _write_fixture_wheel(
    package: Path, wheel_path: Path, *, marker: str
) -> None:
    """Write a wheel whose console command reports its installed origin.

    :param package: Source archive supplying the package module.
    :param wheel_path: Destination for the standards-shaped wheel.
    :param marker: Consumer-visible marker for replacement detection.
    """
    with ZipFile(package) as source:
        module = next(
            source.read(name)
            for name in source.namelist()
            if name.endswith(f"/{_MODULE}.py")
        )
    dist_info = f"{_DISTRIBUTION.replace('-', '_')}-{_VERSION}.dist-info"
    files = {
        f"{_MODULE}.py": module.replace(b"'original'", repr(marker).encode()),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {_DISTRIBUTION}\n"
            f"Version: {_VERSION}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode(),
        f"{dist_info}/entry_points.txt": (
            f"[console_scripts]\n{_DISTRIBUTION} = {_MODULE}:main\n"
        ).encode(),
    }
    rows = []
    for name, content in files.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        rows.append((name, f"sha256={digest}", str(len(content))))
    rows.append((f"{dist_info}/RECORD", "", ""))
    record = StringIO()
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    with ZipFile(wheel_path, "w") as wheel:
        for name, content in files.items():
            wheel.writestr(name, content)


def _zip_as_sdist(package_path: Path, archive_path: Path) -> None:
    """Convert the fixture tree to a real gzip-compressed tar sdist."""
    with (
        ZipFile(package_path) as package,
        tarfile.open(archive_path, "w:gz") as archive,
    ):
        for member in package.infolist():
            info = tarfile.TarInfo(member.filename)
            if member.is_dir():
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                content = package.read(member)
                info.size = len(content)
                archive.addfile(info, BytesIO(content))
    package_path.unlink()


@pytest.mark.parametrize(
    ("source_kind", "subdirectory"),
    (
        ("index", None),
        ("index", "projects/consumer"),
        ("release-sdist", None),
        ("wheel", None),
    ),
)
def test_preacquired_main_archive_installs_selected_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: Literal["index", "release-sdist", "wheel"],
    subdirectory: str | None,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    private_home = tmp_path / "test home ü %2F"
    create_private_directory_if_missing(private_home)
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.setenv("USERPROFILE", str(private_home))
    # > Keep the content-addressed URL path covered by native path encoding.
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
        directory = tmp_path / name
        create_private_directory_if_missing(directory)
        monkeypatch.setenv(variable, str(directory))
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)
    # > Python may already have cached a system temp directory before this test.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temporary"))
    # > Native Windows runs must not publish or inspect real HKCU registration.
    monkeypatch.setattr(
        lifecycle_installation,
        "_register_windows",
        lambda *args, **kwargs: None,
    )
    environment = dict(os.environ)
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    identity = InstallationIdentity(
        "main-archive-fixture",
        _DISTRIBUTION,
        _MODULE,
        None,
        (_DISTRIBUTION,),
    )
    wrapper = f"main-archive-fixture-{_COMMIT}"
    package_directory = tmp_path / "acquired package ü %2F with spaces"
    create_private_directory_if_missing(package_directory)
    fixture_zip = package_directory / "immutable main ü with spaces.zip"
    with ZipFile(fixture_zip, "w") as archive:
        if subdirectory is not None:
            _write_project(archive, wrapper, "0.0.1")
        project = (
            wrapper if subdirectory is None else f"{wrapper}/{subdirectory}"
        )
        _write_project(archive, project, _VERSION)
    package_path = fixture_zip
    if source_kind == "release-sdist":
        package_path = package_directory / "release main ü with spaces.tar.gz"
        _zip_as_sdist(fixture_zip, package_path)
    elif source_kind == "wheel":
        package_path = package_directory / (
            f"{_DISTRIBUTION.replace('-', '_')}-{_VERSION}-py3-none-any.whl"
        )
        _write_fixture_wheel(fixture_zip, package_path, marker="original")
    requirement = (
        f"git+https://github.com/example/main-archive-fixture.git@{_COMMIT}"
    )
    if subdirectory is not None:
        requirement += f"#subdirectory={subdirectory}"
    digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
    if source_kind == "index":
        source = InstallationSource("index", requirement)
    elif source_kind == "wheel":
        source = InstallationSource(
            "wheel", str(package_path), version=_VERSION, digest=digest
        )
    else:
        source = InstallationSource(
            "release-sdist",
            str(package_path),
            version=_VERSION,
            digest=digest,
            runtime_requirements=("setuptools>=80",),
        )
    selection = SourceSelection(
        source,
        package_path=package_path,
        subdirectory=subdirectory,
    )
    staging = tmp_path / "prepared source"
    create_private_directory_if_missing(staging)
    prepared = selection.prepare(staging)
    assert prepared.source == selection.source
    assert (
        prepared.digest == hashlib.sha256(package_path.read_bytes()).hexdigest()
    )
    installation_directory = tmp_path / "installation metadata"
    plan = plan_install(
        identity,
        selection.source,
        InstallationPlacement(Layout.native()),
        target,
        inspection=inspect_installation(
            installation_directory, app_id=identity.app_id
        ),
    )
    if subdirectory is not None:
        assert prepared.source_root is not None
        forged = replace(
            prepared,
            requirement=str(prepared.source_root),
            project_directory=prepared.source_root,
        )
        with pytest.raises(InstallationError, match="content-addressed"):
            lifecycle_installation._validate_prepared_source(plan, forged)
    try:
        installed = install_prepared_application(
            plan,
            prepared,
            environment=environment,
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files={},
            python_requirement=sys.executable,
        )
        assert installed.status == "ready"
        record = installed.record
        assert record is not None
        assert record.operation is None
        snapshot = record.current
        assert snapshot is not None
        assert snapshot.identity == identity
        assert snapshot.version == _VERSION
        assert selection.source.matches_observation(snapshot.source)
        assert snapshot.source.requirement == selection.source.requirement
        assert snapshot.source.digest == prepared.digest
        assert snapshot.backend == target
        assert snapshot.prefix == target.tool_dir / _DISTRIBUTION
        assert len(snapshot.commands) == 1
        command = subprocess.run(
            [str(snapshot.commands[0]), "argument ü with spaces"],
            cwd=tmp_path,
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        observed = json.loads(command.stdout)
        assert observed["distribution"] == _DISTRIBUTION
        assert observed["version"] == _VERSION
        assert observed["entry_points"] == {_DISTRIBUTION: f"{_MODULE}:main"}
        assert observed["argv"] == ["argument ü with spaces"]
        assert Path(observed["prefix"]) == snapshot.prefix
        assert Path(observed["module"]).is_relative_to(snapshot.prefix)
        assert observed["apprc_available"] is False
        assert observed["archive_marker"] == "original"
        saved = inspect_installation(
            installation_directory, app_id=identity.app_id
        )
        assert saved.status == "ready"
        assert saved.record == record
        assert _DISTRIBUTION in inspect_uv_tools(
            target, environment=environment
        )
        repair_plan = plan_repair(
            identity,
            selection.source,
            InstallationPlacement(Layout.native()),
            target,
            inspection=saved,
        )
        assert repair_plan.target.source.digest == prepared.digest
        lifecycle_installation._validate_prepared_source(repair_plan, prepared)
        assert prepared.source_root is not None
        shutil.rmtree(prepared.source_root)
        shutil.rmtree(staging)
        package_path.unlink()
        persisted_proof = lifecycle_installation.probe_installed_tool(
            target,
            identity,
            snapshot.source,
            InstallationPlacement(Layout.native()),
            probe_path=Path(installed_probe.__file__).absolute(),
            environment=environment,
            expected_record_digest=snapshot.distribution_record_digest,
        )
        assert persisted_proof.source == snapshot.source
        replacement_zip = package_directory / "replacement archive.zip"
        with ZipFile(replacement_zip, "w") as archive:
            if subdirectory is not None:
                _write_project(archive, wrapper, "0.0.1")
            _write_project(archive, project, _VERSION, "replacement")
        replacement_path = replacement_zip
        if source_kind == "release-sdist":
            replacement_path = package_directory / "replacement archive.tar.gz"
            _zip_as_sdist(replacement_zip, replacement_path)
        elif source_kind == "wheel":
            replacement_path = package_directory / (
                f"{_DISTRIBUTION.replace('-', '_')}-{_VERSION}-py3-none-any.whl"
            )
            _write_fixture_wheel(
                replacement_zip, replacement_path, marker="replacement"
            )
        replacement_source = (
            replace(
                selection.source,
                digest=hashlib.sha256(
                    replacement_path.read_bytes()
                ).hexdigest(),
            )
            if source_kind in {"release-sdist", "wheel"}
            else selection.source
        )
        replacement = SourceSelection(
            replacement_source,
            package_path=replacement_path,
            subdirectory=subdirectory,
        ).prepare(tmp_path / "replacement staging")
        assert replacement.digest is not None
        assert replacement.source_root is not None
        if source_kind == "wheel":
            assert replacement.source_root != prepared.source_root
        else:
            assert replacement.project_directory != prepared.project_directory
        create_private_directory_if_missing(prepared.source_root.parent)
        shutil.copytree(replacement.source_root, prepared.source_root)
        install_uv_tool(
            target,
            InstallationSource("index", prepared.requirement),
            environment=environment,
            python_requirement=sys.executable,
        )
        with pytest.raises(ValueError, match="RECORD digest differs"):
            lifecycle_installation.probe_installed_tool(
                target,
                identity,
                snapshot.source,
                InstallationPlacement(Layout.native()),
                probe_path=Path(installed_probe.__file__).absolute(),
                environment=environment,
                expected_record_digest=snapshot.distribution_record_digest,
            )
        with pytest.raises(
            ValueError,
            match="Saved (main|release) source lacks its installed RECORD fingerprint|Installed wheel lacks saved source proof",
        ):
            lifecycle_installation.probe_installed_tool(
                target,
                identity,
                snapshot.source,
                InstallationPlacement(Layout.native()),
                probe_path=Path(installed_probe.__file__).absolute(),
                environment=environment,
            )
        replaced = subprocess.run(
            [str(snapshot.commands[0])],
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(replaced.stdout)["archive_marker"] == "replacement"
    except InstallationError as error:
        for metadata in target.tool_dir.rglob("direct_url.json"):
            error.add_note(
                f"Installed source metadata: {metadata.read_text(encoding='utf-8')}"
            )
        raise
    finally:
        remove_uv_tool(target, _DISTRIBUTION, environment=environment)
