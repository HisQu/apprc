"""Opt-in native feasibility construction; never imported by production code."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import venv
from collections.abc import Sequence
from pathlib import Path

import pytest

from apprc.distribution import (
    DistributionSpec,
    build_native_distribution,
    build_project_snapshot,
    read_distribution_spec,
)
from apprc.distribution.native import NativeFrontendBuilder, UV_VERSION
from apprc.distribution.project import PreparedProject

# > Pytest sandboxes HOME per test; native authoring must keep the host Rustup,
# > Cargo and cargo-xwin caches captured during collection.
_AUTHORING_ENVIRONMENT = dict(os.environ)

_LOG = logging.getLogger(__name__)


def require_opt_in() -> None:
    """Reject accidental direct construction without the explicit native opt-in."""
    if os.environ.get("APPRC_TEST_PYAPP") != "1":
        raise RuntimeError("Native feasibility requires APPRC_TEST_PYAPP=1.")


def run(
    argv: Sequence[str],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Capture bounded fixture commands and retain useful failure diagnostics."""
    _LOG.info("Running %s", argv)
    result = subprocess.run(
        argv,
        env=environment,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=1800,
    )
    if check and result.returncode:
        raise AssertionError(f"{argv!r}\n{result.stdout}\n{result.stderr}")
    return result


def pinned_uv(root: Path) -> Path:
    """Create or reuse only this fixture's environment containing exact uv 0.13.6.

    :param root: Fixture-owned storage, separate from the PyApp runtime.
    :return: Absolute uv executable, with both package and binary version checked.
    """
    require_opt_in()
    root = root.absolute()
    if root.is_symlink():
        raise FileExistsError(f"Fixture uv root must not be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)
    environment_root = root / f"uv-{UV_VERSION}"
    marker = root / "pinned-uv.json"
    expected = {"version": UV_VERSION, "environment": environment_root.name}
    if environment_root.is_symlink() or marker.is_symlink():
        raise FileExistsError("Fixture uv state must not contain symlinks.")
    if environment_root.exists():
        if (
            not environment_root.is_dir()
            or not marker.is_file()
            or json.loads(marker.read_text()) != expected
        ):
            raise FileExistsError(
                f"Unexpected fixture uv environment: {environment_root}"
            )
    else:
        if marker.exists():
            raise FileExistsError(f"Unexpected fixture uv marker: {marker}")
        venv.EnvBuilder(with_pip=True).create(environment_root)
        python = environment_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                f"uv=={UV_VERSION}",
            ]
        )
        marker.write_text(json.dumps(expected), encoding="utf-8")
    python = environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    executable = environment_root / (
        "Scripts/uv.exe" if os.name == "nt" else "bin/uv"
    )
    version = run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('uv'))",
        ]
    )
    assert version.stdout.strip() == UV_VERSION
    assert run([str(executable), "--version"]).stdout.split()[:2] == [
        "uv",
        UV_VERSION,
    ]
    return executable.absolute()


def authoring_environment() -> dict[str, str]:
    """Return captured Rust/Cargo settings without pytest's sandbox HOME."""
    return dict(_AUTHORING_ENVIRONMENT)


def authoring_git_environment(
    repository: Path, canonical_url: str
) -> dict[str, str]:
    """Add a fixture-only Git URL rewrite while preserving inherited config.

    :param repository: Local committed checkout supplying immutable Git objects.
    :param canonical_url: Public dependency URL recorded in project metadata.
    :return: Authoring environment with an additional local rewrite entry.
    """
    environment = authoring_environment()
    count = int(environment.get("GIT_CONFIG_COUNT", "0"))
    environment.update(
        {
            f"GIT_CONFIG_KEY_{count}": f"url.file://{repository.resolve()}.insteadOf",
            f"GIT_CONFIG_VALUE_{count}": canonical_url,
            "GIT_CONFIG_COUNT": str(count + 1),
        }
    )
    return environment


def native_builder(
    workspace: Path,
    *,
    pip_extra_args: str = "",
    bootstrap_name: str = "fixture-app-bootstrap",
) -> NativeFrontendBuilder:
    """Create the fixture's production builder with the host authoring environment.

    :param workspace: New operation-owned build directory.
    :param pip_extra_args: Static local recovery-download settings, if needed.
    :param bootstrap_name: Bootstrap namespace shared by related native frontends.
    :return: Builder using the captured authoring environment.
    """
    return NativeFrontendBuilder(
        workspace,
        bootstrap_name=bootstrap_name,
        pip_extra_args=pip_extra_args,
        environment=authoring_environment(),
    )


def isolated_environment(
    root: Path,
    *,
    bootstrap_name: str = "fixture-app-bootstrap",
) -> dict[str, str]:
    """Isolate native state and remove ambient Python, uv, pip and PyApp selectors.

    :param root: Private fixture-owned runtime state root.
    :param bootstrap_name: Exact PyApp bootstrap namespace used by the frontend.
    :return: Environment with isolated locations and no inherited selectors.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            (
                "UV_",
                "PYTHON",
                "PYAPP",
                "PIP_",
                "CONDA",
                "VIRTUAL_ENV",
                "APPRC_FIXTURE_",
            )
        )
    }
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    locations = {
        "HOME": "home",
        "USERPROFILE": "home",
        "LOCALAPPDATA": "local",
        "APPDATA": "roaming",
        "XDG_DATA_HOME": "data",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_STATE_HOME": "state",
        "UV_TOOL_DIR": "tools",
        "UV_TOOL_BIN_DIR": "commands",
        "UV_CACHE_DIR": "uv-cache",
        "UV_PYTHON_INSTALL_DIR": "python",
        "UV_PYTHON_BIN_DIR": "python-bin",
        "UV_CONFIG_DIR": "uv-config",
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
        f"PYAPP_INSTALL_DIR_{bootstrap_name.upper()}": "bootstrap",
        "PATH": "empty-path",
    }
    for key, relative in locations.items():
        path = root / relative
        if relative != "bootstrap":
            path.mkdir(exist_ok=True, mode=0o700)
        environment[key] = str(path)
    environment.update(
        UV_NO_CONFIG="1", PYTHONNOUSERSITE="1", APPRC_FIXTURE_ROOT=str(root)
    )
    return environment


@pytest.fixture(scope="session")
def native_product(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, Path, Path, DistributionSpec, PreparedProject]:
    """Build A and B native products from one current-SDK fixture.

    :param tmp_path_factory: Pytest's session-owned isolated workspace factory.
    :return: A's project, manager uv, Linux setup, checksums, spec and snapshot.
    """
    require_opt_in()
    base = tmp_path_factory.mktemp("native-project")
    project_root = base / "fixture"
    project_root.mkdir()
    vendor = project_root / "vendor"
    vendor.mkdir()
    uv = pinned_uv(base / "tooling")
    build_environment = authoring_environment()
    repository = Path(__file__).resolve().parents[1]
    run(
        [str(uv), "build", "--wheel", "--out-dir", str(vendor)],
        environment=build_environment,
        cwd=repository,
    )
    run(
        [
            str(uv), "build", "--wheel", "--out-dir", str(vendor),
        ],
        environment=build_environment,
        cwd=repository / "src" / "apprc_dev" / "packaging" / "terminal",
    )
    core_wheel = next(vendor.glob("apprc_core-*.whl")).name
    terminal_wheel = next(vendor.glob("apprc-*.whl")).name
    (project_root / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['setuptools>=80']\n"
        "build-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'fixture-app'\nversion = '1.0.0'\n"
        f"requires-python = '>=3.12'\ndependencies = ['apprc-core==0.34.0', 'apprc==0.34.0']\n"
        "[project.optional-dependencies]\nnative-feature = ['fixture-feature-dependency==1.0.0']\n"
        "[dependency-groups]\ndev = ['fixture-dev-dependency==1.0.0']\n"
        "[tool.uv.sources]\n"
        f"apprc-core = {{ path = 'vendor/{core_wheel}' }}\n"
        f"apprc = {{ path = 'vendor/{terminal_wheel}' }}\n"
        "fixture-feature-dependency = { path = 'feature-dependency' }\n"
        "fixture-dev-dependency = { path = 'dev-dependency' }\n"
        "[project.scripts]\nfixture-app = 'fixture_app:main'\n"
        "[tool.apprc.distribution]\napp-id = 'fixture-app'\n"
        "import-package = 'fixture_app'\ncommand-name = 'fixture-app'\n"
        "apprc-reference = 'fixture_config:APP_RC'\n"
        "runtime-python = '3.14'\nconfig = true\n"
        "[tool.apprc.distribution.hooks]\n"
        "initialize = 'fixture_app:initialize'\n"
        "inventory = 'fixture_app:inventory'\n"
        "cleanup = 'fixture_app:cleanup'\n"
        "[tool.setuptools]\npy-modules = ['fixture_app', 'fixture_config']\n",
        encoding="utf-8",
    )
    for dependency, name in (
        ("feature-dependency", "fixture-feature-dependency"),
        ("dev-dependency", "fixture-dev-dependency"),
    ):
        dependency_root = project_root / dependency
        dependency_root.mkdir()
        (dependency_root / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools>=80']\n"
            "build-backend = 'setuptools.build_meta'\n"
            f"[project]\nname = '{name}'\nversion = '1.0.0'\n"
            "requires-python = '>=3.12'\n"
            "[tool.setuptools]\npy-modules = []\n",
            encoding="utf-8",
        )
    (project_root / "fixture_app.py").write_text(
        "import json, os, platform, sys, time\n"
        "from pathlib import Path\n"
        "from importlib.metadata import PackageNotFoundError, distribution, version\n"
        "import typer\n"
        "from apprc.definition.installation import InstallationHooks\n"
        "from apprc.interfaces.cli.context import CliRuntimeOptions\n"
        "from apprc.interfaces.cli.runtime import CliRuntime\n"
        "from fixture_config import APP_RC\n"
        "cli = typer.Typer()\n"
        "runtime = CliRuntime(APP_RC)\n"
        "@cli.callback()\n"
        "def callback(ctx: typer.Context):\n"
        " runtime.prepare(ctx, CliRuntimeOptions())\n"
        "def package_version(name):\n"
        " try: return version(name)\n"
        " except PackageNotFoundError: return None\n"
        "@cli.command()\n"
        "def inspect(value: str = '', fail: bool = False):\n"
        " if fail: raise typer.Exit(code=23)\n"
        " resolved_paths = APP_RC.paths()\n"
        " declared_paths = APP_RC.schema.paths\n"
        " observed_distribution = distribution('fixture-app')\n"
        " commands = sorted(entry.name for entry in observed_distribution.entry_points "
        "if entry.group == 'console_scripts')\n"
        " path_names = ('config', 'appdata', 'cache', 'state')\n"
        " print(json.dumps({'marker': 'committed-source', 'version': "
        "observed_distribution.version, 'distribution': observed_distribution.metadata['Name'], "
        "'python_version': platform.python_version(), "
        "'interpreter': sys.executable, 'prefix': sys.prefix, "
        "'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'environment': os.environ.get('FIXTURE_SENTINEL'), "
        "'feature_version': package_version('fixture-feature-dependency'), "
        "'dev_version': package_version('fixture-dev-dependency'), "
        "'commands': commands, "
        "'capabilities': {name: getattr(declared_paths, name) "
        "for name in path_names}, "
        "'paths': {name: (str(getattr(resolved_paths, name + '_dir')) "
        "if getattr(resolved_paths, name + '_dir') is not None else None) "
        "for name in path_names}}))\n"
        "@cli.command()\n"
        "def hold(marker: Path = typer.Argument(...)):\n"
        " marker.write_text(json.dumps({'process': os.getpid(), 'forwarder': os.getppid()}), encoding='utf-8')\n"
        " print('ready', flush=True)\n"
        " request = sys.stdin.buffer.readline()\n"
        " if request:\n"
        "  print(json.dumps({'version': version('fixture-app'), 'prefix': sys.prefix}), flush=True)\n"
        " sys.stdin.buffer.read()\n"
        "def initialize(context):\n"
        " from pathlib import Path\n"
        " destination = context.placement.config_dir\n"
        " if destination is None: raise RuntimeError('config placement missing')\n"
        " if os.environ.get('FIXTURE_FAIL_INITIALIZE') == '1':\n"
        "  raise RuntimeError('controlled initialization interruption')\n"
        " marker = {'operation_id': str(context.operation_id), "
        "'generation_id': str(context.generation_id), 'directory': str(context.directory)}\n"
        " Path(destination, 'native-hook.json').write_text(json.dumps(marker), encoding='utf-8')\n"
        " barrier_ready = os.environ.get('APPRC_FIXTURE_INITIALIZE_READY')\n"
        " barrier_release = os.environ.get('APPRC_FIXTURE_INITIALIZE_RELEASE')\n"
        " if bool(barrier_ready) != bool(barrier_release):\n"
        "  raise RuntimeError('both initialization barrier paths are required')\n"
        " if barrier_ready and barrier_release:\n"
        "  Path(barrier_ready).write_text('ready', encoding='utf-8')\n"
        "  while not Path(barrier_release).exists(): time.sleep(0.01)\n"
        "def inventory(inspection, categories, forget_retained):\n"
        " from apprc.definition.installation import CleanupInventory, InventoryEntry\n"
        " from apprc.user_files.app_home.writes import file_revision\n"
        " if os.environ.get('FIXTURE_FAIL_INVENTORY') == '1':\n"
        "  raise RuntimeError('controlled inventory preflight failure')\n"
        " if categories != frozenset({'config'}):\n"
        "  raise RuntimeError('unexpected cleanup request')\n"
        " record = inspection.record\n"
        " if record is None or record.placement.config_dir is None:\n"
        "  raise RuntimeError('fixture config placement unavailable')\n"
        " root = record.placement.config_dir\n"
        " target = root / 'provider-owned.json'\n"
        " entries = (InventoryEntry(target, 'file', file_revision(target), 'config'),) if target.is_file() else ()\n"
        " return CleanupInventory(entries=entries, retained=(InventoryEntry(root, 'directory', None, 'config'),))\n"
        "def cleanup(context):\n"
        " marker = {'operation_id': str(context.operation_id), "
        "'generation_id': str(context.generation_id), 'directory': str(context.directory)}\n"
        " Path(context.placement.config_dir, 'cleanup-hook.json').write_text(json.dumps(marker), encoding='utf-8')\n"
        " if os.environ.get('FIXTURE_FAIL_CLEANUP') == '1':\n"
        "  raise RuntimeError('controlled cleanup hook failure')\n"
        "def host_diagnostics():\n"
        " if os.environ.get('FIXTURE_DOCTOR_FAILURE') == '1':\n"
        "  raise ValueError('controlled application diagnostic failure')\n"
        " return {'application': 'fixture'}\n"
        "runtime.mount_app_groups(cli, installation_management=True, "
        "installation_hooks=InstallationHooks("
        "initialize='fixture_app:initialize', inventory='fixture_app:inventory', "
        "cleanup='fixture_app:cleanup'), "
        "host_diagnostics=host_diagnostics)\n"
        "def main(): cli()\n",
        encoding="utf-8",
    )
    (project_root / "fixture_config.py").write_text(
        "from apprc import AppRC, Paths\n"
        "APP_RC = AppRC(app_id='fixture-app', paths=Paths(config=True), "
        "command_name='fixture-app')\n",
        encoding="utf-8",
    )
    environment = authoring_environment()
    run([str(uv), "lock"], environment=environment, cwd=project_root)
    git_environment = {
        **environment,
        "GIT_AUTHOR_NAME": "AppRC native fixture",
        "GIT_AUTHOR_EMAIL": "native-fixture@example.invalid",
        "GIT_COMMITTER_NAME": "AppRC native fixture",
        "GIT_COMMITTER_EMAIL": "native-fixture@example.invalid",
    }
    run(["git", "init", "-q", str(project_root)], environment=git_environment)
    run(
        [
            "git", "-C", str(project_root), "add",
            "pyproject.toml", "uv.lock", "fixture_app.py", "fixture_config.py",
            "vendor", "feature-dependency", "dev-dependency",
        ],
        environment=git_environment,
    )
    run(
        ["git", "-C", str(project_root), "commit", "-q", "-m", "fixture"],
        environment=git_environment,
    )

    spec = read_distribution_spec(project_root)
    project = build_project_snapshot(
        spec,
        revision="HEAD",
        destination=base / "project.zip",
    )
    product = build_native_distribution(
        spec,
        project,
        uv=uv,
        workspace=base / "native-build",
        environment=environment,
        extras=("native-feature",),
    )
    linux_setup = next(
        artifact.path for artifact in product.artifacts
        if artifact.target == "x86_64-unknown-linux-gnu"
    )
    checksum_path = product.checksums.project_root / product.checksums.destination
    project_b = base / "fixture-b"
    shutil.copytree(
        project_root,
        project_b,
        ignore=shutil.ignore_patterns(".git", ".venv", ".cache", "dist"),
    )
    project_metadata = project_b / "pyproject.toml"
    project_metadata.write_text(
        project_metadata.read_text(encoding="utf-8").replace(
            "version = '1.0.0'", "version = '2.0.0'"
        ),
        encoding="utf-8",
    )
    run([str(uv), "lock"], environment=build_environment, cwd=project_b)
    run(["git", "init", "-q", str(project_b)], environment=git_environment)
    run(
        [
            "git", "-C", str(project_b), "add", "pyproject.toml", "uv.lock",
            "fixture_app.py", "fixture_config.py", "vendor",
            "feature-dependency", "dev-dependency",
        ],
        environment=git_environment,
    )
    run(
        ["git", "-C", str(project_b), "commit", "-q", "-m", "fixture v2"],
        environment=git_environment,
    )
    spec_b = read_distribution_spec(project_b)
    project_snapshot_b = build_project_snapshot(
        spec_b,
        revision="HEAD",
        destination=base / "project-b.zip",
    )
    build_native_distribution(
        spec_b,
        project_snapshot_b,
        uv=uv,
        workspace=base / "native-build-b",
        environment=environment,
        extras=("native-feature",),
    )
    return project_root, uv, linux_setup, checksum_path, spec, project

def disk_bytes(root: Path) -> int:
    """Count regular on-disk fixture bytes without following directory links."""
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
