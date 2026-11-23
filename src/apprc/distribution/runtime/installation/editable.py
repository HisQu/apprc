"""Register an existing checkout and publish its commands."""

from __future__ import annotations


import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationInspection,
    InstallationIdentity,
    InstallationPlacement,
    OperationContext,
    OperationStep,
)
from apprc.distribution.runtime import _command_publication
from apprc.distribution.runtime._install_progress import report
from apprc.distribution.runtime._os_integration import (
    validate_command_directory,
    validate_global_command,
)
from apprc.distribution.runtime.backend import (
    runtime_command,
    runtime_environment,
    runtime_interpreter,
)
from apprc.distribution.runtime.probe import (
    _probe_runtime_observations,
)
from apprc.user_files.installation.coordination import installation_lock

from .commands import (
    command_filename,
    recorded_command_directory,
    select_command_directory,
)
from .resources import (
    capture_resource_snapshot,
    initialize_resources,
    report_resources,
)
from .transaction import (
    checkpoint,
    checkpoint_activation,
    commit_activation,
    recover_installation_failure,
    require_update_record,
)

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager


def register_editable_application(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: EditableCheckout,
    placement: InstallationPlacement,
    *,
    command_name: str,
    uv: Path,
    command_directory: Path | None = None,
    assume_yes: bool = False,
    expected_update: tuple[UUID, str] | None = None,
) -> InstallationInspection:
    """Register the existing checkout environment without managing its files."""
    if (
        not runtime.project.is_absolute()
        or not runtime.environment.is_absolute()
    ):
        raise InstallationError("Editable paths must be absolute.")
    from apprc.definition.resolution import resolve_editable_environment

    try:
        project = runtime.project.resolve(strict=True)
        environment_path = runtime.environment.resolve(strict=True)
        expected_environment = resolve_editable_environment(project)
        matches_project = expected_environment.samefile(environment_path)
        matches_interpreter = Path(sys.prefix).samefile(environment_path)
    except OSError as exc:
        raise InstallationError(
            f"Cannot access editable checkout {runtime.project} or environment "
            f"{runtime.environment}; running environment: {sys.prefix}. {exc}"
        ) from exc
    if not matches_project or not (project / "pyproject.toml").is_file():
        raise InstallationError(
            f"Editable registration requires environment {expected_environment}; "
            f"selected environment: {environment_path}."
        )
    runtime = EditableCheckout(project, environment_path, runtime.hooks)
    if not matches_interpreter:
        raise InstallationError(
            "The current interpreter is not this checkout's .venv. "
            f"Expected environment: {environment_path}; "
            f"running environment: {Path(sys.prefix).resolve(strict=True)}."
        )
    interpreter = runtime_interpreter(manager.directory, runtime)
    if not interpreter.is_file():
        raise InstallationError(
            f"Editable interpreter is unavailable: {interpreter}."
        )
    environment = manager.environment
    _validate_editable_metadata(interpreter, identity, environment)
    with installation_lock(manager.directory):
        prior = manager.inspect()
        previous = prior.record
        if expected_update is not None:
            previous = require_update_record(prior, expected_update)
            old = previous.active_runtime
            if (
                not isinstance(old, EditableCheckout)
                or previous.identity != identity
                or previous.command_name != command_name
                or not old.project.samefile(runtime.project)
                or not old.environment.samefile(runtime.environment)
            ):
                raise InstallationError(
                    "The requested update is for a different editable installation."
                )
            command_directory = recorded_command_directory(
                previous, manager.directory
            )
            if command_directory is None:
                raise InstallationError(
                    "The editable installation has no recorded command location."
                )
        if previous is not None and previous.status != "removed-retained":
            prior_runtime = previous.active_runtime
            same_checkout = isinstance(prior_runtime, EditableCheckout) and (
                prior_runtime.project.resolve(strict=False) == project
                and prior_runtime.environment.resolve(strict=False)
                == environment_path
            )
            if (
                prior_runtime is not None
                and not same_checkout
                and not assume_yes
            ):
                raise InstallationError(
                    "Switching installation ownership requires --yes confirmation."
                )
            if previous.operation is None:
                placement = previous.placement
        forbidden = (
            runtime.project,
            runtime.environment,
            runtime.environment.parent,
            manager.directory,
        )
        if expected_update is not None and command_directory is not None:
            validate_command_directory(
                command_directory,
                forbidden=forbidden,
                path_entries=(command_directory,),
            )
            selected_directory = command_directory
        else:
            selected_directory = select_command_directory(
                uv, command_directory, environment, forbidden
            )
        global_command = selected_directory / command_filename(command_name)
        prior_outputs = previous.owned_outputs if previous is not None else ()
        pending_publication = _command_publication.pending_publication(manager)
        publication_authority = _command_publication.authorized_outputs(
            pending_publication
        )
        validate_global_command(
            global_command,
            previous=(*prior_outputs, *publication_authority),
        )
        if previous is not None and previous.operation is not None:
            operation = previous.operation
            intended = operation.intended
            if (
                operation.kind not in {"install", "replace", "repair"}
                or intended is None
                or previous.identity != identity
                or intended.identity != identity
                or previous.command_name != command_name
                or intended.runtime != runtime
                or intended.placement != placement
                or operation.placement != placement
            ):
                raise InstallationError(
                    "Pending registration addresses another checkout."
                )
            # > Resume registration authority, not the developer-owned environment
            # > repair that the public managed-runtime planner deliberately rejects.
            plan = manager.plan_resume()
        else:
            plan = manager.plan_install(
                identity, runtime, placement, command_name=command_name
            )
        operation_id = plan.operation_id
        resources = capture_resource_snapshot(plan.target.placement)
        activation_started = False
        try:
            current = manager.begin_operation(plan)
            if current.revision is None:
                raise InstallationError(
                    "Pending editable registration has no revision."
                )
            observed, observations = _probe_runtime_observations(
                manager.directory,
                identity,
                runtime,
                command_name=command_name,
                environment=dict(environment),
                expected_revision=current.revision,
            )
            if not isinstance(observed, EditableCheckout):
                raise InstallationError(
                    "Editable probe returned a managed runtime."
                )
            revision = checkpoint(
                manager,
                operation_id,
                current.revision,
                OperationStep.RUNTIME_PREPARED,
            )
            revision = checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.RUNTIME_VALIDATED,
                observed,
            )
            context = OperationContext(
                manager.directory,
                operation_id,
                plan.generation_id,
                plan.target.placement,
            )
            report("result", "Checkout", "REUSED", project)
            report("result", "Environment", "REUSED", environment_path)
            report("detail", "Dependencies: not modified")
            version = str(observations["version"])
            report("version", version)
            if resources:
                report("stage", "Initializing Resources")
            initialized = initialize_resources(
                manager,
                identity,
                runtime,
                command_name,
                context,
                expected_revision=revision,
                manager_executable=None,
                expected_observations=observations,
            )
            revision = checkpoint(
                manager, operation_id, revision, OperationStep.RESOURCES_READY
            )
            report_resources(resources, initialized)
            report("stage", "Publishing Command")
            from apprc.distribution.runtime._windows_version import (
                versioned_executable,
            )

            command = runtime_command(manager.directory, runtime, command_name)
            publication_specs = (
                ((global_command, None, str(command)),)
                if os.name != "nt"
                else (
                    (
                        global_command,
                        versioned_executable(command.read_bytes(), version),
                        None,
                    ),
                )
            )
            published, revision = _command_publication.publish_commands(
                manager,
                operation_id,
                revision,
                publication_specs,
                prior_outputs=prior_outputs,
            )
            (output,) = published
            outputs = [
                *(item for item in prior_outputs if item.path != output.path),
                output,
            ]
            revision = checkpoint_activation(manager, operation_id, revision)
            activation_started = True
            return commit_activation(
                manager,
                operation_id=operation_id,
                revision=revision,
                observed=observed,
                outputs=outputs,
                command=global_command,
                version=version,
            )
        except BaseException as error:
            committed = recover_installation_failure(
                manager,
                plan,
                prior,
                error,
                resources=resources,
                activation_started=activation_started,
            )
            if committed is not None:
                return committed
            raise


def _validate_editable_metadata(
    interpreter: Path,
    identity: InstallationIdentity,
    environment: Mapping[str, str],
) -> None:
    """Inspect only installed distribution metadata before creating authority."""
    script = (
        "import importlib.metadata as m,json,sys;"
        "d=m.distribution(sys.argv[1]);"
        "e={p.name:p.value for p in d.entry_points if p.group=='console_scripts'};"
        "print(json.dumps({'distribution':d.metadata['Name'],'version':d.version,'commands':e}))"
    )
    result = subprocess.run(
        [str(interpreter), "-I", "-c", script, identity.distribution],
        env=runtime_environment(environment),
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstallationError(
            "Editable distribution metadata probe is invalid."
        ) from error
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("distribution"), str)
        or metadata["distribution"].lower().replace("_", "-")
        != identity.distribution.lower().replace("_", "-")
        or not isinstance(metadata.get("commands"), dict)
        or not set(identity.commands).issubset(metadata["commands"])
    ):
        raise InstallationError(
            "Editable environment does not own the declared distribution commands."
        )
