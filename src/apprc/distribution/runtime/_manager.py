"""Native AppRC manager entrypoint shared by setup and installed executables."""

from __future__ import annotations

import hashlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from collections.abc import Callable
from typing import cast
from uuid import UUID, uuid4
from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    OwnedOutput,
    RuntimeSlot,
)
from apprc.distribution.models import NativeBinding
from apprc.distribution.runtime._native_product import (
    check_other_product_paths,
    read_products,
)
from apprc.services.installation import InstallationManager


def _executable() -> Path:
    value = os.environ.get("PYAPP")
    if not value:
        raise RuntimeError("PyApp did not provide the executing manager path.")
    return Path(value).absolute()


def _read_products(
    *, include_project: bool = False
) -> tuple[NativeBinding, NativeBinding | None, bytes | None]:
    return read_products(
        _executable(),
        globals().get("_APPRC_ARCHIVE_SIZE"),
        globals().get("_APPRC_ARCHIVE_SHA256"),
        include_project=include_project,
    )


def _read_product(
    *,
    include_project: bool = False,
    identity: InstallationIdentity | None = None,
) -> tuple[NativeBinding, bytes | None]:
    regular, preview, project = _read_products(include_project=include_project)
    if identity is None or identity == regular.identity:
        return regular, project
    if preview is not None and identity == preview.identity:
        return preview, project
    raise InstallationError("Saved identity is absent from the native product.")


def _application(binding: NativeBinding):
    from apprc import AppRC

    return AppRC(
        app_id=binding.identity.app_id,
        display_name=binding.display_name,
        paths=binding.capabilities.paths,
        layout=binding.layout,
        bootstrap_env_prefix=binding.bootstrap_env_prefix,
        command_name=binding.command_name,
        update_alias=binding.capabilities.update_alias,
    )


def _manager_uv() -> Path:
    """Resolve only the uv package and executable owned by this manager."""
    uv = importlib.import_module("uv")
    package_file = vars(uv).get("__file__")
    find_uv_bin = vars(uv).get("find_uv_bin")
    if not isinstance(package_file, str) or not callable(find_uv_bin):
        raise RuntimeError("The manager-owned uv package is unavailable.")
    executable_file = cast(Callable[[], object], find_uv_bin)()
    if not isinstance(executable_file, str):
        raise RuntimeError("The manager-owned uv executable is unavailable.")
    prefix = Path(sys.prefix).resolve(strict=True)
    package = Path(package_file).resolve(strict=True)
    executable = Path(executable_file).resolve(strict=True)
    if not package.is_relative_to(prefix) or not executable.is_relative_to(
        prefix
    ):
        raise RuntimeError("The manager-owned uv executable is unavailable.")
    return executable


def _setup_launch() -> dict[str, bool]:
    """Return the startup state supplied by the Windows Python loader."""
    state = globals().get("_APPRC_SETUP_LAUNCH")
    return cast(dict[str, bool], state) if isinstance(state, dict) else {}


def _install(
    binding: NativeBinding,
    manager: InstallationManager,
    executable: Path,
    args: tuple[str, ...],
    *,
    regular: NativeBinding | None = None,
    preview: NativeBinding | None = None,
    smoke: bool = False,
) -> int:
    """Render native setup progress and report its terminal outcome."""
    _setup_launch()["install"] = True
    from apprc.distribution.runtime._install_progress import (
        installation_progress,
    )
    from apprc.interfaces.cli._installation_output import (
        InstallationProgressOutput,
    )
    from apprc.interfaces.cli.installation_command import (
        _installation_error_message,
    )

    output = InstallationProgressOutput(None, binding.display_name, "managed")
    try:
        with installation_progress(output):
            if smoke:
                assert regular is not None
                _run_preview_smoke(binding, regular, manager, executable, args)
                from apprc.interfaces._terminal_console import cli_line

                cli_line(
                    None, "Preview smoke passed. The preview was uninstalled."
                )
                return 0
            next_step, _ = _install_managed(
                binding,
                manager,
                executable,
                args,
                regular=regular,
                preview=preview,
            )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        if (
            os.name == "nt"
            and isinstance(error, PermissionError)
            and error.filename
        ):
            output.failed(
                error.strerror or "Access denied",
                path=error.filename,
                notes=tuple(getattr(error, "__notes__", ())),
            )
        else:
            output.failed(_installation_error_message(error))
        if os.name == "nt":
            from apprc.distribution.runtime._setup_terminal import (
                setup_diagnostic,
            )
            from apprc.interfaces._terminal_console import cli_line

            diagnostic = setup_diagnostic(
                output.stage or "Preparing Runtime", error
            )
            if diagnostic is not None:
                cli_line(
                    None, "Setup diagnostic log", path=diagnostic, error=True
                )
        return 1
    output.complete(next_step=next_step)
    return 0


def _install_managed(
    binding: NativeBinding,
    manager: InstallationManager,
    executable: Path,
    args: tuple[str, ...],
    *,
    regular: NativeBinding | None = None,
    preview: NativeBinding | None = None,
    smoke_command_directory: Path | None = None,
) -> tuple[str | None, InstallationInspection]:
    """Install the embedded project, offer optional setup, and return its hint."""
    import argparse
    import logging

    from apprc.distribution.runtime._install_progress import warn
    from apprc.definition.paths import Layout
    from apprc.definition.resolution import ResolveOptions
    from apprc.distribution.runtime.installation import (
        _default_command_directory,
        install_application,
        installation_maintenance_group,
    )
    from apprc.interfaces.cli.context import CliRuntimeOptions
    from apprc.user_files.app_home.layouts import resolve_app_paths

    from apprc.interfaces.cli.options import native_runtime_parser

    runtime_parser = native_runtime_parser()
    parser = argparse.ArgumentParser(add_help=False, parents=[runtime_parser])
    parser.add_argument("--command-directory", type=Path)
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument("--start-menu", action="store_true")
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--apprc-update-generation", type=UUID)
    parser.add_argument("--apprc-update-revision")
    options, extras = parser.parse_known_args(args)
    if extras:
        raise ValueError(
            "Native install received unsupported arguments: " + " ".join(extras)
        )

    generation, revision = (
        options.apprc_update_generation,
        options.apprc_update_revision,
    )
    if (generation is None) != (revision is None):
        raise InstallationError("Incomplete installation identity for update.")
    expected_update = (
        (generation, revision)
        if generation is not None and revision is not None
        else None
    )

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
    environment = dict(manager.environment)
    if regular is not None and (
        options.layout is not None
        or options.app_root is not None
        or options.env_file
        or options.workspace is not None
        or _preview_has_path_overrides(manager)
    ):
        raise InstallationError("Preview uses fixed native application paths.")
    previous = manager.inspect().record
    if previous is not None and (
        previous.identity != binding.identity
        or previous.command_name != binding.command_name
    ):
        raise RuntimeError(
            "Saved installation belongs to another native product."
        )
    from apprc.definition.installation import EditableCheckout

    if (
        _setup_launch().get("dedicated", False)
        and not options.yes
        and previous is not None
        and previous.status == "ready"
        and previous.operation is None
        and isinstance(previous.active_runtime, EditableCheckout)
    ):
        import typer
        from apprc.interfaces._terminal_console import cli_line

        cli_line(
            None,
            "Existing editable checkout",
            path=previous.active_runtime.project,
        )
        if not typer.confirm(
            "Switch to a managed installation and keep the checkout files?",
            default=False,
        ):
            raise InstallationError(
                "Setup cancelled. The editable installation was kept."
            )
        options.yes = True
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

        placement = InstallationPlacement.from_paths(
            paths, binding.capabilities.paths
        )

    if regular is not None and placement.layout != Layout.native():
        raise InstallationError("Preview uses fixed native application paths.")

    uv = _manager_uv()
    command_directory = options.command_directory
    if smoke_command_directory is not None:
        command_directory = smoke_command_directory
    elif (
        expected_update is None
        and regular is not None
        and os.name != "nt"
        and command_directory is None
    ):
        command_directory = _default_command_directory(uv, environment)
    _, project_bytes = _read_product(include_project=True)
    if project_bytes is None:
        raise RuntimeError("The embedded project snapshot is unavailable.")
    metadata_path = (
        PurePosixPath(binding.source.project_path) / "pyproject.toml"
    )
    try:
        with zipfile.ZipFile(io.BytesIO(project_bytes)) as snapshot:
            metadata = tomllib.loads(
                snapshot.read(metadata_path.as_posix()).decode("utf-8")
            )
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError(
            "Cannot read the embedded project metadata."
        ) from error
    try:
        settings = metadata["tool"]["apprc"]["distribution"]
        hint = (
            settings["preview"]["install-next-step"]
            if regular is not None
            else settings["install-next-step"]
        )
    except (KeyError, TypeError):
        hint = None
    next_step = (hint.strip() or None) if isinstance(hint, str) else None

    other_product = regular or preview
    temp_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    with tempfile.TemporaryDirectory(
        prefix="apprc-native-project-", dir=temp_parent
    ) as stage:
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
                setup_version=binding.version,
                project_archive=project_archive,
                manager_executable=executable,
                uv=uv,
                command_directory=command_directory,
                assume_yes=options.yes or smoke_command_directory is not None,
                require_fresh=smoke_command_directory is not None,
                other_app_id=other_product.identity.app_id
                if other_product is not None
                else None,
                reserve_other_native_paths=preview is not None,
                expected_update=expected_update,
            )

    if smoke_command_directory is not None:
        return None, inspection

    from apprc.distribution.runtime.installation import (
        confirm_desktop_shortcut,
        offer_configuration_setup,
        publish_optional_shortcuts,
    )
    from apprc.distribution.runtime._install_progress import installation_color
    from apprc.interfaces._terminal_console import color_environment

    inspection.require_usable()
    try:
        offer_configuration_setup(
            inspection,
            skip=options.skip_setup,
            config_group_name=binding.config_group_name,
            runtime_options=captured_options,
            environment=color_environment(
                environment, installation_color.get()
            ),
            raise_on_failure=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        warn(
            logging.getLogger(__name__),
            f"Configuration setup failed. Run `{binding.command_name} {binding.config_group_name} setup` to retry",
            error,
        )

    if previous is None and not options.desktop:
        options.desktop = confirm_desktop_shortcut(
            binding.identity, assume_yes=options.yes
        )
    if options.start_menu or options.desktop:
        try:
            publish_optional_shortcuts(
                manager,
                manager.directory
                / (binding.command_name + (".exe" if os.name == "nt" else "")),
                binding.identity,
                display_name=binding.display_name,
                start_menu=options.start_menu,
                desktop=options.desktop,
                launch_enabled=binding.launch_enabled,
            )
        except (OSError, ValueError) as error:
            warn(
                logging.getLogger(__name__),
                "Optional shortcuts were not updated",
                error,
            )
    return next_step, inspection


def _preview_has_path_overrides(manager: InstallationManager) -> bool:
    return any(
        manager.environment.get(key, "").strip()
        for key in (manager.spec.layout_env_key, manager.spec.root_env_key)
    )


def _run_preview_smoke(
    binding: NativeBinding,
    regular: NativeBinding,
    manager: InstallationManager,
    executable: Path,
    args: tuple[str, ...],
) -> None:
    from apprc.distribution.runtime._install_progress import report
    from apprc.distribution.runtime._uninstall_controller import (
        _recorded_manager_executable,
        run_checked_uninstall,
        verify_windows_registration,
    )
    from apprc.distribution.runtime.installation import _command_filename
    from apprc.user_files.app_home.permissions import (
        set_windows_private_acl,
    )

    if any(arg not in {"--yes", "-y", "--skip-setup"} for arg in args):
        raise InstallationError(
            "Smoke uses automatic setup and accepts no placement or shortcut options."
        )
    command_dir = Path(
        tempfile.mkdtemp(
            prefix="apprc-preview-smoke-",
            dir=Path(tempfile.gettempdir()).resolve(strict=True),
        )
    )
    try:
        if os.name == "nt":
            set_windows_private_acl(command_dir)
        environment = dict(manager.environment)
        environment["PATH"] = (
            str(command_dir) + os.pathsep + environment.get("PATH", "")
        )
        manager = InstallationManager(manager.spec, environment=environment)
        _, installed = _install_managed(
            binding,
            manager,
            executable,
            (),
            regular=regular,
            smoke_command_directory=command_dir,
        )
        record = installed.record
        command = command_dir / _command_filename(binding.command_name)
        if record is None:
            raise InstallationError(
                "Smoke did not reach an identifiable preview generation."
            )
        report_data: dict[str, object] = {}
        verification_error: Exception | None = None
        try:
            report("stage", "Verifying Preview Runtime")
            runtime = record.active_runtime
            if (
                installed.status != "ready"
                or record.identity != binding.identity
                or not isinstance(runtime, RuntimeSlot)
                or runtime.source != binding.source
                or runtime.version != binding.version
                or manager.inspect().snapshot != installed.snapshot
            ):
                raise InstallationError(
                    "Smoke did not install the expected preview runtime."
                )
            if not _owned_manager_invocation(command, manager, binding):
                raise InstallationError(
                    "Smoke command publication is missing or modified."
                )
            verify_windows_registration(
                manager, command, record, binding.maintenance_group_name
            )
            if (
                _forward(
                    binding,
                    manager,
                    ["--version"],
                    expected_revision=installed.revision,
                )
                != 0
            ):
                raise InstallationError(
                    "The preview runtime could not report its version."
                )
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ) as error:
            verification_error = error
        finally:
            report("stage", "Removing Preview")
            try:
                stable = _recorded_manager_executable(record, manager.directory)
                if stable is None:
                    raise InstallationError(
                        "No authenticated preview executable is available for cleanup."
                    )
                removed = run_checked_uninstall(
                    stable,
                    binding.maintenance_group_name,
                    manager,
                    installed,
                    command,
                    (),
                    keep_config=False,
                    assume_yes=True,
                    root=command_dir,
                    environment=environment,
                    report=report_data,
                )
                if removed.status != "missing":
                    raise InstallationError(
                        "Smoke uninstall retained preview resources."
                    )
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.CalledProcessError,
            ) as error:
                recovery = report_data.get("uninstall_recovery")
                detail = (
                    f" Recovery files are under {recovery}." if recovery else ""
                )
                failure = InstallationError(
                    f"Preview cleanup is incomplete at {manager.directory}. {error}{detail}"
                )
                if verification_error is not None:
                    failure.add_note(
                        f"Preview verification also failed: {verification_error}"
                    )
                raise failure from error
        if verification_error is not None:
            raise verification_error
    finally:
        # > A failed handoff may still need the recorded published output.
        if not any(command_dir.iterdir()):
            command_dir.rmdir()


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
    binding: NativeBinding,
    manager: InstallationManager,
    args: list[str],
    *,
    expected_revision: str | None = None,
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
            if (
                record is None
                or record.active_runtime is None
                or record.identity != binding.identity
                or (
                    expected_revision is not None
                    and inspection.revision != expected_revision
                )
            ):
                raise RuntimeError(
                    "The application runtime is unavailable; use app doctor or repair."
                )
            runtime = record.active_runtime
            command = runtime_command(
                manager.directory, runtime, record.command_name
            )
            environment = runtime_environment(manager.environment)
            if isinstance(runtime, RuntimeSlot):
                prefix = (
                    manager.directory
                    / "runtimes"
                    / str(runtime.slot_id)
                    / ".venv"
                )
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
    if argv and argv[0].startswith("--apprc-"):
        _setup_launch()["dispatched"] = True
    regular, preview, _ = _read_products()
    if argv and argv[0] == "--apprc-execute-handoff":
        if len(argv) != 2:
            raise ValueError("Native uninstall handoff arguments are invalid.")
        from apprc.distribution.runtime.uninstall_handoff import execute_handoff

        execute_handoff(
            Path(argv[1]),
            expected_identity=regular.identity,
            preview_identity=preview.identity if preview is not None else None,
        )
        return 0
    if argv and argv[0] == "--apprc-finalize-namespace":
        if len(argv) != 3:
            raise ValueError(
                "Native namespace-finalizer arguments are invalid."
            )
        from apprc.distribution.runtime.namespace_finalizer import (
            finalize_namespace,
        )

        finalize_namespace(
            Path(argv[1]),
            Path(argv[2]),
            expected_app_id=regular.identity.app_id,
            preview_app_id=preview.identity.app_id
            if preview is not None
            else None,
        )
        return 0

    executable = _executable()
    os.environ["_APPRC_NATIVE_MANAGER"] = "1"
    os.environ["_APPRC_NATIVE_EXECUTABLE"] = str(executable)
    from apprc.distribution.runtime.installation import _command_filename

    _setup_launch()["dispatched"] = True
    environment = dict(os.environ)
    preview_command = preview is not None and (
        os.path.normcase(executable.name)
        == os.path.normcase(_command_filename(preview.command_name))
    )
    regular_command = os.path.normcase(executable.name) == os.path.normcase(
        _command_filename(regular.command_name)
    )
    setup_flags = {"-p", "--preview", "-s", "--smoke"}
    if (
        not preview_command
        and not regular_command
        and argv
        and argv[0] in setup_flags
    ):
        if preview is None:
            print(
                "This setup does not declare a preview product.",
                file=sys.stderr,
            )
            return 2
        smoke = False
        while argv and argv[0] in setup_flags:
            smoke = argv.pop(0) in {"-s", "--smoke"} or smoke
        return _install(
            preview,
            InstallationManager(
                _application(preview).schema, environment=environment
            ),
            executable,
            tuple(argv),
            regular=regular,
            smoke=smoke,
        )

    binding = preview if preview_command and preview is not None else regular
    application = _application(binding)
    manager = InstallationManager(application.schema, environment=environment)
    owned = _owned_manager_invocation(executable, manager, binding)
    if preview_command and not owned:
        print(
            "This preview command has no matching installation authority.",
            file=sys.stderr,
        )
        return 2
    if not owned and preview is not None and argv in (["--help"], ["-h"]):
        print("Native setup options:")
        print("  -p, --preview  Install or update the preview.")
        print("  -s, --smoke    Install, check, and uninstall a fresh preview.")
        print()
    group = binding.maintenance_group_name
    core_actions = {
        "doctor",
        "paths",
        "repair",
        "uninstall",
        "migrate",
        "install",
        "update",
    }
    group_args = None
    value_options = {
        "--env-file",
        "--log-level",
        "--workspace",
        "--layout",
        "--app-root",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == group:
            group_args = argv[index + 1 :]
            break
        if owned and token == "update" and binding.capabilities.update_alias:
            group_args = argv[index:]
            break
        if token == "--":
            break
        if token.startswith("-"):
            option = token.split("=", maxsplit=1)[0]
            index += 2 if option in value_options and "=" not in token else 1
            continue
        break

    if preview_command:
        if group_args is not None and group_args[:1] in (
            ["uninstall"],
            ["repair"],
        ):
            from apprc.user_files.installation.planning import resource_roots

            record = manager.inspect().record
            if record is not None:
                try:
                    check_other_product_paths(
                        (
                            manager.directory,
                            *(
                                path
                                for _, path in resource_roots(record.placement)
                            ),
                        ),
                        regular.identity.app_id,
                        environment,
                    )
                except InstallationError as error:
                    print(error, file=sys.stderr)
                    return 1
        if (
            _preview_has_path_overrides(manager)
            or any(
                token.split("=", 1)[0]
                in {"--layout", "--app-root", "--env-file", "--workspace"}
                for token in argv
            )
            or (group_args is not None and group_args[:1] == ["migrate"])
        ):
            print(
                "Preview uses fixed native application paths.", file=sys.stderr
            )
            return 2

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
        return _install(binding, manager, executable, (), preview=preview)
    if (
        not owned
        and group_args is None
        and argv
        and argv[0] not in {"--help", "-h", "--version"}
    ):
        return _install(
            binding, manager, executable, tuple(argv), preview=preview
        )

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

    import typer

    from apprc.interfaces.cli.mount import mount_app_cli
    from apprc.interfaces.cli._typer_utils import run_typer_app

    app = typer.Typer(no_args_is_help=True)
    mount_app_cli(
        app,
        application,
        maintenance_group_name=group,
        config_group_name=binding.config_group_name,
        installation_management=True,
        native_binding=binding,
        installer_entrypoint=lambda values: _install(
            binding,
            manager,
            executable,
            tuple(values),
            regular=regular if preview_command else None,
            preview=None if preview_command else preview,
        ),
    )
    from apprc.interfaces.cli.context import _authenticated_native_manager_scope

    try:
        with _authenticated_native_manager_scope(executable):
            run_typer_app(app, args=argv, prog_name=binding.command_name)
    except typer.Exit as exit_request:
        return exit_request.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
