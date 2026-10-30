"""Real isolated uv-tool ownership, editable changes and observed removal."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
    OperationStep,
)
from apprc.definition.paths import Layout
from apprc.distribution import generate_artifacts, install_support_files
from apprc.distribution.models import (
    Artifact,
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    prepare_source,
)
from apprc.distribution.runtime import bind_install_support, installed_probe
from apprc.distribution.runtime.backend import (
    backend_environment,
    inspect_uv_tools,
    install_uv_tool,
    parse_inventory,
    remove_uv_tool,
    select_uv_target,
)
from apprc.distribution.runtime.controllers import (
    inspect_saved,
    prepare_uninstall,
    repair_saved,
)
from apprc.distribution.runtime.installation import (
    install_application,
    install_prepared_application,
)
import apprc.distribution.runtime.installation as lifecycle_installation
from apprc.distribution.runtime.probe import probe_installed_tool
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.operations import plan_install, plan_repair


def test_real_uv_legacy_migration_activates_publicly_bound_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from apprc import AppRC
    from apprc.definition.installation import (
        InventoryEntry,
        LegacyMigrationEvidence,
        LegacyRunnable,
        MigrationInventory,
        OwnedOutput,
    )
    from apprc.distribution.runtime.backend import external_base_python
    from apprc.distribution.runtime.legacy import stage_legacy_support
    from apprc.user_files.app_home.writes import file_revision

    uv = shutil.which("uv")
    assert uv is not None
    project = tmp_path / "migration source % ! café"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-migration-consumer"
version = "1.0.0"
requires-python = ">=3.12"
[project.scripts]
apprc-migration-consumer = "migration_consumer:main"
[tool.setuptools]
py-modules = ["migration_consumer"]
""",
        encoding="utf-8",
    )
    (project / "migration_consumer.py").write_text(
        "import json\nimport os\nimport sys\n"
        "def main():\n"
        '    print(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}, ensure_ascii=False))\n',
        encoding="utf-8",
    )
    identity = InstallationIdentity(
        "migration-consumer",
        "apprc-migration-consumer",
        "migration_consumer",
        None,
        ("apprc-migration-consumer",),
    )
    source = InstallationSource("editable", str(project))
    placement = InstallationPlacement(Layout.native())
    environment = dict(os.environ)
    environment.update(
        UV_TOOL_DIR=str(tmp_path / "migration tools"),
        UV_TOOL_BIN_DIR=str(tmp_path / "migration commands"),
        UV_CACHE_DIR=str(tmp_path / "migration cache"),
        LOCALAPPDATA=str(tmp_path / "Local AppData"),
        USERPROFILE=str(tmp_path / "User Profile"),
        HOME=str(tmp_path / "Home"),
        XDG_DATA_HOME=str(tmp_path / "XDG Data"),
    )
    manager = AppRC(app_id=identity.app_id).installation(
        environment=environment
    )
    directory = manager.directory
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    try:
        install_uv_tool(
            target,
            source,
            environment=environment,
            python_requirement=">=3.12",
        )
        observed = probe_installed_tool(
            target,
            identity,
            source,
            placement,
            probe_path=Path(installed_probe.__file__).absolute(),
            environment=environment,
        )
        payload_root = tmp_path / "migration payload"
        payload_package = payload_root / "app_lifecycle"
        payload_package.mkdir(parents=True)
        (payload_package / "__init__.py").write_text(
            '"""Migration fixture payload."""\n', encoding="utf-8"
        )
        (payload_package / "install.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            'def main(): Path(sys.argv[1]).write_text("configured", encoding="utf-8")\n'
            'if __name__ == "__main__": main()\n',
            encoding="utf-8",
        )
        (payload_package / "uninstall.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "def main(): Path(sys.argv[1]).unlink(missing_ok=True)\n"
            'if __name__ == "__main__": main()\n',
            encoding="utf-8",
        )
        spec = DistributionSpec(
            ProjectMetadata(
                project,
                identity,
                "1.0.0",
                launcher_command=identity.commands[0],
            )
        )
        payload = PayloadTree(
            payload_root,
            tuple(
                PurePosixPath("app_lifecycle") / module
                for module in ("__init__.py", "install.py", "uninstall.py")
            ),
        )
        support_files = bind_install_support(
            install_support_files(spec, payload),
            observed,
            directory,
        )
        if os.name == "nt":
            assert {"launch.cmd", "uninstall.cmd"} <= {
                path.name for path in support_files
            }
            assert not {"launch.sh", "uninstall.sh"} & {
                path.name for path in support_files
            }
        else:
            assert {"launch.sh", "uninstall.sh"} <= {
                path.name for path in support_files
            }
            assert not {
                "launch.cmd",
                "launch.ps1",
                "uninstall.cmd",
                "uninstall.ps1",
            } & {path.name for path in support_files}
        legacy_root = tmp_path / "legacy distribution installation"
        create_private_directory_if_missing(legacy_root)
        receipt = legacy_root / "receipt.json"
        receipt.write_bytes(b"validated legacy receipt")
        controller = legacy_root / "lifecycle.py"
        controller.write_bytes(b"legacy controller")
        inert_controller = legacy_root / ".retired-lifecycle.py"
        old_uninstall = legacy_root / (
            "uninstall.cmd" if os.name == "nt" else "uninstall.sh"
        )
        old_uninstall.write_bytes(b"legacy uninstall frontend")
        inert_uninstall = legacy_root / ".retired-uninstall"
        generation_id = uuid4()
        support_bytes = {
            str(path): data for path, data in support_files.items()
        }
        if os.name != "nt":
            original_chmod = Path.chmod
            interrupted_frontend = (
                directory
                / "migration-staged"
                / str(generation_id)
                / "launch.sh"
            )

            def interrupt_executable_mode(
                path: Path, mode: int, *, follow_symlinks: bool = True
            ) -> None:
                if path == interrupted_frontend and mode == 0o700:
                    raise PermissionError(
                        "Interrupted executable support staging."
                    )
                original_chmod(path, mode, follow_symlinks=follow_symlinks)

            with monkeypatch.context() as patch:
                patch.setattr(Path, "chmod", interrupt_executable_mode)
                with pytest.raises(
                    PermissionError, match="Interrupted executable"
                ):
                    stage_legacy_support(
                        directory,
                        generation_id=generation_id,
                        support_files=support_bytes,
                    )
        staged = stage_legacy_support(
            directory,
            generation_id=generation_id,
            support_files=support_bytes,
        )
        owned_outputs = tuple(
            OwnedOutput(
                "support",
                str(path),
                hashlib.sha256(data).hexdigest(),
            )
            for path, data in sorted(
                support_files.items(), key=lambda item: str(item[0])
            )
        )
        observed = replace(observed, owned_outputs=owned_outputs)
        evidence = LegacyMigrationEvidence(
            InventoryEntry(receipt, "file", file_revision(receipt)),
            identity.distribution,
            identity.commands[0],
            observed.version,
            source.requirement,
            target,
            external_base_python(observed.prefix),
            (
                LegacyRunnable(
                    controller,
                    inert_controller,
                    file_revision(controller) or "",
                ),
                LegacyRunnable(
                    old_uninstall,
                    inert_uninstall,
                    file_revision(old_uninstall) or "",
                ),
            ),
        )
        result = manager.migrate_legacy(
            evidence,
            placement,
            inventory=MigrationInventory(legacy_root, directory),
            observed=observed,
            quiescent=True,
            staged_support=staged,
            generation_id=generation_id,
        )
        assert result.status == "ready"
        assert not receipt.exists()
        assert not controller.exists()
        assert not old_uninstall.exists()
        assert not inert_controller.exists()
        assert not inert_uninstall.exists()
        saved = inspect_saved(directory)
        assert saved.status == "ready"
        assert prepare_uninstall(directory).can_execute
        saved_controller = subprocess.run(
            [
                sys.executable,
                str(directory / "uninstall.py"),
                "--directory",
                str(directory),
                "--dry-run",
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(saved_controller.stdout)["status"] == "ready"
        app_configuration = tmp_path / "migration consumer configuration"
        subprocess.run(
            [
                sys.executable,
                str(directory / "repair-installer.py"),
                str(app_configuration),
            ],
            env=environment,
            check=True,
            capture_output=True,
        )
        assert app_configuration.read_text(encoding="utf-8") == "configured"
        subprocess.run(
            [
                sys.executable,
                str(directory / "app-uninstall.py"),
                str(app_configuration),
            ],
            env=environment,
            check=True,
            capture_output=True,
        )
        assert not app_configuration.exists()
        caller_directory = tmp_path / "unrelated caller working directory"
        caller_directory.mkdir()
        launch = directory / ("launch.cmd" if os.name == "nt" else "launch.sh")
        arguments = ("with space", "literal%20", "literal!bang", "snowman ☃")
        command = (
            [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/c",
                f'"{launch}"',
                *arguments,
            ]
            if os.name == "nt"
            else [str(launch), *arguments]
        )
        launched = subprocess.run(
            command,
            cwd=caller_directory,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        launched_value = json.loads(launched.stdout)
        assert launched_value == {
            "argv": list(arguments),
            "cwd": str(caller_directory),
        }
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)


def test_inventory_rejects_unknown_output_before_removal() -> None:
    assert parse_inventory("fixture v1.0\n- fixture\n") == frozenset(
        {"fixture"}
    )
    for stdout, stderr, status in (
        ("fixture v1.0\nfixture v1.0\n", "", 0),
        ("unrecognized output\n", "", 0),
        ("fixture v1.0\n", "warning: broken environment", 0),
        ("fixture v1.0\n", "", 1),
    ):
        with pytest.raises(ValueError):
            parse_inventory(stdout, stderr, status)


def test_editable_tool_probe_and_recorded_backend_removal(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    root = tmp_path / "actual checkout ü %2F with spaces"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-backend-fixture"
version = "1.0.0"
requires-python = ">=3.12"
[project.scripts]
apprc-backend-fixture = "backend_fixture:main"
[tool.setuptools]
py-modules = ["backend_fixture"]
""",
        encoding="utf-8",
    )
    override = tmp_path / "runtime override ü %2F"
    override.mkdir()
    (override / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-runtime-override-fixture"
version = "1.0.0"
requires-python = ">=3.12"
[tool.setuptools]
py-modules = []
""",
        encoding="utf-8",
    )
    implementation = root / "backend_fixture.py"
    implementation.write_text(
        'def main():\n    print("before editable change")\n', encoding="utf-8"
    )
    environment = dict(os.environ)
    environment.update(
        UV_TOOL_DIR="relative tools",
        UV_TOOL_BIN_DIR="relative commands",
        UV_CACHE_DIR=str(tmp_path / "cache"),
    )
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    assert target.tool_dir == tmp_path / "relative tools"
    assert target.bin_dir == tmp_path / "relative commands"
    identity = InstallationIdentity(
        "backend-fixture",
        "apprc-backend-fixture",
        "backend_fixture",
        None,
        ("apprc-backend-fixture",),
    )
    source = InstallationSource(
        "editable", str(root), runtime_overrides=(str(override),)
    )
    assert identity.distribution not in inspect_uv_tools(
        target, environment=environment
    )
    placement = InstallationPlacement(Layout.native())
    try:
        install_uv_tool(
            target,
            source,
            environment=environment,
            python_requirement=sys.executable,
        )
        snapshot = probe_installed_tool(
            target,
            identity,
            source,
            placement,
            probe_path=Path(installed_probe.__file__).absolute(),
            environment=environment,
        )
        assert snapshot.version == "1.0.0"
        interpreter = target.tool_dir / identity.distribution / "bin" / "python"
        override_check = subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('apprc-runtime-override-fixture'))",
            ],
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        assert override_check.stdout.strip() == "1.0.0"
        assert snapshot.prefix == target.tool_dir / identity.distribution
        command = snapshot.commands[0]
        before = subprocess.run(
            [str(command)],
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        assert before.stdout.strip() == "before editable change"
        implementation.write_text(
            'def main():\n    print("after live source change")\n',
            encoding="utf-8",
        )
        after = subprocess.run(
            [str(command)],
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        assert after.stdout.strip() == "after live source change"
        misleading = {
            **environment,
            "UV_TOOL_DIR": str(tmp_path / "unrelated tools"),
            "UV_TOOL_BIN_DIR": str(tmp_path / "unrelated commands"),
        }
        remove_uv_tool(target, identity.distribution, environment=misleading)
        assert identity.distribution not in inspect_uv_tools(
            target, environment=environment
        )
        assert not snapshot.prefix.exists()
        assert root.is_dir() and implementation.is_file()
        assert not (tmp_path / "unrelated tools").exists()
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)


def test_custom_install_composition_runs_setup_after_acquisition(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    project = tmp_path / "custom source ü %2F"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-custom-lifecycle-fixture"
version = "1.0.0"
requires-python = ">=3.12"
[project.scripts]
apprc-custom-lifecycle-fixture = "custom_fixture:main"
[tool.setuptools]
py-modules = ["custom_fixture"]
""",
        encoding="utf-8",
    )
    (project / "custom_fixture.py").write_text(
        "from pathlib import Path\n"
        "def main():\n"
        '    print(Path(__file__).with_name("setup.marker").read_text())\n',
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.update(
        UV_TOOL_DIR=str(tmp_path / "custom tools"),
        UV_TOOL_BIN_DIR=str(tmp_path / "custom commands"),
        UV_CACHE_DIR=str(tmp_path / "custom cache"),
    )
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    identity = InstallationIdentity(
        "custom-lifecycle-fixture",
        "apprc-custom-lifecycle-fixture",
        "custom_fixture",
        None,
        ("apprc-custom-lifecycle-fixture",),
    )
    placement = InstallationPlacement(Layout.native())
    directory = tmp_path / "installation"
    inspection = inspect_installation(directory, app_id=identity.app_id)
    plan = plan_install(
        identity,
        InstallationSource("editable", str(project)),
        placement,
        target,
        inspection=inspection,
    )
    prepared_sources: list[str] = []

    def prepare_project(prepared: PreparedSource) -> None:
        prepared_sources.append(prepared.requirement)
        (project / "setup.marker").write_text(
            "project setup completed", encoding="utf-8"
        )

    try:
        prepared = prepare_source(
            plan.target.source, tmp_path / "prepared source"
        )
        prepare_project(prepared)
        installed = install_prepared_application(
            plan,
            prepared,
            environment=environment,
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files={
                PurePosixPath("repair-installer.py"): b"print('repair entry')\n"
            },
            python_requirement=">=3.12",
        )
        assert installed.status == "ready"
        assert (
            installed.record is not None
            and installed.record.current is not None
        )
        assert prepared_sources == [str(project)]
        command = installed.record.current.commands[0]
        result = subprocess.run(
            [str(command)],
            env=backend_environment(target, environment),
            text=True,
            capture_output=True,
            check=True,
        )
        assert result.stdout.strip() == "project setup completed"
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)


def test_generated_saved_launch_and_removal_reconnect(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    project = tmp_path / "saved lifecycle source"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-saved-lifecycle-fixture"
version = "1.0.0"
requires-python = ">=3.12"
[project.scripts]
apprc-saved-lifecycle-fixture = "saved_fixture:main"
[tool.setuptools]
py-modules = ["saved_fixture"]
""",
        encoding="utf-8",
    )
    (project / "saved_fixture.py").write_text(
        'import sys\ndef main():\n    print("saved command executed", repr(sys.argv[1:]))\n',
    )
    payload_root = project / "payload"
    app_module = payload_root / "saved_app"
    app_module.mkdir(parents=True)
    (app_module / "__init__.py").write_text(
        '"""Saved route fixture."""\n', encoding="utf-8"
    )
    (app_module / "install.py").write_text(
        """
import argparse
import json
import os
from pathlib import Path, PurePosixPath
from apprc.definition.installation import InstallationIdentity, InstallationPlacement, InstallationSource
from apprc.definition.paths import Layout
from apprc.distribution.runtime import installed_probe
from apprc.distribution.runtime.backend import select_uv_target
from apprc.distribution.runtime.installation import install_application
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import plan_install, plan_repair

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    environment = dict(os.environ)
    project = Path(environment["APPRC_FIXTURE_PROJECT"])
    identity = InstallationIdentity(
        "saved-lifecycle-fixture", "apprc-saved-lifecycle-fixture", "saved_fixture",
        None, ("apprc-saved-lifecycle-fixture",),
    )
    target = select_uv_target(
        Path(environment["APPRC_FIXTURE_UV"]), environment=environment, invocation_cwd=project,
    )
    directory = args.directory or Path(environment["APPRC_FIXTURE_DIRECTORY"])
    placement = InstallationPlacement(Layout.native())
    source = InstallationSource("editable", str(project))
    inspection = inspect_installation(directory, app_id=identity.app_id)
    plan = (
        plan_repair(identity, source, placement, target, inspection=inspection)
        if args.repair else plan_install(identity, source, placement, target, inspection=inspection)
    )
    support_root = Path(environment["APPRC_FIXTURE_SUPPORT_ROOT"])
    support_files = {
        PurePosixPath(name): (support_root / name).read_bytes()
        for name in json.loads(environment["APPRC_FIXTURE_SUPPORT_PATHS"])
    }
    install_application(
        plan, environment=environment, probe_path=Path(installed_probe.__file__).absolute(),
        support_files=support_files, python_requirement=">=3.12",
    )

if __name__ == "__main__":
    main()
""",
        encoding="utf-8",
    )
    (app_module / "uninstall.py").write_text(
        """
import argparse
import os
from pathlib import Path
from apprc.distribution.runtime.controllers import (
    inspect_saved,
    parse_uninstall_handoff_args,
    prepare_uninstall,
    start_uninstall_handoff,
)

def main():
    original_pid, expected_revision, forwarded = parse_uninstall_handoff_args()
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--category", action="append", choices=("config", "appdata", "cache", "state"))
    parser.add_argument("--forget-retained", action="store_true")
    args = parser.parse_args(forwarded)
    preparation = prepare_uninstall(
        args.directory,
        categories=frozenset(args.category or ()),
        complete=args.complete,
        forget_retained=args.forget_retained,
    )
    if (
        expected_revision is not None
        and (
            preparation.plan is None
            or preparation.plan.expected_revision != expected_revision
        )
    ):
        raise RuntimeError("Installation changed after uninstall preview.")
    if not preparation.can_execute or preparation.plan is None:
        raise RuntimeError("The saved removal preview is not safe.")
    def cleanup(context):
        observed = inspect_saved(args.directory)
        if (
            observed.record is None
            or observed.record.operation is None
            or observed.record.operation.operation_id != context.operation_id
        ):
            raise RuntimeError("Custom cleanup requires its matching pending operation.")
        installed = observed.record.current or observed.record.last_successful
        if installed is None or not Path(installed.prefix).is_dir():
            raise RuntimeError("Custom cleanup requires the installed generation to remain present.")
        child_stopped = os.environ.get("APPRC_FIXTURE_CHILD_STOPPED")
        if child_stopped and not Path(child_stopped).is_file():
            raise RuntimeError("Launcher-owned child remained active during cleanup.")
        Path(os.environ["APPRC_FIXTURE_CLEANUP_MARKER"]).unlink(missing_ok=True)
    handoff = start_uninstall_handoff(
        preparation.plan,
        original_pid=original_pid,
        provider_cleanup=(
            cleanup
            if preparation.inspection.record is not None
            and preparation.inspection.record.current is not None
            else None
        ),
    )
    handoff.wait_ready()
    handoff.signal_exit()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("saved_app") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
        entry_module="saved_app.install",
        uninstall_entry_module="saved_app.uninstall",
    )
    identity = InstallationIdentity(
        "saved-lifecycle-fixture",
        "apprc-saved-lifecycle-fixture",
        "saved_fixture",
        None,
        ("apprc-saved-lifecycle-fixture",),
    )
    metadata = ProjectMetadata(
        project,
        identity,
        "1.0.0",
        distribution_path=PurePosixPath("src/saved_lifecycle_distribution"),
        launcher_command="apprc-saved-lifecycle-fixture",
    )
    spec = DistributionSpec(metadata)
    support_files = install_support_files(spec, payload)
    artifacts = generate_artifacts(spec, payload)
    installer = next(
        item
        for item in artifacts
        if item.destination.name == "main-installer.py"
    )
    environment = dict(os.environ)
    native_home = tmp_path / "home %20"
    environment.update(
        UV_TOOL_DIR=str(tmp_path / "saved tools"),
        UV_TOOL_BIN_DIR=str(tmp_path / "saved commands"),
        UV_CACHE_DIR=str(tmp_path / "saved cache"),
    )
    if os.name == "nt":
        native_root = tmp_path / "Local AppData %20"
        environment.update(
            USERPROFILE=str(native_home), LOCALAPPDATA=str(native_root)
        )
        directory = native_root / identity.app_id / "installation"
    elif sys.platform == "darwin":
        environment["HOME"] = str(native_home)
        directory = (
            native_home
            / "Library"
            / "Application Support"
            / identity.app_id
            / "installation"
        )
    else:
        native_root = tmp_path / "XDG Data %20"
        environment.update(
            HOME=str(native_home), XDG_DATA_HOME=str(native_root)
        )
        directory = native_root / identity.app_id / "installation"
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    support_root = tmp_path / "saved support source"
    for relative, content in support_files.items():
        output = support_root.joinpath(*relative.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    installer_path = tmp_path / "main-installer.py"
    installer_path.write_bytes(installer.content)
    cleanup_marker = tmp_path / "custom cleanup completed"
    cleanup_marker.write_text("stale application state", encoding="utf-8")
    environment.update(
        APPRC_FIXTURE_PROJECT=str(project),
        APPRC_FIXTURE_DIRECTORY=str(directory),
        APPRC_FIXTURE_UV=uv,
        APPRC_FIXTURE_SUPPORT_ROOT=str(support_root),
        APPRC_FIXTURE_SUPPORT_PATHS=json.dumps(
            [str(path) for path in support_files],
            separators=(",", ":"),
        ),
        APPRC_FIXTURE_CLEANUP_MARKER=str(cleanup_marker),
    )

    platform_suffix = ".cmd" if os.name == "nt" else ".sh"
    root_launch = next(
        item
        for item in artifacts
        if item.destination.name == f"app-launch{platform_suffix}"
    )
    root_uninstall = next(
        item
        for item in artifacts
        if item.destination.name == f"app-uninstall{platform_suffix}"
    )

    def invoke_root(
        artifact: Artifact,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        wrapper = tmp_path / "root wrappers" / artifact.destination.name
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_bytes(artifact.content)
        if artifact.destination.suffix == ".sh":
            wrapper.chmod(0o700)
            argv = [str(wrapper), *arguments]
        else:
            argv = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/c",
                f'"{wrapper}"',
                *arguments,
            ]
        result = subprocess.run(
            argv, env=environment, text=True, capture_output=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    try:
        subprocess.run(
            [
                str(uv),
                "run",
                "--no-config",
                "--no-project",
                "--script",
                str(installer_path),
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        installed = inspect_saved(directory)
        assert installed.status == "ready"
        assert (
            installed.record is not None
            and installed.record.current is not None
        )
        fixture_prefix = Path(installed.record.current.prefix)
        environment["APPRC_FIXTURE_PREFIX"] = str(fixture_prefix)
        support_names = {
            Path(item.path).name
            for item in installed.record.current.owned_outputs
            if item.kind == "support"
        }
        if os.name == "nt":
            assert not {"launch.sh", "uninstall.sh"} & support_names
        else:
            assert (
                not {
                    "launch.cmd",
                    "launch.ps1",
                    "uninstall.cmd",
                    "uninstall.ps1",
                }
                & support_names
            )

        rebound = bind_install_support(
            support_files,
            installed.record.current,
            directory,
            installed.record.current.owned_outputs,
        )
        rebound_root = tmp_path / "bound public support"
        for relative, content in rebound.items():
            target_path = rebound_root.joinpath(*relative.parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
        rebound_arguments = ("with space", "literal%20", "snowman ☃")
        rebound_launcher = rebound_root / (
            "launch.cmd" if os.name == "nt" else "launch.sh"
        )
        if os.name == "nt":
            rebound_result = subprocess.run(
                [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    f'"{rebound_launcher}"',
                    *rebound_arguments,
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            rebound_launcher.chmod(0o700)
            rebound_result = subprocess.run(
                [str(rebound_launcher), *rebound_arguments],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        assert rebound_result.returncode == 0, (
            rebound_result.stdout + rebound_result.stderr
        )
        assert rebound_result.stdout.strip() == (
            f"saved command executed {list(rebound_arguments)!r}"
        )
        launcher_arguments = ("with space", "literal%20", "snowman ☃")
        launcher = invoke_root(root_launch, *launcher_arguments)
        assert launcher.stdout.strip() == (
            f"saved command executed {list(launcher_arguments)!r}"
        )
        foreign_command = target.bin_dir / (
            "foreign.exe" if os.name == "nt" else "foreign"
        )
        foreign_command.write_bytes(b"foreign command")
        mismatched_observation = replace(
            installed.record.current,
            commands=(foreign_command,),
        )
        with pytest.raises(InstallationError, match="does not match"):
            bind_install_support(
                support_files,
                mismatched_observation,
                directory,
                installed.record.current.owned_outputs,
            )

        def run_saved_uninstall() -> None:
            invoke_root(root_uninstall)

        host_cli = """
import os
from pathlib import Path
import typer
import apprc as rc
app = typer.Typer()
rc.cli.mount_app_cli(
    app,
    rc.AppRC(app_id="saved-lifecycle-fixture", paths=rc.Paths()),
)
directory = Path(os.environ["APPRC_FIXTURE_DIRECTORY"])
directory_before = directory.is_dir()
prefix = Path(os.environ["APPRC_FIXTURE_PREFIX"])
prefix_before = prefix.is_dir()
try:
    app()
except SystemExit:
    assert directory.is_dir() == directory_before
    assert prefix.is_dir() == prefix_before
    raise
"""

        def run_grouped_cli(*arguments: str) -> None:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    host_cli,
                    "installation",
                    "uninstall",
                    *arguments,
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=90,
            )
            assert completed.returncode == 0, (
                completed.stdout + completed.stderr
            )

        run_grouped_cli("--yes")
        assert not cleanup_marker.exists()
        assert inspect_saved(directory).status == "removed-retained"
        assert not (target.tool_dir / identity.distribution).exists()
        assert prepare_uninstall(directory, complete=True).can_execute

        repair = subprocess.run(
            repair_saved(directory),
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert repair.returncode == 0
        assert inspect_saved(directory).status == "ready"
        cleanup_marker.write_text(
            "state created after repair", encoding="utf-8"
        )
        tui_child_started = tmp_path / "launcher child started"
        tui_child_stopped = tmp_path / "launcher child stopped"
        tui_environment = dict(environment)
        tui_environment.update(
            APPRC_FIXTURE_CHILD_STOPPED=str(tui_child_stopped),
        )
        tui_host = f"""
import asyncio
import os
import sys
from pathlib import Path
import apprc as rc
from apprc.interfaces.tui.launcher.app import LauncherApp
from apprc.interfaces.tui.launcher.model import (
    LauncherAction, LauncherSpec, run_launcher,
)
child_started = Path({str(tui_child_started)!r})
child_stopped = Path({str(tui_child_stopped)!r})
child_command = (
    sys.executable,
    "-c",
    "from pathlib import Path; import os, time; "
    f"Path({str(tui_child_started)!r}).write_text('started'); "
    "parent = os.getppid(); "
    "exec('while os.getppid() == parent: time.sleep(0.05)')",
)
spec = LauncherSpec(actions=(
    LauncherAction(
        "hold", "Hold foreground child",
        lambda _context, _interactive: child_command,
        interactive=False,
    ),
))
def run_headless(app):
    async def drive():
        async with app.run_test() as pilot:
            stop_children = app.home._stop_owned_children
            async def observe_stop():
                children = tuple(app.home._children.values())
                await stop_children()
                if child_started.exists() and not child_stopped.exists():
                    if not children or any(
                        child.returncode is None for child in children
                    ):
                        raise RuntimeError("Launcher did not await its owned child.")
                    child_stopped.write_text("stopped")
            app.home._stop_owned_children = observe_stop
            await pilot.click("#launcher-action-hold")
            for _ in range(200):
                if child_started.is_file():
                    break
                await pilot.pause(0.05)
            assert child_started.is_file(), "Owned foreground child did not start."
            await pilot.press("end")
            await pilot.pause()
            await pilot.click("#launcher-uninstall")
            await pilot.pause()
            await pilot.click("#remove")
            await app.workers.wait_for_complete(tuple(app.workers))
        return app.return_value
    return asyncio.run(drive())
LauncherApp.run = run_headless
directory = Path(os.environ["APPRC_FIXTURE_DIRECTORY"])
directory_before = directory.is_dir()
prefix = Path(os.environ["APPRC_FIXTURE_PREFIX"])
prefix_before = prefix.is_dir()
try:
    run_launcher(
        rc.AppRC(app_id="saved-lifecycle-fixture", paths=rc.Paths()),
        spec=spec,
        environment=dict(os.environ),
    )
except SystemExit as exited:
    assert exited.code == 0
    assert directory.is_dir() == directory_before
    assert prefix.is_dir() == prefix_before
    assert child_stopped.is_file()
    raise
raise RuntimeError("Launcher returned without its actual SystemExit path.")
"""
        tui_result = subprocess.run(
            [sys.executable, "-c", tui_host],
            env=tui_environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
        assert tui_result.returncode == 0, tui_result.stdout + tui_result.stderr
        assert tui_child_stopped.is_file()
        assert inspect_saved(directory).status == "removed-retained"
        assert not (target.tool_dir / identity.distribution).exists()
        assert not cleanup_marker.exists()
        repair = subprocess.run(
            repair_saved(directory),
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert inspect_saved(directory).status == "ready"
        cleanup_marker.write_text(
            "state created after launcher repair", encoding="utf-8"
        )
        run_saved_uninstall()
        assert inspect_saved(directory).status == "removed-retained"
        assert prepare_uninstall(directory, complete=True).can_execute

        run_grouped_cli(
            "--complete",
            "--forget-retained",
            "--yes",
        )
        assert not cleanup_marker.exists()
        assert not directory.exists()
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)


def _interrupted_install_plan(tmp_path: Path):
    uv = shutil.which("uv")
    assert uv is not None
    project = tmp_path / "interrupted source"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "apprc-interruption-fixture"
version = "1.0.0"
requires-python = ">=3.12"
[project.scripts]
apprc-interruption-fixture = "interruption_fixture:main"
[tool.setuptools]
py-modules = ["interruption_fixture"]
""",
        encoding="utf-8",
    )
    (project / "interruption_fixture.py").write_text(
        'def main():\n    print("interruption fixture")\n',
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.update(
        UV_TOOL_DIR=str(tmp_path / "interrupted tools"),
        UV_TOOL_BIN_DIR=str(tmp_path / "interrupted commands"),
        UV_CACHE_DIR=str(tmp_path / "interrupted cache"),
    )
    target = select_uv_target(
        Path(uv), environment=environment, invocation_cwd=tmp_path
    )
    identity = InstallationIdentity(
        "interruption-fixture",
        "apprc-interruption-fixture",
        "interruption_fixture",
        None,
        ("apprc-interruption-fixture",),
    )
    placement = InstallationPlacement(Layout.native())
    directory = tmp_path / "interrupted installation"
    plan = plan_install(
        identity,
        InstallationSource("editable", str(project)),
        placement,
        target,
        inspection=inspect_installation(directory, app_id=identity.app_id),
    )
    return environment, target, identity, directory, placement, plan


def _resume_interrupted_install(environment: dict[str, str], plan):
    return install_application(
        plan,
        environment=environment,
        probe_path=Path(installed_probe.__file__).absolute(),
        support_files={PurePosixPath("saved-helper.py"): b"print('saved')\n"},
        python_requirement=">=3.12",
    )


def test_install_resumes_after_package_checkpoint_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, target, identity, directory, placement, plan = (
        _interrupted_install_plan(tmp_path)
    )
    original_install = lifecycle_installation.install_uv_tool

    def interrupt_before_backend(*args, **kwargs) -> None:
        raise RuntimeError("interrupted before uv mutation")

    monkeypatch.setattr(
        lifecycle_installation, "install_uv_tool", interrupt_before_backend
    )
    try:
        with pytest.raises(
            RuntimeError, match="interrupted before uv mutation"
        ):
            _resume_interrupted_install(environment, plan)
        pending = inspect_installation(directory, app_id=identity.app_id)
        assert (
            pending.record is not None and pending.record.operation is not None
        )
        assert OperationStep.PACKAGE_CHANGED in pending.record.operation.steps
        assert pending.record.current is None

        repair = plan_repair(
            identity,
            plan.target.source,
            placement,
            plan.target.backend,
            inspection=pending,
        )
        monkeypatch.setattr(
            lifecycle_installation, "install_uv_tool", original_install
        )
        assert (
            _resume_interrupted_install(environment, repair).status == "ready"
        )
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)


def test_install_resumes_after_backend_mutation_before_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, target, identity, directory, placement, plan = (
        _interrupted_install_plan(tmp_path)
    )
    original_install = lifecycle_installation.install_uv_tool
    interrupted = False

    def mutate_then_interrupt(*args, **kwargs) -> None:
        nonlocal interrupted
        original_install(*args, **kwargs)
        if not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after uv mutation")

    monkeypatch.setattr(
        lifecycle_installation, "install_uv_tool", mutate_then_interrupt
    )
    try:
        with pytest.raises(RuntimeError, match="interrupted after uv mutation"):
            _resume_interrupted_install(environment, plan)
        pending = inspect_installation(directory, app_id=identity.app_id)
        assert (
            pending.record is not None and pending.record.operation is not None
        )
        assert OperationStep.PACKAGE_CHANGED in pending.record.operation.steps
        assert pending.record.current is None

        repair = plan_repair(
            identity,
            plan.target.source,
            placement,
            plan.target.backend,
            inspection=pending,
        )
        monkeypatch.setattr(
            lifecycle_installation, "install_uv_tool", original_install
        )
        assert (
            _resume_interrupted_install(environment, repair).status == "ready"
        )
    finally:
        remove_uv_tool(target, identity.distribution, environment=environment)
