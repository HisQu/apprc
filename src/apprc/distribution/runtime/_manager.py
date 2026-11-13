"""Native AppRC manager entrypoint shared by setup and installed executables."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4
from apprc.definition.installation import InstallationPlacement, OwnedOutput, RuntimeSlot
from apprc.distribution.models import NativeBinding, decode_native_binding
from apprc.services.installation import InstallationManager


def _executable() -> Path:
    value = os.environ.get("PYAPP")
    if not value:
        raise RuntimeError("PyApp did not provide the executing manager path.")
    return Path(value).absolute()


def _read_product(
    *, include_project: bool = False
) -> tuple[NativeBinding, bytes | None]:
    """Verify the appended archive and optionally load its project snapshot."""
    executable = _executable()
    expected_size = globals().get("_APPRC_ARCHIVE_SIZE")
    expected_digest = globals().get("_APPRC_ARCHIVE_SHA256")
    if (
        type(expected_size) is not int
        or expected_size <= 0
        or not isinstance(expected_digest, str)
        or len(expected_digest) != 64
    ):
        raise RuntimeError("Native manager archive verification metadata is unavailable.")
    size = executable.stat().st_size
    start = size - expected_size
    if start < 0:
        raise RuntimeError("Native manager archive is truncated.")
    digest = hashlib.sha256()
    with executable.open("rb") as stream:
        stream.seek(start)
        for chunk in iter(lambda: stream.read(131072), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise RuntimeError("Native manager archive changed after loading.")
    with zipfile.ZipFile(executable) as archive:
        binding = decode_native_binding(archive.read("binding.json"))
        project = archive.read("project.zip") if include_project else None
    if project is not None and hashlib.sha256(project).hexdigest() != binding.source.digest:
        raise RuntimeError("Embedded project snapshot differs from its binding.")
    return binding, project


def _application(binding: NativeBinding):
    from apprc import AppRC

    return AppRC(
        app_id=binding.identity.app_id,
        display_name=binding.display_name,
        paths=binding.capabilities.paths,
        layout=binding.layout,
        bootstrap_env_prefix=binding.bootstrap_env_prefix,
        command_name=binding.command_name,
    )


def _manager_uv() -> Path:
    """Resolve only the uv package and executable owned by this manager."""
    import uv

    prefix = Path(sys.prefix).resolve(strict=True)
    package = Path(uv.__file__).resolve(strict=True)
    executable = Path(uv.find_uv_bin()).resolve(strict=True)
    if not package.is_relative_to(prefix) or not executable.is_relative_to(prefix):
        raise RuntimeError("The manager-owned uv executable is unavailable.")
    return executable


def _install(
    binding: NativeBinding,
    manager: InstallationManager,
    executable: Path,
    args: tuple[str, ...],
) -> int:
    """Install or transactionally update the binding's embedded project."""
    import argparse

    from apprc.definition.resolution import ResolveOptions
    from apprc.distribution.runtime.installation import (
        install_application,
        installation_maintenance_group,
    )
    from apprc.interfaces.cli.context import CliRuntimeOptions
    from apprc.user_files.app_home.layouts import resolve_app_paths
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--command-directory", type=Path)
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument("--start-menu", action="store_true")
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--env-file", action="append", type=Path)
    parser.add_argument(
        "--env-file-overrides-os-environ", "-o", action="store_true"
    )
    parser.add_argument("--skip-dotenv-layers", "-s", action="store_true")
    parser.add_argument("--workspace")
    parser.add_argument("--layout")
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--log-level")
    options, extras = parser.parse_known_args(args)
    if extras:
        raise ValueError("Native install received unsupported arguments: " + " ".join(extras))

    runtime_parser = argparse.ArgumentParser(add_help=False)
    runtime_parser.add_argument("--env-file", action="append", type=Path)
    runtime_parser.add_argument(
        "--env-file-overrides-os-environ", "-o", action="store_true"
    )
    runtime_parser.add_argument("--skip-dotenv-layers", "-s", action="store_true")
    runtime_parser.add_argument("--workspace")
    runtime_parser.add_argument("--layout")
    runtime_parser.add_argument("--app-root", type=Path)
    runtime_parser.add_argument("--log-level")
    runtime_options, _ = runtime_parser.parse_known_args(sys.argv[1:])
    captured_options = CliRuntimeOptions.from_typer(
        env_files=runtime_options.env_file,
        env_file_overrides_os_environ=runtime_options.env_file_overrides_os_environ,
        load_dotenv_layers=not runtime_options.skip_dotenv_layers,
        workspace=runtime_options.workspace,
        layout=runtime_options.layout,
        app_root=runtime_options.app_root,
        log_level=runtime_options.log_level,
    )
    environment = dict(os.environ)
    previous = manager.inspect().record
    if previous is not None and (
        previous.identity != binding.identity
        or previous.command_name != binding.command_name
    ):
        raise RuntimeError("Saved installation belongs to another native product.")
    if previous is not None:
        placement = previous.placement
    else:
        paths = resolve_app_paths(
            manager.spec,
            ResolveOptions(
                env_files=captured_options.env_files,
                env_file_overrides_os_environ=(
                    captured_options.env_file_overrides_os_environ
                ),
                load_dotenv_layers=captured_options.load_dotenv_layers,
                workspace=captured_options.workspace,
                layout=captured_options.layout or binding.layout,
            ),
            environment,
        )

        capabilities = binding.capabilities.paths
        placement = InstallationPlacement(
            layout=paths.layout,
            config_dir=paths.config_dir if capabilities.config else None,
            appdata_dir=paths.appdata_dir if capabilities.appdata else None,
            cache_dir=paths.cache_dir if capabilities.cache else None,
            state_dir=paths.state_dir if capabilities.state else None,
            logs_dir=paths.logs_dir if capabilities.state else None,
            capabilities=frozenset(
                kind
                for kind, enabled in (
                    ("config", capabilities.config),
                    ("appdata", capabilities.appdata),
                    ("cache", capabilities.cache),
                    ("state", capabilities.state),
                )
                if enabled
            ),
        )

    uv = _manager_uv()
    _, project_bytes = _read_product(include_project=True)
    if project_bytes is None:
        raise RuntimeError("The embedded project snapshot is unavailable.")

    with tempfile.TemporaryDirectory(prefix="apprc-native-project-") as stage:
        project_archive = Path(stage) / "project.zip"
        project_archive.write_bytes(project_bytes)
        runtime = RuntimeSlot(
            uuid4(),
            binding.source,
            binding.selection,
            hooks=binding.hooks,
        )
        with installation_maintenance_group(binding.maintenance_group_name):
            inspection = install_application(
                manager,
                binding.identity,
                runtime,
                placement,
                command_name=binding.command_name,
                project_archive=project_archive,
                manager_executable=executable,
                uv=uv,
                command_directory=options.command_directory,
                assume_yes=options.yes,
            )

    from apprc.distribution.runtime.installation import (
        offer_configuration_setup,
        publish_optional_shortcuts,
    )

    try:
        inspection = publish_optional_shortcuts(
            manager,
            manager.directory
            / (
                binding.command_name + (".exe" if os.name == "nt" else "")
            ),
            binding.identity,
            display_name=binding.display_name,
            start_menu=options.start_menu,
            desktop=options.desktop,
            launch_enabled=binding.launch_enabled,
        )
    except (OSError, ValueError) as error:
        print(
            f"Warning: optional shortcuts were not updated: {error}",
            file=sys.stderr,
        )
    offer_configuration_setup(inspection, skip=options.skip_setup)
    return 0


def _owned_manager_invocation(
    executable: Path, manager: InstallationManager, binding: NativeBinding
) -> bool:
    """Recognize the recorded stable manager or its exact global command copy."""
    record = manager.inspect().record
    if record is None:
        return False
    stable = manager.directory / (
        binding.command_name + (".exe" if os.name == "nt" else "")
    )
    try:
        executable_path = Path(os.path.abspath(executable))
        resolved_executable = executable.resolve(strict=True)
    except OSError:
        return False
    try:
        resolved_stable = stable.resolve(strict=True)
    except OSError:
        resolved_stable = None
    normalized_executable = os.path.normcase(str(executable_path))
    pending_outputs = (
        tuple(
            OwnedOutput("command", str(item.path), item.intended.digest)
            for item in record.operation.publication
        )
        if record.operation is not None
        else ()
    )
    for output in (*record.owned_outputs, *pending_outputs):
        if output.kind != "command" or output.digest is None:
            continue
        output_path = os.path.normcase(os.path.abspath(output.path))
        if (
            output_path == os.path.normcase(os.path.abspath(stable))
            and output_path == normalized_executable
            and resolved_stable is not None
            and resolved_executable == resolved_stable
        ):
            try:
                with stable.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
            except OSError:
                continue
            if digest == output.digest:
                return True
        if output_path != normalized_executable:
            continue
        if executable.is_symlink():
            if (
                os.name == "nt"
                or resolved_stable is None
                or resolved_executable != resolved_stable
            ):
                continue
            try:
                digest = hashlib.sha256(
                    os.fsencode(os.readlink(executable))
                ).hexdigest()
            except OSError:
                continue
        else:
            try:
                with executable.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
            except OSError:
                continue
        if digest == output.digest:
            return True
    return False


def _forward(
    binding: NativeBinding, manager: InstallationManager, args: list[str]
) -> int:
    """Forward one ordinary command after acquiring its runtime lease."""
    from apprc.distribution.runtime.backend import (
        runtime_command,
        runtime_environment,
    )
    from apprc.distribution.runtime._leases import (
        acquire_runtime_lease_locked,
    )
    from apprc.user_files.installation.coordination import installation_lock

    lease = None
    try:
        with installation_lock(manager.directory):
            inspection = manager.inspect()
            record = inspection.require_usable()
            if record is None or record.active_runtime is None:
                raise RuntimeError(
                    "The application runtime is unavailable; use app doctor or repair."
                )
            runtime = record.active_runtime
            command = runtime_command(
                manager.directory, runtime, record.command_name
            )
            environment = runtime_environment(dict(os.environ))
            if isinstance(runtime, RuntimeSlot):
                prefix = manager.directory / "runtimes" / str(runtime.slot_id) / ".venv"
                lease = acquire_runtime_lease_locked(
                    manager.directory / "runtimes" / str(runtime.slot_id)
                )
            else:
                prefix = runtime.environment
            binary = prefix / ("Scripts" if os.name == "nt" else "bin")
            environment["VIRTUAL_ENV"] = str(prefix)
            environment["PATH"] = (
                str(binary) + os.pathsep + environment.get("PATH", "")
            )
            if lease is not None:
                environment = lease.environment(environment)
                spawn_options = lease.subprocess_options()
            else:
                environment.pop("_APPRC_RUNTIME_LEASE_HANDLE", None)
                spawn_options = {}
        return subprocess.run(
            [str(command), *args],
            env=environment,
            check=False,
            **spawn_options,
        ).returncode
    finally:
        if lease is not None:
            lease.close()


def main() -> int:
    """Dispatch manager-only handoff before loading product/application code."""
    argv = list(sys.argv[1:])
    if argv and argv[0] == "--apprc-execute-handoff":
        if len(argv) != 2:
            raise ValueError("Native uninstall handoff arguments are invalid.")
        binding, _ = _read_product()
        from apprc.distribution.runtime.removal import execute_handoff

        execute_handoff(
            Path(argv[1]), expected_identity=binding.identity
        )
        return 0
    if argv and argv[0] == "--apprc-finalize-namespace":
        if len(argv) != 3:
            raise ValueError("Native namespace-finalizer arguments are invalid.")
        binding, _ = _read_product()
        from apprc.distribution.runtime.namespace_finalizer import (
            finalize_namespace,
        )

        finalize_namespace(
            Path(argv[1]),
            Path(argv[2]),
            expected_app_id=binding.identity.app_id,
        )
        return 0

    binding, _ = _read_product()
    executable = _executable()
    os.environ["_APPRC_NATIVE_MANAGER"] = "1"
    os.environ["_APPRC_NATIVE_EXECUTABLE"] = str(executable)
    application = _application(binding)
    manager = InstallationManager(application.schema, environment=dict(os.environ))
    owned = _owned_manager_invocation(executable, manager, binding)
    group = binding.maintenance_group_name
    core_actions = {
        "doctor", "paths", "repair", "uninstall", "migrate", "install"
    }
    group_args = None
    value_options = {
        "--env-file", "--log-level", "--workspace", "--layout", "--app-root"
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == group:
            group_args = argv[index + 1 :]
            break
        if token == "--":
            break
        if token.startswith("-"):
            option = token.split("=", maxsplit=1)[0]
            index += (
                2
                if option in value_options and "=" not in token
                else 1
            )
            continue
        break


    if (
        not owned
        and group_args is not None
        and group_args[:1] == ["install"]
        and any(option in group_args[1:] for option in ("-e", "--editable"))
    ):
        print(
            f"This setup executable cannot register an editable runtime. "
            f"Run `uv run --locked {binding.command_name} {group} install -e` "
            "from the checkout.",
            file=sys.stderr,
        )
        return 2
    if not owned and not argv:
        return _install(binding, manager, executable, ())
    if not owned and group_args is None and argv and argv[0] not in {
        "--help", "-h", "--version"
    }:
        return _install(binding, manager, executable, tuple(argv))

    if owned:
        if argv and argv[0] in {"--help", "-h", "--version"}:
            try:
                return _forward(binding, manager, argv)
            except (OSError, ValueError, RuntimeError):
                if argv == ["--version"]:
                    print(f"{binding.command_name} {binding.version}")
                    return 0
        elif group_args is None and argv:
            try:
                return _forward(binding, manager, argv)
            except (OSError, ValueError, RuntimeError) as error:
                print(
                    f"Application runtime is unavailable: {error}",
                    file=sys.stderr,
                )
                argv = ["--help"]
        elif group_args:
            if group_args[0] not in core_actions:
                try:
                    return _forward(binding, manager, argv)
                except (OSError, ValueError, RuntimeError) as error:
                    print(
                        f"Application runtime is unavailable: {error}",
                        file=sys.stderr,
                    )
                    argv = ["--help"]
            if group_args[0] == "install" and any(
                option in group_args[1:] for option in ("-e", "--editable")
            ):
                print(
                    f"This managed command cannot register an editable runtime. "
                    f"Run `uv run --locked {binding.command_name} "
                    f"{group} install -e` from the checkout.",
                    file=sys.stderr,
                )
                return 2
        elif not argv:
            try:
                return _forward(binding, manager, argv)
            except (OSError, ValueError, RuntimeError) as error:
                print(
                    f"Application runtime is unavailable: {error}",
                    file=sys.stderr,
                )
                argv = ["--help"]
    elif argv == ["--version"]:
        record = manager.inspect().record
        if record is not None and record.active_runtime is not None:
            try:
                return _forward(binding, manager, argv)
            except (OSError, ValueError, RuntimeError):
                pass
        print(f"{binding.command_name} {binding.version}")
        return 0
    elif argv and argv[0] in {"--help", "-h"}:
        record = manager.inspect().record
        if record is not None and record.active_runtime is not None:
            try:
                return _forward(binding, manager, argv)
            except (OSError, ValueError, RuntimeError):
                pass

    from apprc.interfaces.cli.mount import mount_app_cli
    from apprc.interfaces.cli._typer_utils import run_typer_app

    app = __import__("typer").Typer(no_args_is_help=True)
    mount_app_cli(
        app,
        application,
        maintenance_group_name=group,
        installation_management=True,
        native_binding=binding,
        installer_entrypoint=lambda values: _install(
            binding, manager, executable, tuple(values)
        ),
    )
    from apprc.interfaces.cli.context import _authenticated_native_manager_scope

    with _authenticated_native_manager_scope(executable):
        return run_typer_app(app, args=argv, prog_name=binding.command_name)


if __name__ == "__main__":
    raise SystemExit(main())
