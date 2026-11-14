"""Opt-in native feasibility construction; never imported by production code."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import shutil
import subprocess
import venv
from collections.abc import Sequence
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Literal

import pytest

from apprc.definition.installation import (
    InstallationInspection,
    OperationPlan,
    OwnedOutput,
)
from apprc.distribution import (
    DistributionSpec,
    build_native_distribution,
    build_project_snapshot,
    read_distribution_spec,
)
from apprc.distribution.models import decode_native_binding
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


def start_installation_driver(
    setup: Path,
    uv: Path,
    command_directory: Path,
    *,
    environment: dict[str, str],
    cwd: Path,
    log_path: Path,
    ready: Path | None = None,
    boundary: Literal["candidate", "publication"] | None = None,
) -> BaseProcess:
    """Run the real install engine with a killable test-only boundary.

    The child uses the native product's immutable binding, project archive and
    executable, and the real uv binary. Only boundary notification is replaced;
    native command dispatch and recovery are observed by separate executables.

    :param setup: Real setup executable supplying product bytes.
    :param uv: Fixture's pinned manager uv.
    :param command_directory: Isolated global-command destination.
    :param environment: Isolated installation environment.
    :param cwd: Child working directory.
    :param log_path: Persistent child diagnostics for failed readiness waits.
    :param ready: Notification written after the selected durable mutation.
    :param boundary: Mutation after which the child waits to be killed.
    :return: Started POSIX process; the caller owns termination and joining.
    """

    def install() -> None:
        import signal
        from zipfile import ZipFile

        from apprc.distribution.runtime import _manager, installation
        from apprc.services.installation import InstallationManager

        os.setsid()
        os.environ.clear()
        os.environ.update(environment)
        os.chdir(cwd)
        with log_path.open("w", encoding="utf-8", buffering=1) as log:
            import sys

            original_stdout, original_stderr = sys.stdout, sys.stderr

            sys.stdout = sys.stderr = log
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            sys.argv = [str(setup)]
            with ZipFile(setup) as archive:
                binding = decode_native_binding(archive.read("binding.json"))
                project_bytes = archive.read("project.zip")
            manager = InstallationManager(
                _manager._application(binding).schema, environment=environment
            )
            patch = pytest.MonkeyPatch()

            def pause() -> None:
                if ready is None:
                    raise ValueError(
                        "A crash boundary requires readiness output."
                    )
                ready.write_text("ready", encoding="utf-8")
                while True:
                    signal.pause()

            if boundary == "candidate":
                original_begin = manager.begin_operation

                def begin(plan: OperationPlan) -> InstallationInspection:
                    result = original_begin(plan)
                    pause()
                    return result

                patch.setattr(manager, "begin_operation", begin)
            elif boundary == "publication":
                original_publish = installation._publish_stable_command

                def publish(
                    destination: Path,
                    executable: Path,
                    *,
                    previous: tuple[OwnedOutput, ...],
                ) -> OwnedOutput:
                    result = original_publish(
                        destination, executable, previous=previous
                    )
                    pause()
                    return result

                patch.setattr(installation, "_publish_stable_command", publish)
            patch.setattr(_manager, "_manager_uv", lambda: uv)
            patch.setattr(
                _manager,
                "_read_product",
                lambda *, include_project=False: (
                    binding,
                    project_bytes if include_project else None,
                ),
            )
            try:
                _manager._install(
                    binding,
                    manager,
                    setup,
                    (
                        "--yes",
                        "--skip-setup",
                        "--command-directory",
                        str(command_directory),
                    ),
                )
            except BaseException:
                import traceback

                traceback.print_exc(file=log)
                raise
            finally:
                sys.stdout, sys.stderr = original_stdout, original_stderr

    process = multiprocessing.get_context("fork").Process(target=install)
    process.start()
    return process


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
            str(uv),
            "build",
            "--wheel",
            "--out-dir",
            str(vendor),
        ],
        environment=build_environment,
        cwd=repository / "src" / "apprc_dev" / "packaging" / "terminal",
    )
    # > These wheels are committed fixture inputs, not release outputs.
    (vendor / ".gitignore").unlink()
    core_wheel = next(vendor.glob("apprc_core-*.whl")).name
    terminal_wheel = next(vendor.glob("apprc-*.whl")).name
    (project_root / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['setuptools>=80']\n"
        "build-backend = 'fixture_backend'\nbackend-path = ['.']\n"
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
        "runtime-python = '3.14'\nconfig = true\nappdata = true\n"
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
    (project_root / "fixture_backend.py").write_text(
        "import json, os, time\n"
        "from pathlib import Path\n"
        "from setuptools import build_meta\n"
        "def __getattr__(name): return getattr(build_meta, name)\n"
        "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
        " ready = os.environ.get('APPRC_FIXTURE_BUILD_READY')\n"
        " release = os.environ.get('APPRC_FIXTURE_BUILD_RELEASE')\n"
        " if bool(ready) != bool(release): raise RuntimeError('incomplete build barrier')\n"
        " if ready:\n"
        "  Path(ready).write_text(json.dumps({'process': os.getpid(), 'parent': os.getppid()}), encoding='utf-8')\n"
        "  while not Path(release).exists(): time.sleep(0.01)\n"
        " return build_meta.build_wheel(wheel_directory, config_settings, metadata_directory)\n",
        encoding="utf-8",
    )
    (project_root / "fixture_app.py").write_text(
        "import json, os, platform, sys, time\n"
        "from pathlib import Path\n"
        "from importlib.metadata import PackageNotFoundError, distribution, version\n"
        "import typer\n"
        "from apprc.definition.installation import InstallationHooks\n"
        "from apprc.interfaces.cli.context import CliRuntimeOptions\n"
        "from apprc.interfaces.cli.config_command.state import DefaultConfigCliState\n"
        "from apprc.interfaces.cli.runtime import CliRuntime\n"
        "from apprc.interfaces.tui.launcher.model import LauncherSpec\n"
        "from fixture_config import APP_RC, NativeConfig\n"
        "cli = typer.Typer()\n"
        "def runtime_payload(state: DefaultConfigCliState) -> dict[str, object]:\n"
        " if state.resolved is None: raise RuntimeError('fixture configuration is unresolved')\n"
        " native = state.resolved.build(NativeConfig)\n"
        " return {'native': {'label': native.label}}\n"
        "runtime = CliRuntime(APP_RC, runtime_payload=runtime_payload)\n"
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
        " if not categories or not categories <= frozenset({'config', 'appdata'}):\n"
        "  raise RuntimeError('unexpected cleanup request')\n"
        " record = inspection.record\n"
        " if record is None: raise RuntimeError('fixture authority unavailable')\n"
        " entries, retained = [], []\n"
        " for category, root in (('config', record.placement.config_dir), ('appdata', record.placement.appdata_dir)):\n"
        "  if root is None: raise RuntimeError('fixture placement unavailable')\n"
        "  if category in categories:\n"
        "   target = root / 'provider-owned.json'\n"
        "   if target.is_file(): entries.append(InventoryEntry(target, 'file', file_revision(target), category))\n"
        "  retained.append(InventoryEntry(root, 'directory', None, category))\n"
        " return CleanupInventory(entries=tuple(entries), retained=tuple(retained))\n"
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
        "host_diagnostics=host_diagnostics, "
        "launcher_spec=LauncherSpec(title='Native fixture launcher'))\n"
        "def main(): cli()\n",
        encoding="utf-8",
    )
    (project_root / "fixture_config.py").write_text(
        "import apprc as rc\n"
        "APP_RC = rc.AppRC(app_id='fixture-app', paths=rc.Paths(config=True, appdata=True), "
        "command_name='fixture-app', user_dotenv=rc.UserDotenv())\n"
        "@APP_RC.config('native', prefix='NATIVE_')\n"
        "class NativeConfig(rc.Config):\n"
        "    label: str = rc.field('NATIVE_LABEL', default='default')\n",
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
            "git",
            "-C",
            str(project_root),
            "add",
            "pyproject.toml",
            "uv.lock",
            "fixture_app.py",
            "fixture_config.py",
            "vendor",
            "feature-dependency",
            "dev-dependency",
            "fixture_backend.py",
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
        artifact.path
        for artifact in product.artifacts
        if artifact.target == "x86_64-unknown-linux-gnu"
    )
    checksum_path = (
        product.checksums.project_root / product.checksums.destination
    )
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
            "git",
            "-C",
            str(project_b),
            "add",
            "pyproject.toml",
            "uv.lock",
            "fixture_app.py",
            "fixture_config.py",
            "vendor",
            "feature-dependency",
            "dev-dependency",
            "fixture_backend.py",
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
