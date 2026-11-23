"""Guide a real installation lifecycle from the surviving checkout environment."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import typer

import apprc.utils as ut
from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationInspection,
    InstallationPlacement,
    RuntimeSlot,
)
from apprc.definition.resolution import CliRuntimeOptions, ResolveOptions
from apprc.distribution._release_assets import regular_setup_arguments
from apprc.distribution.frontends import _check_old_setup, _inspect_native_setup
from apprc.distribution.runtime._os_integration import validate_global_command
from apprc.distribution.runtime._uninstall_controller import (
    check_protected_removal_paths,
    run_checked_uninstall,
    verify_windows_registration,
)
from apprc.distribution.runtime.installation.commands import (
    select_command_directory,
)
from apprc.interfaces._terminal_console import cli_line
from apprc.interfaces.cli._distribution_authoring import (
    _check,
    _revision,
    _targets,
)
from apprc.interfaces.cli._typer_utils import click
from apprc.interfaces.cli.context import cli_runtime_options_to_args
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.planning import resource_roots

if TYPE_CHECKING:
    from apprc.distribution.models import NativeBinding
    from apprc.interfaces.cli._distribution_authoring import CheckoutAuthoring
    from apprc.public.app_rc import AppRC
    from apprc.services.installation import InstallationManager

_TIMEOUT = 300


def _manual_observation(answer: str) -> str:
    """Validate the manual observation using Typer's public prompt callback."""
    if answer not in {"pass", "fail", "skip"}:
        raise typer.BadParameter("Choose pass, fail, or skip.")
    return answer


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    capture: bool = False,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        check=True,
    )
    return result.stdout if capture else ""


def _verify_runtime(
    manager: InstallationManager,
    publication: Path,
    group: str,
    *,
    root: Path,
    prefix: Path,
    binding: NativeBinding | None,
    environment: dict[str, str],
    root_arguments: tuple[str, ...] = (),
) -> InstallationInspection:
    """Check saved runtime, the published command, and its diagnostics."""
    inspection = manager.inspect()
    record = inspection.record
    if inspection.status != "ready" or record is None:
        raise InstallationError("The test installation did not reach Ready.")
    active = record.active_runtime
    if binding is None:
        if not isinstance(active, EditableCheckout) or not (
            root.samefile(active.project)
            and prefix.samefile(active.environment)
        ):
            raise InstallationError(
                "The installed editable runtime differs from this checkout."
            )
    elif (
        not isinstance(active, RuntimeSlot)
        or record.identity != binding.identity
        or active.source != binding.source
        or active.version != binding.version
    ):
        raise InstallationError(
            "The managed runtime differs from the verified setup."
        )
    validate_global_command(publication, previous=record.owned_outputs)
    shell_environment = dict(environment)
    shell_environment.pop("VIRTUAL_ENV", None)
    shell_path = [
        item
        for item in environment.get("PATH", "").split(os.pathsep)
        if item and not Path(item).absolute().resolve().is_relative_to(prefix)
    ]
    shell_environment["PATH"] = os.pathsep.join(shell_path)
    selected = shutil.which(record.command_name, path=shell_environment["PATH"])
    if selected is None or Path(
        selected
    ).absolute().resolve() != publication.resolve(strict=True):
        raise InstallationError(
            "A fresh command lookup does not select the published test command."
        )
    doctor = json.loads(
        _run(
            [str(publication), *root_arguments, group, "doctor", "--json"],
            cwd=root.parent,
            environment=shell_environment,
            capture=True,
        )
    )
    if not isinstance(doctor, dict) or doctor.get("status") not in {
        "ok",
        "warning",
    }:
        raise InstallationError(
            "The installed application failed its health check."
        )
    verify_windows_registration(manager, publication, record, group)
    return inspection


def _check_setup_pair(
    authoring: CheckoutAuthoring,
    app_id: str,
    revision: str,
    older: Path | None,
) -> tuple[tuple[Path, NativeBinding], ...]:
    from packaging.version import Version

    (target,) = _targets(current=True)
    (setup,) = _check(
        authoring.backend(),
        authoring.root,
        revision=revision,
        targets=(target,),
    )
    binding = _inspect_native_setup(setup, app_id=app_id, target=target)
    for path in (setup,) if older is None else (setup, older):
        if not os.access(path, os.X_OK):
            raise InstallationError(
                f"Setup is not executable: {path}. Grant execute permission before testing."
            )
    if older is None:
        return ((setup, binding),)
    older = older.absolute()
    previous = _check_old_setup(older, app_id=app_id, target=target)
    if (
        previous.identity != binding.identity
        or previous.source.commit == binding.source.commit
        or Version(previous.version) >= Version(binding.version)
    ):
        raise InstallationError(
            "The old setup must contain an earlier version and a distinct commit for this application."
        )
    return ((older, previous), (setup, binding))


def run_distribution_test(
    ctx: typer.Context,
    authoring: CheckoutAuthoring,
    apprc: AppRC,
    group: str,
    command: str,
    *,
    managed: bool,
    update_from: Path | None,
    assume_yes: bool,
) -> None:
    """Run the selected profile and leave a report even on a failed step."""
    root = authoring.root
    prefix = Path(sys.prefix).resolve(strict=True)
    environment = dict(os.environ)
    options = ctx.meta.get(
        "apprc.distribution.runtime_options", CliRuntimeOptions()
    )
    if not isinstance(options, CliRuntimeOptions):
        raise InstallationError("Distribution runtime options are unavailable.")
    root_arguments = tuple(cli_runtime_options_to_args(options))
    manager = apprc.installation(environment=environment)
    report_dir = root / ".cache" / "apprc" / "dist-test"
    assert_no_links(report_dir)
    create_private_directory_if_missing(report_dir)
    report_file = report_dir / f"{uuid4().hex}.json"
    report: dict[str, object] = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "profile": "update"
        if update_from is not None
        else "managed"
        if managed
        else "editable",
        "status": "failed",
        "manual_observation": "not verified",
    }
    steps: list[str] = []
    report["passed_steps"] = steps
    write_bytes_atomic(report_file, b"{}\n", private=True)
    try:
        if not assume_yes and not sys.stdin.isatty():
            raise InstallationError(
                "Use an interactive terminal or pass --yes."
            )
        revision = _revision(root)
        report["commit"] = revision
        setups = (
            _check_setup_pair(
                authoring, manager.spec.app_id, revision, update_from
            )
            if managed
            else ()
        )
        report["artifacts"] = [
            {
                "file": path.name,
                "sha256": ut.sha256_file(path),
                "commit": binding.source.commit,
                "version": binding.version,
            }
            for path, binding in setups
        ]
        name = command + (".exe" if os.name == "nt" else "")
        checkout_command = (
            prefix / ("Scripts" if os.name == "nt" else "bin") / name
        )
        uv_command = shutil.which("uv")
        if not checkout_command.is_file() or uv_command is None:
            raise InstallationError(
                "The checkout console command and uv must be available."
            )
        uv = Path(uv_command).resolve(strict=True)
        inspection = manager.inspect()
        record = inspection.require_usable()
        if record is not None and assume_yes:
            raise InstallationError(
                "A pre-existing installation exists. Run interactively to review and uninstall it."
            )
        if inspection.status not in {"missing", "ready", "removed-retained"}:
            raise InstallationError(
                "Resolve the pending installation before running the test."
            )
        paths = apprc.paths(
            ResolveOptions(
                env_files=options.env_files,
                env_file_overrides_os_environ=options.env_file_overrides_os_environ,
                load_dotenv_layers=options.load_dotenv_layers,
                workspace=options.workspace,
                layout=options.layout,
            ),
            environment=environment,
        )
        placement = InstallationPlacement.from_paths(paths, apprc.schema.paths)
        resource_paths = tuple(path for _, path in resource_roots(placement))
        check_protected_removal_paths(resource_paths, (root, prefix))
        publication = (
            select_command_directory(
                uv,
                None,
                environment,
                (root, prefix, manager.directory, *resource_paths),
            )
            / name
        )
        validate_global_command(
            publication, previous=record.owned_outputs if record else ()
        )
        verify_windows_registration(
            manager, publication, record, group, required=False
        )
        if update_from is not None and placement.appdata_dir is None:
            raise InstallationError(
                "Update validation requires declared application data."
            )
        steps.append("preflight")
        retained: tuple[Path, ...] = ()
        if record is not None:
            cli_line(ctx, "Existing installation", path=inspection.directory)
            cli_line(
                ctx,
                "The test requires uninstalling it first. Review the Delete items and configuration choice.",
            )
            config_roots = tuple(
                path
                for kind, path in resource_roots(record.placement)
                if kind == "config"
            )
            inspection = run_checked_uninstall(
                checkout_command,
                group,
                manager,
                inspection,
                publication,
                (root, prefix),
                keep_config=False,
                assume_yes=False,
                root=root,
                environment=environment,
                report=report,
                root_arguments=root_arguments,
            )
            retained = tuple(path for path in config_roots if path.exists())
            report["retained_config_count"] = len(retained)
            for path in retained:
                cli_line(
                    ctx, "Final cleanup will preserve configuration", path=path
                )
            steps.append("pre-existing uninstall")
        elif not assume_yes and not typer.confirm(
            "Install and remove this application as a test?"
        ):
            raise typer.Abort()
        inspections: list[InstallationInspection] = []
        sentinel: Path | None = None
        sentinel_bytes = uuid4().hex.encode()
        for executable, binding in setups or ((checkout_command, None),):
            if manager.inspect().snapshot != (
                inspections[-1].snapshot if inspections else inspection.snapshot
            ):
                raise InstallationError(
                    "Installation authority changed during the test."
                )
            flags = [
                "--yes",
                "--skip-setup",
                "--command-directory",
                str(publication.parent),
            ]
            arguments = (
                [group, "install", "-e", *flags] if binding is None else flags
            )
            _run(
                [
                    str(executable),
                    *(
                        regular_setup_arguments(executable)
                        if binding is not None
                        else ()
                    ),
                    *root_arguments,
                    *arguments,
                ],
                cwd=root,
                environment=environment,
            )
            current = _verify_runtime(
                manager,
                publication,
                group,
                root=root,
                prefix=prefix,
                binding=binding,
                environment=environment,
                root_arguments=root_arguments,
            )
            active = current.record.active_runtime if current.record else None
            if len(setups) == 2:
                assert current.record is not None and isinstance(
                    active, RuntimeSlot
                )
                if not inspections:
                    appdata = current.record.placement.appdata_dir
                    assert appdata is not None
                    sentinel = appdata / f".apprc-dist-test-{uuid4().hex}"
                    assert_no_links(sentinel)
                    with sentinel.open("xb") as stream:
                        stream.write(sentinel_bytes)
                else:
                    previous = inspections[0].record
                    assert previous is not None and isinstance(
                        previous.active_runtime, RuntimeSlot
                    )
                    if (
                        active.slot_id == previous.active_runtime.slot_id
                        or sentinel is None
                        or sentinel.read_bytes() != sentinel_bytes
                    ):
                        raise InstallationError(
                            "The update did not activate a new slot and preserve the test data."
                        )
            inspections.append(current)
            steps.append(
                "install and verify"
                if len(inspections) == 1
                else "update and verify"
            )
        if not assume_yes:
            if os.name == "nt":
                cli_line(
                    ctx,
                    "Check the application entry in Windows Settings / Installed apps.",
                )
            cli_line(
                ctx,
                "Launch and check the application from a fresh shell",
                path=publication,
            )
            choice = typer.prompt(
                "Application launch and functional check (pass/fail/skip)",
                default="skip",
                value_proc=_manual_observation,
            )
            report["manual_observation"] = (
                "not verified" if choice == "skip" else choice
            )
        run_checked_uninstall(
            checkout_command,
            group,
            manager,
            inspections[-1],
            publication,
            (root, prefix, *retained),
            keep_config=bool(retained),
            assume_yes=assume_yes,
            root=root,
            environment=environment,
            report=report,
            root_arguments=root_arguments,
        )
        if not checkout_command.is_file() or any(
            not path.exists() for path in retained
        ):
            raise InstallationError(
                "Final cleanup removed the checkout environment or retained configuration."
            )
        steps.append("final uninstall")
        if report["manual_observation"] == "fail":
            raise InstallationError(
                "The application did not pass the manual check."
            )
        report["status"] = "passed"
    except typer.Abort:
        report["status"] = "declined"
        raise
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        report["error_type"] = type(error).__name__
        raise click.ClickException(str(error)) from error
    finally:
        write_bytes_atomic(
            report_file,
            (json.dumps(report, indent=2) + "\n").encode(),
            private=True,
        )
        cli_line(ctx, "Distribution test report", path=report_file)
        recovery = report.get("uninstall_recovery")
        if isinstance(recovery, str):
            cli_line(ctx, "Uninstall recovery", path=recovery, error=True)
