"""Opt-in PyApp bootstrap, transport and saved-lifecycle feasibility proofs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import textwrap
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
)
from apprc.definition.paths import Layout
from apprc.distribution.frontends import build_native_installers
from apprc.distribution import install_support_files
from apprc.distribution.native import NativeArtifact, NativeTarget
from apprc.distribution.models import (
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import standalone_script
from apprc.distribution.runtime import installed_probe
from apprc.distribution.runtime.backend import (
    external_base_python,
    select_uv_target,
)
from apprc.distribution.runtime.controllers import repair_saved
from apprc.distribution.runtime.installation import install_application
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import plan_install
from tests.support_pyapp import (
    authoring_environment,
    authoring_git_environment,
    isolated_environment,
    native_builder,
    pinned_uv,
    require_opt_in,
    run,
)


@pytest.fixture(autouse=True)
def _require_serial_pyapp(request: pytest.FixtureRequest) -> None:
    """Reject xdist workers before they can start native builds or downloads."""
    if os.environ.get("APPRC_TEST_PYAPP") == "1" and hasattr(
        request.config, "workerinput"
    ):
        pytest.fail("Run PyApp feasibility serially with pytest -n 0.")


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("APPRC_TEST_PYAPP") != "1",
        reason="Set APPRC_TEST_PYAPP=1 to enable native feasibility builds.",
    ),
]

_APP_ID = "fixture-app"
_DISTRIBUTION = "apprc-pyapp-fixture-app"
_VERSION = "1.0.0"
_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _write_dispatcher(path: Path, *, marker: str) -> None:
    """Write the native bootstrap identity probe."""
    path.write_text(
        f"""import json, os, sys, uv
from importlib.metadata import version
MARKER = {marker!r}
def main():
    print(json.dumps({{"role": "identity", "marker": MARKER, "python": sys.executable, "pyapp": os.environ.get("PYAPP"), "uv": uv.find_uv_bin(), "uv_version": version("uv"), "argv": sys.argv[1:]}}))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )


def _write_project(
    root: Path,
    marker: str,
    core_version: str = "0.33.0",
    *,
    core_requirement: str | None = None,
) -> Path:
    """Author a tiny AppRC-declared console application for real setup."""
    root.mkdir(parents=True)
    core_requirement = core_requirement or f"apprc-core=={core_version}"
    (root / "pyproject.toml").write_text(
        "[build-system]\nrequires=['setuptools>=80']\nbuild-backend='setuptools.build_meta'\n"
        f"[project]\nname='apprc-pyapp-fixture-app'\nversion='1.0.0'\nrequires-python='>=3.12'\ndependencies=[{core_requirement!r},'platformdirs==4.10.0']\n"
        "[project.scripts]\napprc-pyapp-fixture-app='fixture_app:main'\n"
        "[tool.apprc.distribution]\nruntime-python='3.13'\n"
        "[tool.setuptools]\npy-modules=['fixture_app','fixture_config']\n",
        encoding="utf-8",
    )
    (root / "fixture_app.py").write_text(
        "import importlib.metadata,json,os,sys,time\n"
        f"MARKER={marker!r}\n"
        "def main():\n"
        " if '--hold' in sys.argv:\n"
        "  print(json.dumps({'pid':os.getpid()}),flush=True)\n"
        "  while True: time.sleep(0.1)\n"
        " print(json.dumps({'version':'1.0.0','marker':MARKER,'dependency':importlib.metadata.version('platformdirs'),'python_minor':sys.version_info.minor,'argv':sys.argv[1:]}))\n"
        " print('fixture-stderr', file=__import__('sys').stderr)\n"
        " if '--exit-23' in sys.argv: raise SystemExit(23)\n"
        "if __name__ == '__main__': main()\n",
        encoding="utf-8",
    )
    (root / "fixture_config.py").write_text(
        "from apprc import AppRC\nfrom apprc.definition.paths import Paths\n"
        "APP_RC = AppRC(app_id='fixture-app', paths=Paths(cache=True), "
        "command_name='apprc-pyapp-fixture-app')\n",
        encoding="utf-8",
    )
    return root


def _write_uninstall(path: Path) -> None:
    """Compose the same saved-management uninstall handoff used by real installs."""
    path.write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "from apprc.definition.installation import CleanupInventory, InventoryEntry\n"
        "from apprc.user_files.app_home.writes import file_revision\n"
        "from apprc.distribution.runtime.controllers import inspect_saved, parse_uninstall_handoff_args, prepare_uninstall, start_uninstall_handoff\n"
        "def main():\n"
        " original_pid, expected_revision, forwarded=parse_uninstall_handoff_args(); parser=argparse.ArgumentParser(); parser.add_argument('--directory',type=Path,required=True); parser.add_argument('--complete',action='store_true'); args=parser.parse_args(forwarded)\n"
        " inventory=None; categories=frozenset()\n"
        " if args.complete:\n"
        "  observed=inspect_saved(args.directory); installed=observed.record.current if observed.record else None\n"
        "  if installed is None or installed.placement.cache_dir is None: raise RuntimeError('fixture cleanup requires its recorded cache')\n"
        "  cache=installed.placement.cache_dir; categories=frozenset({'cache'})\n"
        "  files=(cache/'.apprc-owner.json',cache/'fixture-resource'); inventory=CleanupInventory(tuple(InventoryEntry(item,'file',file_revision(item),'cache') for item in files)+(InventoryEntry(cache,'directory',None,'cache'),))\n"
        " preparation=prepare_uninstall(args.directory,complete=args.complete,categories=categories,inventory=inventory)\n"
        " if not preparation.can_execute or preparation.plan is None: raise RuntimeError(f'saved uninstall preview is unsafe: {preparation.diagnostics}')\n"
        " if expected_revision is not None and preparation.plan.expected_revision != expected_revision: raise RuntimeError('installation changed after uninstall preview')\n"
        " def cleanup(context):\n"
        "  observed=inspect_saved(args.directory)\n"
        "  if observed.record is None or observed.record.operation is None or observed.record.operation.operation_id != context.operation_id: raise RuntimeError('cleanup requires its matching pending operation')\n"
        "  installed=observed.record.current or observed.record.last_successful\n"
        "  if installed is None or not installed.prefix.is_dir() or installed.placement.cache_dir is None: raise RuntimeError('cleanup requires its installed generation and cache')\n"
        "  (installed.placement.cache_dir/'fixture-resource').unlink(missing_ok=True)\n"
        " handoff=start_uninstall_handoff(preparation.plan,original_pid=original_pid,provider_cleanup=cleanup); handoff.wait_ready(); handoff.signal_exit()\n"
        "if __name__=='__main__': main()\n",
        encoding="utf-8",
    )


def _write_lifecycle_payload(root: Path) -> PayloadTree:
    """Author the app-specific saved install and uninstall actions."""
    lifecycle = root / "app_lifecycle"
    lifecycle.mkdir(parents=True)
    (lifecycle / "__init__.py").write_text(
        '"""Shared native and saved lifecycle fixture."""\n', encoding="utf-8"
    )
    (lifecycle / "install.py").write_text(
        textwrap.dedent("""\
            import argparse
            import hashlib
            import json
            import os
            import shutil
            import sys
            import tempfile
            from pathlib import Path, PurePosixPath
            from apprc.definition.installation import InstallationPlacement
            from apprc.definition.paths import Layout
            from apprc.distribution.runtime import (
                installed_probe,
                load_installer_spec,
                prepare_installation_source,
            )
            from apprc.distribution.runtime.acquisition import (
                SourceSelection,
                parse_source_arguments,
            )
            from apprc.distribution.runtime.backend import select_uv_target
            from apprc.distribution.runtime.installation import install_application
            from apprc.user_files.installation.discovery import inspect_installation
            from apprc.user_files.installation.operations import plan_install, plan_repair


            def main():
                spec = load_installer_spec()
                selection, remaining = parse_source_arguments(spec, sys.argv[1:])
                parser = argparse.ArgumentParser()
                parser.add_argument("--directory", type=Path, required=True)
                parser.add_argument("--repair", action="store_true")
                args = parser.parse_args(remaining)
                identity = spec.metadata.identity
                observed = inspect_installation(args.directory, app_id=identity.app_id)
                record = observed.record
                snapshot = (record.current or record.last_successful) if record else None
                placement = snapshot.placement if snapshot else InstallationPlacement(
                    Layout.native(),
                    cache_dir=Path(os.environ["XDG_CACHE_HOME"]) / identity.app_id,
                    capabilities=frozenset({"cache"}),
                )
                if args.repair:
                    if snapshot is None:
                        raise RuntimeError("saved source record is unavailable")
                    selection = SourceSelection(snapshot.source)
                    target = snapshot.backend
                else:
                    uv_executable = os.environ.get("UV") or shutil.which("uv")
                    if uv_executable is None:
                        raise RuntimeError("uv executable is unavailable")
                    target = select_uv_target(
                        Path(uv_executable),
                        environment=os.environ,
                        invocation_cwd=spec.metadata.project_root,
                    )

                with tempfile.TemporaryDirectory(prefix="apprc-native-source-") as temporary:
                    staging = Path(temporary)
                    prepared = prepare_installation_source(
                        spec,
                        selection,
                        staging,
                        repair_from=args.directory if args.repair else None,
                    )
                    plan = (
                        plan_repair(
                            identity,
                            prepared.source,
                            placement,
                            target,
                            inspection=observed,
                        )
                        if args.repair
                        else plan_install(
                            identity,
                            prepared.source,
                            placement,
                            target,
                            inspection=observed,
                        )
                    )
                    support_root = Path(__file__).parents[1] / "_support"
                    support = {}
                    excluded = (
                        prepared.support_files.keys()
                        if prepared.support_files is not None
                        else frozenset()
                    )
                    for output in (record.owned_outputs if record else ()):
                        if output.kind != "support":
                            continue
                        relative = PurePosixPath(output.path)
                        if (
                            relative.is_absolute()
                            or ".." in relative.parts
                            or output.digest is None
                        ):
                            raise RuntimeError(
                                "Saved installation contains invalid support ownership."
                            )
                        if relative in excluded:
                            continue
                        path = args.directory.joinpath(*relative.parts)
                        if path.is_symlink() or not path.is_file():
                            raise RuntimeError(
                                f"Saved installation support is missing: {relative}."
                            )
                        content = path.read_bytes()
                        if hashlib.sha256(content).hexdigest() != output.digest:
                            raise RuntimeError(
                                f"Saved installation support changed: {relative}."
                            )
                        support[relative] = content
                    if not support:
                        if support_root.is_symlink() or not support_root.is_dir():
                            raise RuntimeError(
                                "Generated AppRC lifecycle support directory is missing or linked."
                            )
                        for path in sorted(support_root.rglob("*")):
                            if path.is_symlink():
                                raise RuntimeError(
                                    f"Generated lifecycle support contains a link: {path}."
                                )
                            if path.is_file():
                                relative = PurePosixPath(
                                    path.relative_to(support_root).as_posix()
                                )
                                if relative not in excluded:
                                    support[relative] = path.read_bytes()
                            elif not path.is_dir():
                                raise RuntimeError(
                                    "Generated lifecycle support is not a regular file."
                                )
                    installed = install_application(
                        plan,
                        environment=dict(os.environ),
                        probe_path=Path(installed_probe.__file__).absolute(),
                        support_files=support,
                        python_requirement=spec.metadata.runtime_python_requirement,
                        prepared_source=prepared,
                    )
                    print(json.dumps({
                        "status": installed.status,
                        "backend": str(plan.target.backend.executable),
                        "source_digest": prepared.digest,
                    }))


            if __name__ == "__main__":
                main()
            """),
        encoding="utf-8",
    )
    _write_uninstall(lifecycle / "uninstall.py")
    return PayloadTree(
        root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )


def _public_envelope(root: Path, installer: bytes, package: Path) -> Path:
    """Stage a standalone public-entry script and exact release manifest."""
    envelope = root / "public-envelope"
    envelope.mkdir()
    installer_path = envelope / "main-installer.py"
    installer_path.write_bytes(installer)
    package_path = envelope / package.name
    shutil.copyfile(package, package_path)
    manifest = {
        "schema_version": 1,
        "app_id": _APP_ID,
        "distribution": _DISTRIBUTION,
        "version": _VERSION,
        "commit": _COMMIT,
        "payload_format": "script",
        "assets": [
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in (installer_path, package_path)
        ],
    }
    (envelope / "release-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return envelope


def _build_core_wheels(root: Path) -> tuple[Path, ...]:
    """Build a real core wheel for the fixture's local flat index."""
    environment = authoring_environment()
    fixture_uv = pinned_uv(root / "build uv")
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    repository_root = Path(__file__).resolve().parents[1]
    environment.update(
        UV_NO_CONFIG="1",
        UV_CACHE_DIR=str(root / "core wheel uv cache"),
    )
    result = run(
        [
            str(fixture_uv),
            "build",
            "--wheel",
            "--package",
            "apprc-core",
            "--out-dir",
            str(wheelhouse),
        ],
        environment=environment,
        cwd=repository_root,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return (next(wheelhouse.glob("apprc_core-*.whl")),)


def _build_native_release(
    root: Path,
    *,
    target: NativeTarget,
) -> tuple[Path, Path, Path, Path, tuple[NativeArtifact, ...]]:
    """Build the compiler's real locked release and return its artifacts."""
    fixture_uv = pinned_uv(root / "build uv")
    repository_root = Path(__file__).resolve().parents[1]
    repository_url = "https://github.com/HisQu/apprc"
    authoring = authoring_git_environment(repository_root, repository_url)
    committed_head = run(
        ["git", "rev-parse", "HEAD"],
        environment=authoring,
        cwd=repository_root,
    ).stdout.strip()
    committed_metadata = run(
        ["git", "show", f"{committed_head}:pyproject.toml"],
        environment=authoring,
        cwd=repository_root,
    ).stdout
    core_version = tomllib.loads(committed_metadata)["project"]["version"]
    project = _write_project(
        root / "release source",
        "release",
        core_version,
        core_requirement=f"apprc-core @ git+{repository_url}@{committed_head}",
    )
    authoring.pop("UV_FIND_LINKS", None)
    authoring.update(
        UV_NO_CONFIG="1",
        UV_CACHE_DIR=str(root / "authoring uv cache"),
    )
    lock = run(
        [str(fixture_uv), "lock"],
        environment=authoring,
        cwd=project,
        check=False,
    )
    assert lock.returncode == 0, lock.stdout + lock.stderr
    sdist_dir = root / "sdist"
    sdist_dir.mkdir()
    built = run(
        [str(fixture_uv), "build", "--sdist", "--out-dir", str(sdist_dir)],
        environment=authoring,
        cwd=project,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    package = next(sdist_dir.glob("apprc_pyapp_fixture_app-1.0.0.tar.gz"))
    identity = InstallationIdentity(
        _APP_ID,
        _DISTRIBUTION,
        "fixture_app",
        "fixture_config:APP_RC",
        (_DISTRIBUTION,),
    )
    spec = DistributionSpec(
        ProjectMetadata(
            project,
            identity,
            _VERSION,
            bundle_repositories=(repository_url,),
            runtime_python="3.13",
        ),
        source_mode="release",
        repository_url="https://github.com/example/fixture",
        release_version=_VERSION,
        release_commit=_COMMIT,
        release_asset=f"https://github.com/example/fixture/releases/download/v{_VERSION}/{package.name}",
        release_digest=hashlib.sha256(package.read_bytes()).hexdigest(),
    )
    payload = _write_lifecycle_payload(root / "lifecycle payload")
    support = install_support_files(spec, payload)
    support_root = payload.root / "_support"
    support_paths = []
    for relative, content in support.items():
        path = support_root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        support_paths.append(PurePosixPath("_support") / relative)
    payload = PayloadTree(
        payload.root, payload.modules, resources=tuple(support_paths)
    )
    native = build_native_installers(
        spec,
        payload,
        source_package=package,
        uv=fixture_uv,
        workspace=root / "native assembly",
        targets=(target,),
        environment=authoring,
    )
    launch = next(
        item.path for item in native.frontends if "-launch-" in item.path.name
    )
    installer = next(
        item.path for item in native.frontends if "-install-" in item.path.name
    )
    return installer, launch, package, project, native.frontends


@pytest.mark.skipif(
    sys.platform != "linux", reason="Native lifecycle execution requires Linux."
)
def test_linux_native_frontends_preserve_saved_lifecycle(
    tmp_path: Path,
) -> None:
    """Build and run production Linux frontends through saved lifecycle."""
    require_opt_in()
    root = tmp_path / "native build"
    target: NativeTarget = "x86_64-unknown-linux-gnu"
    bootstrap_name = f"{_APP_ID}-bootstrap"
    builder = native_builder(
        root / "identity compiler",
        bootstrap_name=bootstrap_name,
    )
    identity_dispatcher = root / "identity.py"
    _write_dispatcher(identity_dispatcher, marker="stable")
    launcher = builder.build(
        identity_dispatcher,
        target=target,
        destination=root / "identity-linux",
    ).path
    environment = isolated_environment(
        root / "native runtime",
        bootstrap_name=bootstrap_name,
    )
    assert list(Path(environment["PATH"]).iterdir()) == []
    launcher_arguments = ("with space", "literal%20", "snowman ☃")
    first = run(
        [str(launcher), *launcher_arguments],
        environment=environment,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_identity = json.loads(first.stdout)
    assert first_identity["role"] == "identity"
    assert first_identity["marker"] == "stable"
    assert first_identity["argv"] == list(launcher_arguments)
    assert Path(first_identity["python"]).is_relative_to(
        (root / "native runtime").resolve()
    )
    assert Path(first_identity["pyapp"]).resolve() == launcher.resolve()
    assert first_identity["uv_version"] == "0.13.6"
    assert Path(first_identity["uv"]).is_absolute()
    corrupted = root / "corrupted-linux"
    shutil.copyfile(launcher, corrupted)
    with zipfile.ZipFile(launcher) as archive:
        entry = archive.getinfo("dispatcher.py")
        changed_payload = archive.read(entry).replace(b"'stable'", b"'tamper'")
    with corrupted.open("r+b") as stream:
        stream.truncate(entry.header_offset)
    with zipfile.ZipFile(corrupted, "a") as archive:
        archive.writestr("dispatcher.py", changed_payload)
    corrupted.chmod(0o700)
    rejected = run([str(corrupted)], environment=environment, check=False)
    assert rejected.returncode != 0 and rejected.stdout == ""

    changed_dispatcher = root / "identity-changed.py"
    _write_dispatcher(changed_dispatcher, marker="changed")
    changed_launcher = builder.build(
        changed_dispatcher,
        target=target,
        destination=root / "identity-changed-linux",
    ).path
    second = run(
        [str(changed_launcher), *launcher_arguments],
        environment=environment,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    second_identity = json.loads(second.stdout)
    assert second_identity["marker"] == "changed"
    assert second_identity["python"] == first_identity["python"]
    assert second_identity["uv"] == first_identity["uv"]
    assert second_identity["uv_version"] == first_identity["uv_version"]

    installer, _, package, project, _ = _build_native_release(
        root, target=target
    )
    environment["UV"] = first_identity["uv"]
    directory = root / "native runtime" / "data" / _APP_ID / "installation"
    install_result = run(
        [str(installer), "--directory", str(directory)],
        environment=environment,
        check=False,
    )
    assert install_result.returncode == 0, (
        install_result.stdout + install_result.stderr
    )
    installed = json.loads(install_result.stdout.splitlines()[-1])
    assert installed["status"] == "ready"
    assert installed["backend"] == first_identity["uv"]
    inspection = inspect_installation(directory, app_id=_APP_ID)
    assert inspection.status == "ready" and inspection.record is not None
    snapshot = inspection.record.current
    assert (
        snapshot is not None and snapshot.identity.distribution == _DISTRIBUTION
    )
    assert snapshot.backend.executable == Path(first_identity["uv"])
    assert (Path(environment["XDG_CACHE_HOME"]) / _APP_ID).is_dir()
    launcher_path = directory / "launch"
    assert launcher_path.stat().st_mode & 0o111
    launched = run(
        [
            str(launcher_path),
            "--directory",
            str(directory),
            "with space",
            "literal%20",
        ],
        environment=environment,
        check=False,
    )

    assert json.loads(launched.stdout.splitlines()[0]) == {
        "version": "1.0.0",
        "marker": "release",
        "dependency": "4.10.0",
        "python_minor": 13,
        "argv": ["with space", "literal%20"],
    }
    assert "fixture-stderr" in launched.stderr
    failed_status = run(
        [str(launcher_path), "--directory", str(directory), "--exit-23"],
        environment=environment,
        check=False,
    )
    assert failed_status.returncode == 23
    retained_payload = directory / "installer-payload.zip"
    original_payload = retained_payload.read_bytes()
    original_authority = (directory / "installation.json").read_bytes()
    altered_payload = original_payload + b"\nmodified retained payload\n"
    retained_payload.write_bytes(altered_payload)
    refused_payload = run(
        repair_saved(directory), environment=environment, check=False
    )
    assert refused_payload.returncode != 0
    assert retained_payload.read_bytes() == altered_payload
    assert (directory / "installation.json").read_bytes() == original_authority
    retained_payload.write_bytes(original_payload)
    original_launcher = launcher_path.read_bytes()
    edited_launcher = original_launcher + b"\nuser-modified launcher\n"
    launcher_path.write_bytes(edited_launcher)
    refused = run(repair_saved(directory), environment=environment, check=False)
    assert refused.returncode != 0
    assert launcher_path.read_bytes() == edited_launcher
    still_owned = inspect_installation(directory, app_id=_APP_ID)
    assert still_owned.record is not None
    assert still_owned.record.last_successful == snapshot
    assert still_owned.record.owned_outputs == inspection.record.owned_outputs
    retained_outputs = [
        item
        for item in inspection.record.owned_outputs
        if item.path == "installer-payload.zip" and item.kind == "support"
    ]
    assert len(retained_outputs) == 1
    assert (directory / retained_outputs[0].path).is_file()
    launcher_path.write_bytes(original_launcher)
    cache_file = (
        Path(environment["XDG_CACHE_HOME"]) / _APP_ID / "fixture-resource"
    )
    cache_file.write_text("provider-owned cached resource", encoding="utf-8")
    package.unlink()
    shutil.rmtree(project)
    launcher_path.unlink()
    repaired = run(
        repair_saved(directory), environment=environment, check=False
    )
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    repaired_inspection = inspect_installation(directory, app_id=_APP_ID)
    assert repaired_inspection.record is not None
    assert repaired_inspection.record.current is not None
    assert repaired_inspection.record.current.backend == snapshot.backend
    assert launcher_path.is_file() and launcher_path.stat().st_mode & 0o111
    recovered = run(
        [str(launcher_path), "--directory", str(directory), "after-repair"],
        environment=environment,
        check=False,
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    held = subprocess.Popen(
        [
            str(launcher_path),
            "--directory",
            str(directory),
            "--hold",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert held.stdout is not None
        identity = json.loads(held.stdout.readline())
        assert identity == {"pid": held.pid}
        held.terminate()
        assert held.wait(timeout=10) == -signal.SIGTERM
    finally:
        # > Failure cleanup targets only this fixture's isolated process group.
        try:
            os.killpg(held.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if held.poll() is None:
            held.kill()
            held.wait(timeout=10)
        if held.stdout is not None:
            held.stdout.close()
        if held.stderr is not None:
            held.stderr.close()
    assert json.loads(recovered.stdout.splitlines()[0])["marker"] == "release"
    management = json.loads((directory / "management.json").read_text())
    base_python = Path(management["base_python"])
    assert base_python.is_file() and base_python.is_absolute()
    assert not base_python.is_relative_to(directory)
    assert not base_python.is_relative_to(snapshot.prefix)
    assert not base_python.is_relative_to(
        Path(environment["XDG_CACHE_HOME"]) / _APP_ID
    )
    assert not base_python.is_relative_to(
        Path(environment[f"PYAPP_INSTALL_DIR_{bootstrap_name.upper()}"])
    )
    removed = run(
        [
            str(base_python),
            str(directory / "management.py"),
            "uninstall",
            "--directory",
            str(directory),
            "--complete",
        ],
        environment=environment,
        check=False,
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    deadline = time.monotonic() + 30
    while directory.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not directory.exists() and not snapshot.prefix.exists()
    assert not (Path(environment["XDG_CACHE_HOME"]) / _APP_ID).exists()
    assert not cache_file.exists()
    assert base_python.is_file() and Path(first_identity["uv"]).is_file()
    assert not base_python.is_relative_to(
        Path(environment[f"PYAPP_INSTALL_DIR_{bootstrap_name.upper()}"])
    )


def test_windows_native_frontends_compile_without_execution(
    tmp_path: Path,
) -> None:
    """Cross-compile production frontends and inspect PE metadata only."""
    require_opt_in()
    root = tmp_path / "windows build"
    artifacts = _build_native_release(root, target="x86_64-pc-windows-msvc")
    windows_artifacts = artifacts[-1]
    assert len(windows_artifacts) == 2
    for artifact in windows_artifacts:
        assert artifact.target == "x86_64-pc-windows-msvc"
        assert artifact.path.suffix == ".exe"
        assert artifact.size > 0 and len(artifact.sha256) == 64
        report = json.loads(artifact.report.read_text())
        assert report["artifact"]["format"] == "PE"


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="Only Windows PE compilation is cross-platform.",
)
def test_pinned_uv_fixture_never_uses_host_uv(tmp_path: Path) -> None:
    """The explicitly opted-in helper pins its own uv package and executable."""
    require_opt_in()
    executable = pinned_uv(tmp_path / "owned uv")
    assert executable.is_absolute()
    assert executable.parent.parent.name == "uv-0.13.6"
    assert "0.13.6" in run([str(executable), "--version"]).stdout


@pytest.mark.skipif(
    sys.platform != "linux", reason="Native lifecycle execution requires Linux."
)
def test_real_lifecycle_saved_backend_launch_repair_and_external_base(
    tmp_path: Path,
) -> None:
    """Exercise real AppRC setup, saved management, uv ownership and cleanup."""
    require_opt_in()
    uv = pinned_uv(tmp_path / "fixture uv")
    environment = isolated_environment(tmp_path / "isolated")
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    project = _write_project(tmp_path / "source project", "first")
    identity = InstallationIdentity(
        "fixture-app",
        "apprc-pyapp-fixture-app",
        "fixture_app",
        "fixture_config:APP_RC",
        ("apprc-pyapp-fixture-app",),
    )
    target = select_uv_target(
        uv, environment=environment, invocation_cwd=tmp_path
    )
    source = InstallationSource(
        "editable",
        str(project),
        runtime_overrides=(str(Path(__file__).resolve().parents[1]),),
    )
    directory = (
        tmp_path / "isolated" / "data" / identity.app_id / "installation"
    )
    placement = InstallationPlacement(
        Layout.native(),
        cache_dir=Path(environment["XDG_CACHE_HOME"]) / identity.app_id,
        capabilities=frozenset({"cache"}),
    )
    inspection = inspect_installation(directory, app_id=identity.app_id)
    plan = plan_install(
        identity, source, placement, target, inspection=inspection
    )
    payload_root = tmp_path / "saved payload"
    lifecycle = payload_root / "app_lifecycle"
    lifecycle.mkdir(parents=True)
    (lifecycle / "__init__.py").write_text('"""Saved lifecycle fixture."""\n')
    (lifecycle / "install.py").write_text(
        "import argparse, json, os, sys\nfrom pathlib import Path, PurePosixPath\n"
        "from apprc.definition.installation import InstallationIdentity, InstallationPlacement, InstallationSource\n"
        "from apprc.definition.paths import Layout\n"
        "from apprc.distribution.runtime import installed_probe\n"
        "from apprc.distribution.runtime.backend import select_uv_target\n"
        "from apprc.distribution.runtime.installation import install_application\n"
        "from apprc.user_files.installation.discovery import inspect_installation\n"
        "from apprc.user_files.installation.operations import plan_install, plan_repair\n"
        "def main():\n"
        " parser=argparse.ArgumentParser(); parser.add_argument('--repair',action='store_true'); parser.add_argument('--directory',type=Path,required=True); args=parser.parse_args()\n"
        " env=dict(os.environ); project=Path(env['APPRC_FIXTURE_PROJECT']); identity=InstallationIdentity('fixture-app','apprc-pyapp-fixture-app','fixture_app','fixture_config:APP_RC',('apprc-pyapp-fixture-app',))\n"
        " observed=inspect_installation(args.directory,app_id=identity.app_id); saved=observed.record.current if observed.record and observed.record.current else None\n"
        " uv=Path(saved.backend.executable) if saved else Path(env['APPRC_FIXTURE_UV']); target=select_uv_target(uv,environment=env,invocation_cwd=project)\n"
        " source=InstallationSource('editable',str(project),runtime_overrides=(env['APPRC_FIXTURE_APPRC_ROOT'],)); placement=saved.placement if saved else InstallationPlacement(Layout.native(),cache_dir=Path(env['XDG_CACHE_HOME'])/identity.app_id,capabilities=frozenset({'cache'}))\n"
        " plan=plan_repair(identity,source,placement,target,inspection=observed) if args.repair else plan_install(identity,source,placement,target,inspection=observed)\n"
        " support_root=Path(env['APPRC_FIXTURE_SUPPORT_ROOT']); names=json.loads(env['APPRC_FIXTURE_SUPPORT_PATHS']); support={PurePosixPath(name):(support_root/name).read_bytes() for name in names}\n"
        " install_application(plan,environment=env,probe_path=Path(installed_probe.__file__).absolute(),support_files=support,python_requirement=sys.executable)\n"
        "if __name__=='__main__': main()\n",
        encoding="utf-8",
    )
    (lifecycle / "uninstall.py").write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "from apprc.distribution.runtime.controllers import parse_uninstall_handoff_args, prepare_uninstall, start_uninstall_handoff\n"
        "def main():\n"
        " original_pid, _, forwarded=parse_uninstall_handoff_args(); parser=argparse.ArgumentParser(); parser.add_argument('--directory',type=Path,required=True); parser.add_argument('--complete',action='store_true'); args=parser.parse_args(forwarded)\n"
        " preparation=prepare_uninstall(args.directory,complete=args.complete)\n"
        " if not preparation.can_execute or preparation.plan is None: raise RuntimeError('saved uninstall preview is unsafe')\n"
        " handoff=start_uninstall_handoff(preparation.plan,original_pid=original_pid); handoff.wait_ready(); handoff.signal_exit()\n"
        "if __name__=='__main__': main()\n",
        encoding="utf-8",
    )
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    spec = DistributionSpec(ProjectMetadata(project, identity, "1.0.0"))
    support = install_support_files(spec, payload)
    support_root = tmp_path / "saved support"
    support_root.mkdir()
    support_names = []
    for relative, content in support.items():
        path = support_root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        support_names.append(relative.as_posix())
    environment.update(
        APPRC_FIXTURE_PROJECT=str(project),
        APPRC_FIXTURE_UV=str(uv),
        APPRC_FIXTURE_APPRC_ROOT=str(Path(__file__).resolve().parents[1]),
        APPRC_FIXTURE_SUPPORT_ROOT=str(support_root),
        APPRC_FIXTURE_SUPPORT_PATHS=json.dumps(support_names),
    )
    try:
        installed = install_application(
            plan,
            environment=environment,
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files=support,
            python_requirement=sys.executable,
        )
        assert installed.status == "ready" and installed.record is not None
        snapshot = installed.record.current
        assert snapshot is not None and snapshot.backend == target
        assert snapshot.prefix == target.tool_dir / identity.distribution
        independent = external_base_python(snapshot.prefix)
        assert independent.is_absolute()
        assert not independent.is_relative_to(snapshot.prefix)
        assert (Path(environment["XDG_CACHE_HOME"]) / identity.app_id).is_dir()
        command = snapshot.commands[0]
        arguments = ("with space", "literal%20")
        result = subprocess.run(
            [str(command), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        assert json.loads(result.stdout.splitlines()[0]) == {
            "version": "1.0.0",
            "marker": "first",
            "dependency": "4.10.0",
            "python_minor": sys.version_info.minor,
            "argv": list(arguments),
        }
        assert "fixture-stderr" in result.stderr
        failed_command = subprocess.run(
            [str(command), "--exit-23"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed_command.returncode == 23
        management = subprocess.run(
            [
                str(independent),
                str(directory / "management.py"),
                "launch",
                "--directory",
                str(directory),
                *arguments,
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        assert json.loads(management.stdout.splitlines()[0]) == {
            "version": "1.0.0",
            "marker": "first",
            "dependency": "4.10.0",
            "python_minor": sys.version_info.minor,
            "argv": list(arguments),
        }
        project.joinpath("fixture_app.py").write_text(
            project.joinpath("fixture_app.py")
            .read_text()
            .replace("first", "changed"),
            encoding="utf-8",
        )
        repaired = subprocess.run(
            repair_saved(directory),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        refreshed = inspect_installation(directory, app_id=identity.app_id)
        assert refreshed.status == "ready"
        assert (
            refreshed.record is not None
            and refreshed.record.current is not None
        )
        assert refreshed.record.current.backend == snapshot.backend
        changed = subprocess.run(
            [str(command), "changed payload"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        assert json.loads(changed.stdout.splitlines()[0]) == {
            "version": "1.0.0",
            "marker": "changed",
            "dependency": "4.10.0",
            "python_minor": sys.version_info.minor,
            "argv": ["changed payload"],
        }
        missing_uv = uv.with_name("uv-missing")
        uv.rename(missing_uv)
        try:
            failed_repair = subprocess.run(
                repair_saved(directory),
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            assert failed_repair.returncode != 0
            unchanged = inspect_installation(directory, app_id=identity.app_id)
            assert unchanged.record is not None
            assert unchanged.record.current is not None
            assert unchanged.record.current.backend == snapshot.backend
        finally:
            missing_uv.rename(uv)
    finally:
        from apprc.distribution.runtime.backend import remove_uv_tool

        remove_uv_tool(target, identity.distribution, environment=environment)


@pytest.mark.parametrize(
    "mutation",
    (
        "valid",
        "renamed",
        "wrong-app",
        "wrong-version",
        "wrong-commit",
        "wrong-package",
        "modified-package",
        "modified-installer",
    ),
)
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="Public standalone execution requires Linux.",
)
def test_public_standalone_envelope_rejects_mismatch_before_entry(
    tmp_path: Path, mutation: str
) -> None:
    """Execute the public loader and reject invalid filename, identity or bytes."""
    require_opt_in()
    payload_root = tmp_path / "payload"
    package_module = payload_root / "app_lifecycle"
    package_module.mkdir(parents=True)
    (package_module / "__init__.py").write_text(
        '"""Fixture lifecycle."""\n', encoding="utf-8"
    )
    (package_module / "install.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "Path(os.environ['APPRC_FIXTURE_ENTRY']).write_text('entered')\n",
        encoding="utf-8",
    )
    _write_uninstall(package_module / "uninstall.py")
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    package = tmp_path / "fixture-1.0.tar.gz"
    package.write_bytes(b"fixture release package")
    identity = InstallationIdentity(
        _APP_ID, _DISTRIBUTION, "fixture_app", None, ("fixture-command",)
    )
    spec = DistributionSpec(
        ProjectMetadata(tmp_path, identity, _VERSION),
        source_mode="release",
        repository_url="https://github.com/example/fixture",
        release_version=_VERSION,
        release_commit=_COMMIT,
        release_asset=package.name,
        release_digest=hashlib.sha256(package.read_bytes()).hexdigest(),
    )
    installer = standalone_script(spec, payload, entry=payload.entry_module)
    envelope = _public_envelope(tmp_path, installer, package)
    if mutation == "renamed":
        selected = envelope / "renamed.py"
        (envelope / "main-installer.py").rename(selected)
    else:
        selected = envelope / "main-installer.py"
    manifest_path = envelope / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation in {"wrong-app", "wrong-version", "wrong-commit"}:
        field = {
            "wrong-app": "app_id",
            "wrong-version": "version",
            "wrong-commit": "commit",
        }[mutation]
        manifest[field] = "wrong"
    elif mutation == "wrong-package":
        manifest["assets"][1]["filename"] = "other-package.tar.gz"
    elif mutation == "modified-package":
        (envelope / package.name).write_bytes(b"modified package")
    elif mutation == "modified-installer":
        selected.write_bytes(selected.read_bytes() + b"\n# changed")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    marker = tmp_path / "payload entered"
    environment = isolated_environment(tmp_path / "isolated")
    environment["APPRC_FIXTURE_ENTRY"] = str(marker)
    uv = pinned_uv(tmp_path / "owned uv")
    result = run(
        [
            str(uv),
            "run",
            "--no-config",
            "--no-project",
            "--script",
            str(selected),
        ],
        environment=environment,
        check=False,
    )
    if mutation == "valid":
        assert result.returncode == 0, result.stdout + result.stderr
        assert marker.read_text() == "entered"
    else:
        assert result.returncode != 0
        assert not marker.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="Selected script execution requires Linux."
)
def test_selected_script_uses_its_pep723_dependencies(tmp_path: Path) -> None:
    """A selected installer dependency is resolved in the clean uv script child."""
    require_opt_in()
    payload_root = tmp_path / "payload"
    package_module = payload_root / "app_lifecycle"
    package_module.mkdir(parents=True)
    (package_module / "__init__.py").write_text(
        '"""Fixture lifecycle."""\n', encoding="utf-8"
    )
    (package_module / "install.py").write_text(
        "import importlib.metadata, os\nfrom pathlib import Path\n"
        "Path(os.environ['APPRC_FIXTURE_ENTRY']).write_text("
        "importlib.metadata.version('idna'))\n",
        encoding="utf-8",
    )
    (package_module / "uninstall.py").write_text("pass\n", encoding="utf-8")
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    package = tmp_path / "fixture-1.0.tar.gz"
    package.write_bytes(b"fixture")
    identity = InstallationIdentity(
        _APP_ID, _DISTRIBUTION, "fixture_app", None, ("fixture-command",)
    )
    spec = DistributionSpec(
        ProjectMetadata(tmp_path, identity, _VERSION),
        source_mode="release",
        repository_url="https://github.com/example/fixture",
        release_version=_VERSION,
        release_commit=_COMMIT,
        release_asset=package.name,
        release_digest=hashlib.sha256(package.read_bytes()).hexdigest(),
    )
    installer = standalone_script(spec, payload, entry=payload.entry_module)
    installer = installer.replace(
        b"# dependencies = [",
        b'# dependencies = [\n#   "idna==3.10",',
        1,
    )
    envelope = _public_envelope(tmp_path, installer, package)
    marker = tmp_path / "selected dependency"
    environment = isolated_environment(tmp_path / "isolated")
    environment["APPRC_FIXTURE_ENTRY"] = str(marker)
    result = run(
        [
            str(pinned_uv(tmp_path / "owned uv")),
            "run",
            "--no-config",
            "--no-project",
            "--script",
            str(envelope / "main-installer.py"),
        ],
        environment=environment,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == "3.10"
