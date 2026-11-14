"""Private request transport to the target interpreter's sole app bridge."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from apprc.definition.paths import ResourceKind
from typing import Any
from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    MigrationPlan,
    OperationContext,
    RuntimeSlot,
)

from apprc.distribution.runtime.acquisition import _assert_private_staging
from apprc.distribution.runtime.backend import (
    runtime_environment,
    runtime_interpreter,
    runtime_prefix,
)
from apprc.distribution.runtime._leases import (
    RuntimeLease,
    acquire_runtime_lease_locked,
    authorized_runtime_quiescence,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation.codec import _encode
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation

_ACTIONS = frozenset(
    {"probe", "initialize", "doctor", "inventory", "cleanup", "migrate"}
)

_LOADER = """import hashlib,sys,zipfile
executable,request,expected=sys.argv[1:4]
with open(executable,'rb') as stream:
 actual=hashlib.file_digest(stream,'sha256').hexdigest()
if actual != expected:
 raise RuntimeError('Manager executable changed before bridge dispatch')
with zipfile.ZipFile(executable) as archive:
 source=archive.read('apprc/distribution/runtime/installed_probe.py')
filename=executable+'/apprc/distribution/runtime/installed_probe.py'
namespace={'__name__':'_apprc_installed_probe','__file__':filename,'__package__':None,'__spec__':None}
exec(compile(source,filename,'exec'),namespace,namespace)
raise SystemExit(namespace['main'](['--request',request]))
"""


def _private_request_file(
    directory: Path,
    request: dict[str, object],
    forbidden_roots: tuple[Path, ...],
) -> Path:
    temporary_root = Path(tempfile.mkdtemp(prefix="apprc-request-"))
    try:
        _assert_private_staging(temporary_root)
        resolved = temporary_root.resolve()
        roots = (directory, *forbidden_roots)
        if any(
            resolved == root.resolve(strict=False)
            or resolved.is_relative_to(root.resolve(strict=False))
            for root in roots
        ):
            raise InstallationError(
                "Bridge request staging is inside a removal root."
            )
        path = temporary_root / "request.json"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                request,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except BaseException:
        import shutil

        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def application_bridge(
    directory: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    *,
    command_name: str,
    action: str,
    environment: dict[str, str],
    manager_executable: Path | None = None,
    expected_revision: str | None = None,
    runtime_options: dict[str, object] | None = None,
    operation_context: OperationContext | None = None,
    categories: frozenset[ResourceKind] = frozenset(),
    forget_retained: bool = False,
    migration_plan: MigrationPlan | None = None,
) -> dict[str, object]:
    """Execute one strict app-bridge request with the recorded interpreter.

    :param directory: Installation authority directory used by the bridge.
    :param identity: Saved application and distribution identities.
    :param runtime: Exact active managed slot or editable checkout.
    :param command_name: Saved primary console command.
    :param action: One fixed bridge action.
    :param environment: Captured environment with ordinary credentials preserved.
    :param runtime: Exact active managed slot or editable checkout, including its captured hooks.
    :param manager_executable: Optional manager whose verified ZIP contains the bridge.
    :param expected_revision: Authority revision for mutation validation.
    :param runtime_options: Encoded captured CLI options for application doctor.
    :param operation_context: Exact authorization for resource initialization.
    :param categories: Provider cleanup categories.
    :param forget_retained: Whether accepted cleanup forgets retained targets.
    :param migration_plan: Explicit resource migration authority.
    :return: The bridge's typed-by-action result object.
    """
    if action not in _ACTIONS:
        raise InstallationError("Unknown application bridge action.")
    if not command_name or command_name not in identity.commands:
        raise InstallationError("Bridge command does not match saved identity.")
    if runtime_options is None:
        from apprc.definition.resolution import _BridgeRuntimeOptions

        runtime_options_payload = _encode(_BridgeRuntimeOptions())
    else:
        runtime_options_payload = runtime_options
    request: dict[str, object] = {
        "action": action,
        "identity": _encode(identity),
        "command_name": command_name,
        "directory": str(directory),
        "expected_revision": expected_revision,
        "runtime_options": runtime_options_payload,
        "operation_context": _encode(operation_context)
        if operation_context is not None
        else None,
        "categories": sorted(categories),
        "forget_retained": forget_retained,
        "migration_plan": _encode(migration_plan)
        if migration_plan is not None
        else None,
        "hooks": _encode(runtime.hooks),
    }
    lease: RuntimeLease | None = None
    close_lease = True
    protected_roots: tuple[Path, ...] = ()
    with installation_lock(directory):
        inspection = inspect_installation(directory, app_id=identity.app_id)
        record = inspection.record
        if record is None or inspection.revision is None:
            raise InstallationError(
                "Bridge requires valid installation authority."
            )
        if (
            expected_revision is not None
            and inspection.revision != expected_revision
        ):
            raise InstallationError(
                "Installation changed before bridge runtime selection."
            )
        authorized_runtime = record.active_runtime
        operation = record.operation
        if operation is not None and operation.intended is not None:
            pending = operation.intended.runtime
            if pending == runtime and action in {"probe", "initialize"}:
                authorized_runtime = pending
        if authorized_runtime != runtime:
            raise InstallationError(
                "Bridge runtime is not the active or exact pending target."
            )
        placement = record.placement
        protected_roots = tuple(
            path
            for path in (
                placement.config_dir,
                placement.appdata_dir,
                placement.cache_dir,
                placement.state_dir,
                placement.logs_dir,
                *(resource.path for resource in placement.retired),
            )
            if path is not None
        )
        expected_revision = inspection.revision
        manager_digest: str | None = None
        if manager_executable is not None:
            if (
                not manager_executable.is_absolute()
                or not manager_executable.is_file()
            ):
                raise InstallationError(
                    "Saved manager executable is unavailable."
                )
            assert_no_links(manager_executable)
            with manager_executable.open("rb") as stream:
                manager_digest = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
            if manager_executable.resolve(strict=True).is_relative_to(
                directory.resolve(strict=False)
            ):
                owned_paths = {str(manager_executable)}
                try:
                    owned_paths.add(
                        str(manager_executable.relative_to(directory))
                    )
                except ValueError:
                    pass
                owned = next(
                    (
                        item
                        for item in record.owned_outputs
                        if item.path in owned_paths and item.digest is not None
                    ),
                    None,
                )
                if owned is None or owned.digest != manager_digest:
                    raise InstallationError(
                        "Saved manager executable differs from owned bytes."
                    )
        if isinstance(runtime, RuntimeSlot):
            slot_directory = directory / "runtimes" / str(runtime.slot_id)
            lease = authorized_runtime_quiescence(slot_directory)
            if lease is None:
                lease = acquire_runtime_lease_locked(slot_directory)
            else:
                close_lease = False
    if lease is not None:
        captured_environment = lease.environment(environment)
        spawn_options = lease.subprocess_options()
    else:
        captured_environment = dict(environment)
        spawn_options = {}
        captured_environment.pop("_APPRC_RUNTIME_LEASE_HANDLE", None)
    request["expected_revision"] = expected_revision
    forbidden = protected_roots + (
        (runtime.project, runtime.environment)
        if isinstance(runtime, EditableCheckout)
        else (runtime_prefix(directory, runtime).parent,)
    )
    try:
        request_path = _private_request_file(directory, request, forbidden)
    except BaseException:
        if lease is not None and close_lease:
            lease.close()
        raise
    try:
        interpreter = runtime_interpreter(directory, runtime)
        child_environment = runtime_environment(captured_environment)
        if lease is not None:
            child_environment = lease.environment(child_environment)
        prefix = runtime_prefix(directory, runtime)
        command_bin = prefix / ("Scripts" if os.name == "nt" else "bin")
        child_environment["VIRTUAL_ENV"] = str(prefix)
        child_environment["PATH"] = (
            str(command_bin) + os.pathsep + child_environment.get("PATH", "")
        )
        if manager_executable is not None:
            assert manager_digest is not None
            argv = [
                str(interpreter),
                "-I",
                "-c",
                _LOADER,
                str(manager_executable),
                str(request_path),
                manager_digest,
            ]
        else:
            bridge = Path(__file__).with_name("installed_probe.py")
            if not bridge.is_file():
                raise InstallationError(
                    "Installed SDK application bridge is unavailable."
                )
            argv = [
                str(interpreter),
                "-I",
                str(bridge),
                "--request",
                str(request_path),
            ]
        result = subprocess.run(
            argv,
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
            **spawn_options,
        )
        try:
            response: Any = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise InstallationError(
                f"Application bridge returned invalid {action} JSON."
            ) from error
        if (
            not isinstance(response, dict)
            or set(response) != {"action", "result"}
            or response["action"] != action
            or not isinstance(response["result"], dict)
        ):
            raise InstallationError(
                f"Application bridge returned an invalid {action} envelope."
            )
        if result.stderr:
            sys.stderr.write(result.stderr)
        payload = response["result"]
        if action == "doctor":
            checks = payload.get("checks")
            if (
                not isinstance(payload.get("status"), str)
                or not isinstance(checks, list)
                or any(
                    not isinstance(check, dict)
                    or not isinstance(check.get("status"), str)
                    for check in checks
                )
            ):
                raise InstallationError(
                    "Application doctor returned invalid failure JSON."
                )
            if result.returncode == 1 and payload["status"] != "error":
                raise InstallationError(
                    "Application doctor failed without valid failure checks."
                )
        elif result.returncode != 0:
            raise InstallationError(
                f"Application bridge {action} failed: {result.stderr.strip()}"
            )
        return payload
    finally:
        import shutil

        shutil.rmtree(request_path.parent, ignore_errors=True)
        if lease is not None and close_lease:
            lease.close()


def _probe_runtime_observations(
    directory: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    *,
    command_name: str,
    environment: dict[str, str],
    manager_executable: Path | None = None,
    expected_revision: str | None = None,
) -> tuple[RuntimeSlot | EditableCheckout, dict[str, object]]:
    """Return a validated runtime and its exact bridge observations."""
    import re

    from apprc.distribution.runtime.backend import (
        runtime_command,
        runtime_prefix,
    )

    result = application_bridge(
        directory,
        identity,
        runtime,
        command_name=command_name,
        action="probe",
        environment=environment,
        manager_executable=manager_executable,
        expected_revision=expected_revision,
    )
    fields = {
        "distribution",
        "version",
        "prefix",
        "interpreter",
        "python_version",
        "commands",
    }
    if not isinstance(result, dict) or set(result) != fields:
        raise InstallationError("Runtime probe returned incompatible metadata.")

    def normalized(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    if (
        not isinstance(result["distribution"], str)
        or normalized(result["distribution"])
        != normalized(identity.distribution)
        or not isinstance(result["version"], str)
        or not result["version"]
        or not isinstance(result["python_version"], str)
        or re.fullmatch(r"\d+\.\d+\.\d+", result["python_version"]) is None
        or not isinstance(result["prefix"], str)
        or not isinstance(result["interpreter"], str)
    ):
        raise InstallationError("Runtime probe identity or version is invalid.")
    prefix = Path(result["prefix"])
    expected_prefix = runtime_prefix(directory, runtime)
    if not prefix.is_absolute() or os.path.normcase(
        str(prefix.resolve(strict=False))
    ) != os.path.normcase(str(expected_prefix.resolve(strict=False))):
        raise InstallationError(
            "Runtime interpreter prefix differs from its recorded environment."
        )
    commands = result["commands"]
    if not isinstance(commands, dict) or set(commands) != set(
        identity.commands
    ):
        raise InstallationError(
            "Runtime probe command ownership is incomplete."
        )
    if any(
        not isinstance(value, str) or not value for value in commands.values()
    ):
        raise InstallationError(
            "Runtime probe returned invalid console entry points."
        )
    for command in identity.commands:
        if not runtime_command(directory, runtime, command).is_file():
            raise InstallationError(
                f"Runtime console command is missing: {command}."
            )
    if isinstance(runtime, EditableCheckout):
        return runtime, result
    if runtime.version is not None and runtime.version != result["version"]:
        raise InstallationError(
            "Installed version differs from the requested runtime version."
        )
    if (
        runtime.python_version is not None
        and runtime.python_version != result["python_version"]
    ):
        raise InstallationError(
            "Installed Python version differs from the requested runtime version."
        )
    return RuntimeSlot(
        runtime.slot_id,
        runtime.source,
        runtime.selection,
        result["version"],
        result["python_version"],
        runtime.hooks,
    ), result


def probe_runtime(
    directory: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    *,
    command_name: str,
    environment: dict[str, str],
    manager_executable: Path | None = None,
    expected_revision: str | None = None,
) -> RuntimeSlot | EditableCheckout:
    """Return a managed slot with actual interpreter/package observations."""
    observed, _metadata = _probe_runtime_observations(
        directory,
        identity,
        runtime,
        command_name=command_name,
        environment=environment,
        manager_executable=manager_executable,
        expected_revision=expected_revision,
    )
    return observed
