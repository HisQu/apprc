"""Guide a real installation lifecycle from the surviving checkout environment."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import typer
from typer._click import ClickException
from typer._types import TyperChoice

import apprc.utils as ut
from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    RuntimeSlot,
)
from apprc.distribution.frontends import _check_old_setup, _inspect_native_setup
from apprc.distribution.runtime._os_integration import (
    capture_windows_registration,
    validate_global_command,
    windows_registration_intent,
)
from apprc.distribution.runtime._uninstall_controller import prepare_uninstall
from apprc.distribution.runtime.installation import _command_directory
from apprc.interfaces._terminal_console import cli_line
from apprc.interfaces.cli._distribution_command import (
    _check,
    _revision,
    _targets,
)
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
    set_windows_private_acl,
)
from apprc.user_files.installation.planning import resource_roots

if TYPE_CHECKING:
    from apprc.distribution.models import NativeBinding
    from apprc.interfaces.cli._distribution_command import CheckoutAuthoring
    from apprc.public.app_rc import AppRC
    from apprc.services.installation import InstallationManager

_TIMEOUT = 300


def _windows_entry(
    manager: InstallationManager,
    publication: Path,
    record: InstallationRecord | None,
    group: str,
    *,
    required: bool = True,
) -> None:
    """Verify the saved current-user key, or require absence without authority."""
    if os.name != "nt":
        return
    entry = None
    if record is not None:
        expected = windows_registration_intent(
            manager.directory,
            record.identity,
            publication,
            maintenance_group_name=group,
        )
        entry = next(
            (
                item
                for item in record.owned_outputs
                if item.kind == "hkcu" and item.path == expected.path
            ),
            None,
        )
    if entry is not None:
        current = capture_windows_registration(entry)
        if current is not None and current.values is not None:
            if not required or {
                name: value for name, value, _ in current.values
            } == dict(entry.values):
                return
        if required:
            raise InstallationError(
                "Windows uninstall registration is missing or incomplete."
            )
        return
    if required and record is not None:
        raise InstallationError(
            "The installation has no recorded Windows uninstall entry."
        )
    import winreg

    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{manager.spec.app_id}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise InstallationError(
                "An unowned Windows uninstall entry exists."
            )
    except FileNotFoundError:
        pass


def _protected_paths(
    deleted: tuple[Path, ...], protected: tuple[Path, ...]
) -> None:
    """Reject removals overlapping the runner or retained configuration."""
    for path in deleted:
        for survivor in protected:
            if survivor.is_relative_to(path) or path.is_relative_to(survivor):
                raise InstallationError(
                    f"Removal overlaps a protected path: {survivor}"
                )


def _await_uninstall(
    manager: InstallationManager,
    staging: Path,
    previous: InstallationRecord,
    publication: Path,
    group: str,
    *,
    timeout: float = _TIMEOUT,
) -> InstallationInspection:
    """Wait for the specific handoff's staging to retire, then verify authority."""
    deadline = time.monotonic() + timeout
    while any(staging.glob("apprc-uninstall-*")):
        if time.monotonic() >= deadline:
            raise InstallationError(
                f"Uninstall did not finish. Recovery is under {staging}."
            )
        time.sleep(0.1)
    result = manager.inspect()
    if result.status not in {"missing", "removed-retained"} or (
        result.record is not None
        and result.record.generation_id != previous.generation_id
    ):
        raise InstallationError(
            "Uninstall did not retire the expected installation."
        )
    if any(
        os.path.lexists(item.path)
        for item in previous.owned_outputs
        if item.kind in {"command", "shortcut"}
    ):
        raise InstallationError(
            "Uninstall left published commands or shortcuts."
        )
    _windows_entry(manager, publication, None, group)
    return result


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


def _uninstall(
    command: Path,
    group: str,
    manager: InstallationManager,
    expected: InstallationInspection,
    publication: Path,
    protected: tuple[Path, ...],
    *,
    keep_config: bool,
    assume_yes: bool,
    root: Path,
    environment: dict[str, str],
    report: dict[str, object],
) -> InstallationInspection:
    """Use normal uninstall and retain private recovery files on an incomplete run."""
    if expected.record is None:
        raise InstallationError(
            "Uninstall requires the previously verified authority."
        )
    preview = prepare_uninstall(
        manager.directory, keep_config=keep_config or None
    )
    if (
        not preview.can_execute
        or preview.plan is None
        or preview.inspection.snapshot != expected.snapshot
    ):
        raise InstallationError(
            "Uninstall preview is unsafe or installation authority changed."
        )
    _protected_paths(
        tuple(entry.path for entry in preview.plan.inventory.entries), protected
    )
    parent = Path(
        tempfile.mkdtemp(
            prefix="apprc-dist-test-", dir=Path(tempfile.gettempdir()).resolve()
        )
    )
    report["uninstall_recovery"] = str(parent)
    assert_no_links(parent)
    if os.name == "nt":
        set_windows_private_acl(parent)
    flags = ["--keep-config"] if keep_config else []
    if assume_yes:
        flags.append("--yes")
    _run(
        [str(command), group, "uninstall", *flags],
        cwd=root,
        environment={
            **environment,
            **dict.fromkeys(("TMPDIR", "TMP", "TEMP"), str(parent)),
        },
    )
    result = _await_uninstall(
        manager, parent, expected.record, publication, group
    )
    if not any(parent.iterdir()):
        parent.rmdir()
    report.pop("uninstall_recovery")
    return result


def _verify_runtime(
    manager: InstallationManager,
    publication: Path,
    group: str,
    *,
    root: Path,
    prefix: Path,
    binding: NativeBinding | None,
    environment: dict[str, str],
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
            [str(publication), group, "doctor", "--json"],
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
    _windows_entry(manager, publication, record, group)
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
        paths = apprc.paths(environment=environment)
        placement = InstallationPlacement.from_paths(paths, apprc.schema.paths)
        resource_paths = tuple(path for _, path in resource_roots(placement))
        _protected_paths(resource_paths, (root, prefix))
        publication = (
            _command_directory(
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
        _windows_entry(manager, publication, record, group, required=False)
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
            inspection = _uninstall(
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
                [str(executable), *arguments], cwd=root, environment=environment
            )
            current = _verify_runtime(
                manager,
                publication,
                group,
                root=root,
                prefix=prefix,
                binding=binding,
                environment=environment,
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
                type=TyperChoice(["pass", "fail", "skip"]),
            )
            report["manual_observation"] = (
                "not verified" if choice == "skip" else choice
            )
        _uninstall(
            publication,
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
        raise ClickException(str(error)) from error
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
