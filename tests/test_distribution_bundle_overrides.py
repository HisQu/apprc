"""Opt-in real uv proof of managed wheel-bundle installation."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from zipfile import ZipFile

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from tests.support_pyapp import pinned_uv

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationSource,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.distribution.models import BundledWheel
from apprc.distribution.runtime import installed_probe
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    SourceSelection,
    _sha256_file,
)
from apprc.distribution.runtime.backend import (
    inspect_uv_tools,
    remove_uv_tool,
    select_uv_target,
)
from apprc.distribution.runtime.bundles import prepare_wheel_bundle
from apprc.distribution.runtime.installation import install_application
from apprc.distribution.standalone import _deterministic_zip
from apprc.user_files.installation.operations import plan_install

pytestmark = pytest.mark.skipif(
    os.environ.get("APPRC_TEST_PYAPP") != "1",
    reason="real pinned-uv bundle proof requires APPRC_TEST_PYAPP=1",
)


_REPOSITORY = "https://bundled-repository.invalid/fixture/private"
_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_SUBDIRECTORY = "packages/private"
_PRIVATE = "apprc-bundle-private"
_EXTRA = "apprc-bundle-extra"
_WINDOWS = "apprc-bundle-windows"
_APPLICATION = "apprc-bundle-application"
_ORIGINAL = (
    f"{_PRIVATE}[feature] @ git+{_REPOSITORY}@{_COMMIT}"
    f"#subdirectory={_SUBDIRECTORY}"
)
_IDENTITY = InstallationIdentity(
    "bundle-proof", _APPLICATION, "bundle_application", None, (_APPLICATION,)
)


@dataclass(frozen=True, slots=True)
class BundleGraph:
    """One portable archive and its trusted build-time runtime graph."""

    root: Path
    archive: bytes
    inventory: tuple[BundledWheel, ...]
    runtime_requirements: tuple[str, ...]


_VERSIONS = {
    _APPLICATION: "1.0.0",
    _PRIVATE: "2.0.0",
    _EXTRA: "3.0.0",
    _WINDOWS: "4.0.0",
}
_MODULES = {
    _APPLICATION: "bundle_application",
    _PRIVATE: "bundle_private",
    _EXTRA: "bundle_extra",
    _WINDOWS: "bundle_windows",
}


def _run(
    argv: list[str], *, root: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run real tools with bounded failure output retained by pytest."""
    result = subprocess.run(
        argv,
        cwd=root,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"{argv!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _environment(root: Path, *, empty_path: bool = False) -> dict[str, str]:
    """Isolate fixture roots and discard ambient Python/uv source selection."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "PYTHON", "PIP_"))
        and key not in {"VIRTUAL_ENV", "CONDA_PREFIX"}
    }
    for key, relative in {
        "HOME": "home",
        "USERPROFILE": "home",
        "XDG_CONFIG_HOME": "config",
        "XDG_DATA_HOME": "data",
        "XDG_CACHE_HOME": "cache",
        "XDG_STATE_HOME": "state",
        "UV_TOOL_DIR": "tools",
        "UV_TOOL_BIN_DIR": "commands",
        "UV_CACHE_DIR": "uv-cache",
        "UV_PYTHON_INSTALL_DIR": "python",
    }.items():
        environment[key] = str(root / relative)
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    environment["UV_NO_PROGRESS"] = "1"
    if empty_path:
        empty = root / "empty-path"
        empty.mkdir(parents=True, exist_ok=True)
        environment["PATH"] = str(empty)
    return environment


def _write_project(root: Path, name: str) -> None:
    """Author tiny real setuptools projects; wheel metadata keeps the Git edge."""
    root.mkdir(parents=True)
    module = _MODULES[name]
    dependencies = [_ORIGINAL] if name == _APPLICATION else []
    optional_dependencies = (
        [
            f"{_EXTRA}=={_VERSIONS[_EXTRA]}",
            f"{_WINDOWS}=={_VERSIONS[_WINDOWS]}; sys_platform == 'win32'",
        ]
        if name == _PRIVATE
        else None
    )
    optional = (
        "\n[project.optional-dependencies]\n"
        f"feature = {json.dumps(optional_dependencies)}\n"
        if optional_dependencies is not None
        else ""
    )
    scripts = (
        f'\n[project.scripts]\n{_APPLICATION} = "{module}:main"\n'
        if name == _APPLICATION
        else ""
    )
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=80"]\n'
        'build-backend = "setuptools.build_meta"\n'
        f'[project]\nname = "{name}"\nversion = "{_VERSIONS[name]}"\n'
        'requires-python = ">=3.12"\n'
        f"dependencies = {json.dumps(dependencies)}\n"
        f"{optional}{scripts}\n[tool.setuptools]\n"
        f"py-modules = {json.dumps([module])}\n",
        encoding="utf-8",
    )
    implementation = 'MARKER = "selected private wheel"\n'
    if name == _EXTRA:
        implementation = 'MARKER = "extra-only wheel"\n'
    elif name == _WINDOWS:
        implementation = 'MARKER = "Windows-only wheel"\n'
    elif name == _APPLICATION:
        implementation = (
            "import importlib.metadata\nimport json\nimport sys\n"
            "import bundle_private\nimport bundle_extra\n"
            "def main():\n"
            "    print(json.dumps({\n"
            '        "private": bundle_private.MARKER,\n'
            '        "extra": bundle_extra.MARKER,\n'
            '        "argv": sys.argv[1:],\n'
            f'        "version": importlib.metadata.version("{name}"),\n'
            "    }))\n"
        )
    (root / f"{module}.py").write_text(implementation, encoding="utf-8")


def _entry_json(entry: BundledWheel) -> dict[str, object]:
    """Serialize portable payload facts, never private preparation paths."""
    return asdict(entry)


def _write_inventory(root: Path, entries: tuple[BundledWheel, ...]) -> None:
    (root / "inventory.json").write_text(
        json.dumps([_entry_json(entry) for entry in entries], indent=2) + "\n",
        encoding="utf-8",
    )


def _load_inventory(root: Path) -> tuple[BundledWheel, ...]:
    """Read build-authored inventory rows; production preparation validates them."""
    document = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    return tuple(BundledWheel(**item) for item in document)


def build_bundle_graph(root: Path, uv: Path) -> BundleGraph:
    """Build and export one real runtime graph for retained-payload composition.

    The exporter alone supplies local overrides. Application wheel metadata
    retains the unreachable immutable Git requirement. Requirements are lowered
    from uv's complete runtime export with packaging, not a fixture resolver.

    :param root: Fresh fixture-owned directory outside installation targets.
    :param uv: Absolute executable returned by support_pyapp.pinned_uv.
    :return: Portable archive plus build-side paths and inventory facts.
    """
    root.mkdir(parents=True)
    wheels = root / "payload"
    wheels.mkdir(mode=0o700)
    environment = _environment(root / "build-environment")
    entries: list[BundledWheel] = []
    for name, version in _VERSIONS.items():
        project = root / "projects" / name
        _write_project(project, name)
        _run(
            [
                str(uv),
                "build",
                "--wheel",
                "--no-sources",
                "--python",
                sys.executable,
                "--out-dir",
                str(wheels),
                str(project),
            ],
            root=root,
            environment=environment,
        )
        candidates = list(
            wheels.glob(f"{name.replace('-', '_')}-{version}-*.whl")
        )
        assert len(candidates) == 1
        wheel = candidates[0]
        entries.append(
            BundledWheel(
                name,
                version,
                wheel.name,
                _sha256_file(wheel),
                marker="sys_platform == 'win32'" if name == _WINDOWS else None,
                repository=_REPOSITORY if name == _PRIVATE else None,
                commit=_COMMIT if name == _PRIVATE else None,
                subdirectory=_SUBDIRECTORY if name == _PRIVATE else None,
                original_requirement=_ORIGINAL if name == _PRIVATE else None,
            )
        )
    _write_inventory(wheels, tuple(entries))
    inventory = _load_inventory(wheels)
    exporter = root / "exporter"
    exporter.mkdir()
    overrides = [
        f"{entry.name}{'[feature]' if entry.name == _PRIVATE else ''} @ "
        f"{(wheels / entry.filename).as_uri()}"
        + (f" ; {entry.marker}" if entry.marker else "")
        for entry in inventory
        if entry.name != _APPLICATION
    ]
    application = next(
        entry for entry in inventory if entry.name == _APPLICATION
    )
    (exporter / "pyproject.toml").write_text(
        '[project]\nname = "apprc-runtime-export-fixture"\n'
        'version = "1.0.0"\nrequires-python = ">=3.12"\n'
        f"dependencies = {json.dumps([f'{_APPLICATION} @ {(wheels / application.filename).as_uri()}'])}\n"
        f"[tool.uv]\noverride-dependencies = {json.dumps(overrides)}\n",
        encoding="utf-8",
    )
    _run(
        [str(uv), "lock", "--offline", "--python", sys.executable],
        root=exporter,
        environment=environment,
    )
    for format_name, filename in (
        ("requirements-txt", "runtime-export.txt"),
        ("pylock.toml", "pylock.runtime.toml"),
    ):
        arguments = [
            str(uv),
            "export",
            "--frozen",
            "--offline",
            "--no-dev",
            "--no-default-groups",
            "--no-emit-project",
            "--format",
            format_name,
            "--output-file",
            str(root / filename),
        ]
        if format_name == "requirements-txt":
            arguments.extend(("--no-hashes", "--no-header", "--no-annotate"))
        _run(arguments, root=exporter, environment=environment)
    graph = tomllib.loads(
        (root / "pylock.runtime.toml").read_text(encoding="utf-8")
    )
    requirements: list[str] = []
    names: set[str] = set()
    for package in graph["packages"]:
        name = canonicalize_name(package["name"])
        assert name in _VERSIONS, f"Unexpected runtime package: {name}"
        assert str(Version(package["version"])) == _VERSIONS[name]
        names.add(name)
        marker = f"; {package['marker']}" if package.get("marker") else ""
        requirement = Requirement(f"{name}=={package['version']}{marker}")
        requirements.append(str(requirement))
    assert names == set(_VERSIONS)
    runtime = tuple(requirements)
    (wheels / "runtime-requirements.txt").write_text(
        "".join(requirement + "\n" for requirement in runtime), encoding="utf-8"
    )
    payload_names = (
        *(entry.filename for entry in inventory),
        "inventory.json",
        "runtime-requirements.txt",
    )
    archive = _deterministic_zip(
        (name, (wheels / name).read_bytes()) for name in payload_names
    )
    return BundleGraph(wheels, archive, inventory, runtime)


def _prepare_bundle(
    graph: BundleGraph,
    staging: Path,
    payload_directory: Path | None = None,
) -> tuple[InstallationSource, PreparedSource]:
    """Use production acquisition and bundle preparation from trusted graph facts."""
    root_entry = next(
        entry for entry in graph.inventory if entry.name == _APPLICATION
    )
    source = InstallationSource(
        "wheel",
        f"https://bundle-fixture.invalid/{root_entry.filename}",
        version=root_entry.version,
        digest=root_entry.digest,
        runtime_requirements=graph.runtime_requirements,
    )
    prepared = SourceSelection(
        source, package_path=graph.root / root_entry.filename
    ).prepare(staging)
    bundle = prepare_wheel_bundle(
        payload_directory or graph.root,
        staging,
        source=source,
        distribution=_APPLICATION,
    )
    return source, replace(prepared, bundle=bundle)


def _source_for_graph(graph: BundleGraph) -> InstallationSource:
    root = next(
        entry for entry in graph.inventory if entry.name == _APPLICATION
    )
    return InstallationSource(
        "wheel",
        f"https://bundle-fixture.invalid/{root.filename}",
        version=root.version,
        digest=root.digest,
        runtime_requirements=graph.runtime_requirements,
    )


def _externalize_extra_wheel(
    graph: BundleGraph, payload: Path, flat_index: Path
) -> None:
    """Leave one selected runtime wheel for uv to obtain from a flat index."""
    shutil.copytree(graph.root, payload)
    extra = next(entry for entry in graph.inventory if entry.name == _EXTRA)
    (payload / extra.filename).unlink()
    _write_inventory(
        payload,
        tuple(entry for entry in graph.inventory if entry.name != _EXTRA),
    )
    flat_index.mkdir()
    shutil.copyfile(graph.root / extra.filename, flat_index / extra.filename)


def _install_bundle(
    graph: BundleGraph,
    staging: Path,
    target: UvToolTarget,
    environment: Mapping[str, str],
    directory: Path,
    *,
    payload_directory: Path | None = None,
) -> tuple[InstallationInspection, PreparedSource, InstallationSource]:
    """Install verified graph inputs through the managed lifecycle API."""
    from apprc.user_files.installation.discovery import inspect_installation

    source, prepared = _prepare_bundle(
        graph, staging, payload_directory=payload_directory
    )
    placement = InstallationPlacement(Layout.native())
    inspection = inspect_installation(directory, app_id=_IDENTITY.app_id)
    plan = plan_install(
        _IDENTITY, source, placement, target, inspection=inspection
    )
    installed = install_application(
        plan,
        environment={**environment, "UV_OFFLINE": "1"},
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files={},
        python_requirement=sys.executable,
        prepared_source=prepared,
    )
    return installed, prepared, source


@pytest.fixture(scope="module")
def bundle_graph(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> tuple[BundleGraph, Path]:
    """Keep real builds serial and entirely behind the module's explicit opt-in."""
    if request.config.getoption("numprocesses", default=0) not in (
        0,
        None,
        "0",
    ):
        pytest.fail("Run the opted-in bundle proof serially with pytest -n 0")
    if sys.platform != "linux":
        pytest.skip("Native Windows/macOS execution is explicitly deferred")
    root = tmp_path_factory.mktemp("real bundle graph ü %2F")
    uv = pinned_uv(root / "pinned-tool")
    return build_bundle_graph(root / "build", uv), uv


@pytest.mark.parametrize(
    "external_extra",
    (False, True),
    ids=("bundled-extra", "external-flat-index-extra"),
)
def test_real_override_installs_complete_runtime_graph_without_repository_tools(
    bundle_graph: tuple[BundleGraph, Path],
    tmp_path: Path,
    external_extra: bool,
) -> None:
    graph, uv = bundle_graph
    environment = _environment(tmp_path / "recipient", empty_path=True)
    payload_directory: Path | None = None
    if external_extra:
        payload_directory = tmp_path / "bundle payload"
        flat_index = tmp_path / "flat wheel index"
        _externalize_extra_wheel(graph, payload_directory, flat_index)
        environment["UV_FIND_LINKS"] = str(flat_index)
    for command in ("python", "python3", "uv", "git", "gh"):
        assert shutil.which(command, path=environment["PATH"]) is None
    target = select_uv_target(
        uv, environment=environment, invocation_cwd=tmp_path
    )
    assert _APPLICATION not in inspect_uv_tools(target, environment=environment)
    try:
        installed, prepared, source = _install_bundle(
            graph,
            tmp_path / "private staging",
            target,
            environment,
            tmp_path / "installation",
            payload_directory=payload_directory,
        )
        assert (
            installed.record is not None
            and installed.record.current is not None
        )
        snapshot = installed.record.current
        result = _run(
            [str(snapshot.commands[0]), "space argument", "ü", "--literal"],
            root=tmp_path,
            environment=environment,
        )
        assert json.loads(result.stdout) == {
            "private": "selected private wheel",
            "extra": "extra-only wheel",
            "version": "1.0.0",
            "argv": ["space argument", "ü", "--literal"],
        }
        assert snapshot.source.kind == "wheel"
        assert snapshot.source.digest == source.digest
        windows = next(
            Requirement(line)
            for line in graph.runtime_requirements
            if canonicalize_name(Requirement(line).name) == _WINDOWS
        )
        assert windows.marker is not None
        assert windows.marker.evaluate({"sys_platform": "win32"})
        assert not windows.marker.evaluate({"sys_platform": "linux"})
        interpreter = snapshot.prefix / "bin" / "python"
        inactive = _run(
            [
                str(interpreter),
                "-I",
                "-c",
                "import importlib.util; "
                "assert importlib.util.find_spec('bundle_windows') is None",
            ],
            root=tmp_path,
            environment=environment,
        )
        assert inactive.returncode == 0
        private = next(
            entry for entry in graph.inventory if entry.name == _PRIVATE
        )
        assert private.original_requirement == _ORIGINAL
        assert private.commit == _COMMIT
        assert prepared.constraints is not None
        assert prepared.constraints.read_text(encoding="utf-8") == "".join(
            requirement + "\n" for requirement in source.runtime_requirements
        )
        with ZipFile(io.BytesIO(graph.archive)) as archive:
            assert set(archive.namelist()) == {
                "inventory.json",
                "runtime-requirements.txt",
                *(entry.filename for entry in graph.inventory),
            }
            assert b"file://" not in archive.read("runtime-requirements.txt")
    finally:
        remove_uv_tool(target, _APPLICATION, environment=environment)


@pytest.mark.parametrize(
    "failure",
    [
        "digest",
        "wheel-name",
        "wheel-version",
        "wheel-tag",
        "metadata-name",
        "metadata-version",
        "selector",
        "credential-selector",
        "subdirectory",
        "absolute-subdirectory",
        "mutable-commit",
        "filename-traversal",
        "missing-extra",
        "missing-windows-marker",
    ],
)
def test_invalid_bundle_refuses_before_backend_or_installation_mutation(
    bundle_graph: tuple[BundleGraph, Path],
    tmp_path: Path,
    failure: str,
) -> None:
    graph, uv = bundle_graph
    payload = tmp_path / "payload"
    shutil.copytree(graph.root, payload)
    entries = list(graph.inventory)
    index = next(i for i, entry in enumerate(entries) if entry.name == _PRIVATE)
    entry = entries[index]
    wheel = payload / entry.filename
    if failure == "digest":
        wheel.write_bytes(wheel.read_bytes() + b"modified wheel")
    elif failure in {"wheel-name", "wheel-version", "wheel-tag"}:
        filename = {
            "wheel-name": "different_package-2.0.0-py3-none-any.whl",
            "wheel-version": "apprc_bundle_private-9.0.0-py3-none-any.whl",
            "wheel-tag": "apprc_bundle_private-2.0.0-cp38-cp38-win_amd64.whl",
        }[failure]
        wheel.rename(payload / filename)
        entries[index] = replace(entry, filename=filename)
    elif failure in {"metadata-name", "metadata-version"}:
        with ZipFile(wheel) as source:
            members = [
                (item.filename, source.read(item)) for item in source.infolist()
            ]
        with ZipFile(wheel, "w") as destination:
            for name, content in members:
                if name.endswith(".dist-info/METADATA"):
                    content = content.replace(
                        b"Name: apprc-bundle-private"
                        if failure == "metadata-name"
                        else b"Version: 2.0.0",
                        b"Name: other-package"
                        if failure == "metadata-name"
                        else b"Version: 9.0.0",
                    )
                destination.writestr(name, content)
        entries[index] = replace(entry, digest=_sha256_file(wheel))
    elif failure in {"selector", "credential-selector"}:
        entries[index] = replace(
            entry,
            repository=(
                "https://unselected.invalid/private.git"
                if failure == "selector"
                else "https://user:secret@bundled-repository.invalid/fixture/private.git"
            ),
        )
    elif failure in {"subdirectory", "absolute-subdirectory"}:
        entries[index] = replace(
            entry,
            subdirectory=(
                "../private" if failure == "subdirectory" else "/private"
            ),
        )
    elif failure == "mutable-commit":
        entries[index] = replace(entry, commit="main")
    elif failure == "filename-traversal":
        entries[index] = replace(entry, filename="../outside.whl")
    else:
        runtime = [Requirement(line) for line in graph.runtime_requirements]
        if failure == "missing-extra":
            runtime = [item for item in runtime if item.name != _EXTRA]
        else:
            for item in runtime:
                if item.name == _WINDOWS:
                    item.marker = None
        (payload / "runtime-requirements.txt").write_text(
            "".join(str(item) + "\n" for item in runtime), encoding="utf-8"
        )
    _write_inventory(payload, tuple(entries))
    target = UvToolTarget(
        uv, tmp_path / "recipient/tools", tmp_path / "recipient/commands"
    )
    sentinel = tmp_path / "installation" / "user-file"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"preserve existing installation bytes")
    with pytest.raises(InstallationError):
        prepare_wheel_bundle(
            payload,
            tmp_path / "private staging",
            source=_source_for_graph(graph),
            distribution=_APPLICATION,
        )
    assert sentinel.read_bytes() == b"preserve existing installation bytes"
    assert set(sentinel.parent.iterdir()) == {sentinel}
    assert not target.tool_dir.exists()
    assert not target.bin_dir.exists()
