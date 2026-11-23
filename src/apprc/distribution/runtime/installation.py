"""Transactional managed runtime installation and editable registration."""

from __future__ import annotations

import apprc.utils as ut

import contextvars
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, TextIO
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from apprc.definition.installation import (
    EditableCheckout,
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstallationRecord,
    InstallationWriteAuthority,
    InstallPlan,
    InstallationIdentity,
    InstallationPlacement,
    OperationContext,
    OperationStep,
    OwnedOutput,
    RuntimeSlot,
)
from apprc.definition.paths import ResourceKind
from apprc.distribution.runtime import _command_publication
from apprc.distribution.runtime._install_progress import report, warn
from apprc.distribution.runtime._os_integration import (
    command_is_owned,
    validate_command_directory,
    validate_global_command,
)
from apprc.distribution.runtime._leases import (
    RuntimeLease,
    acquire_runtime_lease,
    try_acquire_runtime_quiescence,
    try_retire_runtime_slot,
)
from apprc.distribution.runtime.acquisition import (
    materialize_project_snapshot,
)
from apprc.distribution.runtime.backend import (
    runtime_command,
    runtime_environment,
    runtime_interpreter,
    runtime_prefix,
    sync_runtime_slot,
)
from apprc.distribution.runtime.probe import (
    _probe_runtime_observations,
    application_bridge,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.writes import (
    file_revision,
    managed_lock_path,
    managed_write_lock,
)
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.planning import resource_roots
from apprc.user_files.installation.operations import _matches_candidate

if TYPE_CHECKING:
    from apprc.definition.resolution import CliRuntimeOptionsProtocol
    from apprc.services.installation import InstallationManager

LOG = logging.getLogger(__name__)

_ResourceSnapshot = tuple[
    tuple[Path, ResourceKind | None, bool, str | None], ...
]

_MAINTENANCE_GROUP: contextvars.ContextVar[str] = contextvars.ContextVar(
    "apprc_installation_maintenance_group", default="app"
)


@contextmanager
def installation_maintenance_group(name: str) -> Iterator[None]:
    """Bind native command-group metadata to one installation transaction."""
    if (
        not name
        or name in {".", ".."}
        or any(char in name for char in "/\\\x00")
    ):
        raise InstallationError("Maintenance group name is invalid.")
    token = _MAINTENANCE_GROUP.set(name)
    try:
        yield
    finally:
        _MAINTENANCE_GROUP.reset(token)


def _command_filename(command_name: str) -> str:
    if (
        not command_name
        or command_name in {".", ".."}
        or any(character in command_name for character in "/\\\x00")
    ):
        raise InstallationError("Primary command must be a single filename.")
    return command_name + (".exe" if os.name == "nt" else "")


def _path_entries(environment: Mapping[str, str]) -> tuple[Path, ...]:
    return tuple(
        Path(item).expanduser().absolute()
        for item in environment.get("PATH", "").split(os.pathsep)
        if item
    )


def _default_command_directory(
    uv: Path, environment: Mapping[str, str]
) -> Path:
    """Resolve the shared user bin the same way for both install modes."""
    result = subprocess.run(
        [str(uv), "tool", "dir", "--bin", "--no-config"],
        env=dict(environment),
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def _command_directory(
    uv: Path,
    selected: Path | None,
    environment: Mapping[str, str],
    forbidden: tuple[Path, ...],
) -> Path:
    if selected is None:
        selected = _default_command_directory(uv, environment)
    validate_command_directory(
        selected,
        forbidden=forbidden,
        path_entries=_path_entries(environment),
    )
    return selected


def _runtime_steps(
    inspection: InstallationInspection,
) -> frozenset[OperationStep]:
    record = inspection.record
    operation = record.operation if record is not None else None
    return frozenset(operation.steps if operation is not None else ())


def _checkpoint(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    step: OperationStep,
    observed: RuntimeSlot | EditableCheckout | None = None,
) -> InstallationInspection:
    result = manager.record_step(
        operation_id=operation_id,
        expected_revision=revision,
        step=step,
        observed=observed,
    )
    if result.revision is None:
        raise InstallationError(
            f"{step.value} checkpoint has no authority revision."
        )
    return result


def _context(
    directory: Path,
    operation_id: UUID,
    generation_id: UUID,
    placement: InstallationPlacement,
) -> OperationContext:
    return OperationContext(directory, operation_id, generation_id, placement)


def _validate_selected_resource_ownership(
    identity: InstallationIdentity,
    placement: InstallationPlacement,
) -> None:
    """Require installed ownership evidence for every selected resource root."""
    from apprc.user_files.app_home.ownership import inspect_ownership

    roots = {
        "config": placement.config_dir,
        "appdata": placement.appdata_dir,
        "cache": placement.cache_dir,
        "state": placement.state_dir,
    }
    resource_categories: tuple[ResourceKind, ...] = (
        "config",
        "appdata",
        "cache",
        "state",
    )
    for category in resource_categories:
        if category not in placement.capabilities:
            continue
        root = roots[category]
        if root is None:
            raise InstallationError(
                f"Selected {category} resource has no recorded root."
            )
        try:
            ownership = inspect_ownership(root, identity.app_id, category)
        except (OSError, ValueError) as error:
            raise InstallationError(
                f"Selected {category} resource root is unsafe."
            ) from error
        if ownership != "owned":
            raise InstallationError(
                f"Selected {category} resource root has no valid ownership marker."
            )
    logs = placement.logs_dir
    state = placement.state_dir
    if logs is not None and (
        state is None
        or not Path(os.path.normcase(str(logs.absolute()))).is_relative_to(
            Path(os.path.normcase(str(state.absolute())))
        )
    ):
        try:
            ownership = inspect_ownership(logs, identity.app_id, "state")
        except (OSError, ValueError) as error:
            raise InstallationError(
                "Selected logs resource root is unsafe."
            ) from error
        if ownership != "owned":
            raise InstallationError(
                "Selected logs resource root has no valid ownership marker."
            )


def _initialize_runtime(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    command_name: str,
    context: OperationContext,
    *,
    expected_revision: str,
    manager_executable: Path | None,
    expected_observations: dict[str, object],
) -> tuple[Path, ...]:
    hooks = runtime.hooks
    if identity.apprc_reference is None:
        if any(
            reference is not None
            for reference in (
                hooks.initialize,
                hooks.inventory,
                hooks.cleanup,
                hooks.migrate,
            )
        ):
            raise InstallationError(
                "Lifecycle hooks require an AppRC declaration."
            )
        initialized = manager.initialize(context=context)
        _validate_selected_resource_ownership(identity, context.placement)
        return initialized.paths
    result = application_bridge(
        manager.directory,
        identity,
        runtime,
        command_name=command_name,
        action="initialize",
        environment=dict(manager.environment),
        manager_executable=manager_executable,
        expected_revision=expected_revision,
        operation_context=context,
    )
    observation_fields = {
        "distribution",
        "version",
        "prefix",
        "interpreter",
        "python_version",
        "commands",
    }
    if (
        set(expected_observations) != observation_fields
        or not isinstance(result, dict)
        or set(result) != observation_fields | {"capabilities", "paths"}
        or any(
            result[field] != expected_observations[field]
            for field in observation_fields
        )
    ):
        raise InstallationError(
            "Initialization observations differ from the validated runtime probe."
        )
    capabilities = result["capabilities"]
    capability_names = {"config", "appdata", "cache", "state"}
    if (
        not isinstance(capabilities, dict)
        or set(capabilities) != capability_names
        or any(type(enabled) is not bool for enabled in capabilities.values())
    ):
        raise InstallationError(
            "Initialization returned invalid resource capabilities."
        )
    enabled = {name for name, value in capabilities.items() if value}
    if not enabled.issubset(context.placement.capabilities):
        raise InstallationError(
            "Initialized resource capabilities exceed the selected placement."
        )
    paths = result["paths"]
    if not isinstance(paths, list) or any(
        not isinstance(path, str) for path in paths
    ):
        raise InstallationError(
            "Initialization returned invalid resource paths."
        )
    resource_paths = {
        "config": context.placement.config_dir,
        "appdata": context.placement.appdata_dir,
        "cache": context.placement.cache_dir,
        "state": context.placement.state_dir,
    }
    if any(
        enabled_name and resource_paths[name] is None
        for name, enabled_name in capabilities.items()
    ):
        raise InstallationError(
            "Initialized capability has no selected resource path."
        )
    expected_paths = [
        str(resource_paths[name])
        for name in ("config", "appdata", "cache", "state")
        if capabilities[name]
    ]
    if capabilities["state"] and context.placement.logs_dir is not None:
        expected_paths.append(str(context.placement.logs_dir))
    if paths != expected_paths:
        raise InstallationError(
            "Initialized resource paths differ from the selected placement."
        )
    _validate_selected_resource_ownership(identity, context.placement)
    return tuple(Path(path) for path in paths)


def _retire_recorded_runtimes(
    manager: InstallationManager,
) -> InstallationInspection:
    directory = manager.directory
    with installation_lock(directory):
        inspection = manager.inspect()
        record = inspection.record
        if record is None or inspection.revision is None:
            return inspection
        generation_id = record.generation_id
        for slot_id in record.retiring_runtime_ids:
            fresh = manager.inspect()
            if (
                fresh.record is None
                or fresh.revision is None
                or fresh.record.generation_id != generation_id
                or slot_id not in fresh.record.retiring_runtime_ids
            ):
                return fresh
            slot_directory = directory / "runtimes" / str(slot_id)
            try:
                if not try_retire_runtime_slot(slot_directory):
                    continue
                inspection = manager.record_runtime_retired(
                    slot_id=slot_id,
                    expected_revision=fresh.revision,
                    generation_id=generation_id,
                )
            except (InstallationError, OSError):
                return manager.inspect()
            if inspection.record is None or inspection.revision is None:
                break
        return inspection


def _resource_snapshot(placement: InstallationPlacement) -> _ResourceSnapshot:
    """Capture SDK resource existence before an installation initializes them.

    :param placement: Validated intended resource locations.
    :return: Roots, marker categories, prior existence and marker revisions.
    """
    roots: list[tuple[Path | None, ResourceKind | None]] = [
        (placement.config_dir, "config"),
        (placement.appdata_dir, "appdata"),
        (placement.cache_dir, "cache"),
        (placement.state_dir, "state"),
    ]
    if "state" in placement.capabilities and placement.logs_dir is not None:
        state = placement.state_dir
        logs = placement.logs_dir
        roots.append(
            (
                logs,
                None
                if state is not None and logs.is_relative_to(state)
                else "state",
            )
        )
    captured: dict[
        Path, tuple[Path, ResourceKind | None, bool, str | None]
    ] = {}
    for root, category in roots:
        if root is None or (
            category is not None and category not in placement.capabilities
        ):
            continue
        assert_no_links(root)
        captured.setdefault(
            root,
            (
                root,
                category,
                root.exists(),
                file_revision(root / ".apprc-owner.json"),
            ),
        )
    return tuple(captured.values())


def _report_resources(
    snapshot: _ResourceSnapshot, initialized: tuple[Path, ...]
) -> None:
    labels: dict[ResourceKind | None, str] = {
        "config": "Configuration",
        "appdata": "Application data",
        "cache": "Cache",
        "state": "State",
        None: "Logs",
    }
    for root, category, existed, _ in snapshot:
        if root in initialized:
            status = "EXISTING" if existed else "CREATED"
            report("result", labels[category], status, root)


def _rollback_resources(
    manager: InstallationManager,
    plan: InstallPlan,
    inspection: InstallationInspection,
    resources: _ResourceSnapshot,
) -> None:
    """Remove only new SDK markers and empty directories, preserving payload.

    :param manager: Installation whose namespace is locked by the caller.
    :param plan: Pending operation authorizing resource lock acquisition.
    :param inspection: Current pending authority snapshot.
    :param resources: Existence captured before initialization.
    """
    from apprc.user_files.app_home.ownership import inspect_ownership

    changed = tuple(
        item
        for item in resources
        if (not item[2] and item[0].exists())
        or file_revision(item[0] / ".apprc-owner.json") != item[3]
    )
    if not changed:
        return
    context = _context(
        manager.directory,
        plan.operation_id,
        plan.generation_id,
        plan.target.placement,
    )
    controls = {managed_lock_path(item[0]) for item in resources}
    with managed_write_lock(
        *(item[0] for item in changed),
        authority=InstallationWriteAuthority(
            manager.spec.app_id, inspection.snapshot, context
        ),
    ):
        for root, category, existed, marker_revision in sorted(
            changed, key=lambda item: len(item[0].parts), reverse=True
        ):
            assert_no_links(root)
            marker = root / ".apprc-owner.json"
            actual_marker = file_revision(marker)
            if marker_revision is not None:
                if actual_marker != marker_revision:
                    raise InstallationError(
                        f"Resource ownership changed during installation: {root}."
                    )
                continue
            if actual_marker is not None:
                if (
                    category is None
                    or inspect_ownership(root, manager.spec.app_id, category)
                    != "owned"
                ):
                    raise InstallationError(
                        f"Resource ownership cannot be rolled back: {root}."
                    )
                payload = tuple(
                    path for path in root.iterdir() if path != marker
                )
                if payload and all(
                    path in controls
                    and path.is_file()
                    and not path.is_symlink()
                    for path in payload
                ):
                    # > Stable subordinate locks may still be open on Windows.
                    # > Keep their owned container so a fresh retry can reuse it.
                    continue
                if payload:
                    raise InstallationError(
                        f"New resource contains application or unknown data: {root}."
                    )
                marker.unlink()
            if not existed and root.exists():
                root.rmdir()


def _finish_installation(
    manager: InstallationManager, inspection: InstallationInspection
) -> InstallationInspection:
    """Keep activation successful when postcommit housekeeping needs a retry."""
    try:
        inspection = _command_publication.cleanup_publication_images(
            manager, inspection
        )
        return (
            _retire_recorded_runtimes(manager)
            if inspection.record
            else inspection
        )
    except Exception as error:
        warn(LOG, "Installation succeeded; cleanup remains pending", error)
        return inspection


def _failed_operation(
    manager: InstallationManager,
    plan: InstallPlan,
    prior: InstallationInspection,
    error: BaseException,
    *,
    resources: _ResourceSnapshot,
    candidate_existed: bool,
    activation_started: bool,
) -> InstallationInspection | None:
    """Restore one caught install failure or retain honest recovery authority.

    Authority is restored last, only after exact-owned effects were reversed.
    Application callbacks remain responsible for their own data and side effects.

    :param manager: Installation whose lifecycle lock is already held.
    :param plan: Exact operation this invocation attempted.
    :param prior: Authority captured before this attempt.
    :param error: Original failure, preserved if rollback succeeds.
    :param resources: Resource existence before initialization.
    :param candidate_existed: Whether the managed candidate predates this attempt.
    :param activation_started: Whether activation was called before the failure.
    :return: Committed success after a read-back failure, otherwise ``None``.
    """
    try:
        latest = manager.inspect()
        record = latest.record
        if (
            activation_started
            and record is not None
            and record.status == "ready"
            and record.operation is None
            and record.generation_id == plan.generation_id
            and record.identity == plan.target.identity
            and record.command_name == plan.command_name
            and record.active_runtime is not None
            and _matches_candidate(plan.target.runtime, record.active_runtime)
        ):
            report(
                "result",
                "Installation record",
                "RECORDED",
                manager.directory / "installation.json",
            )
            warn(
                LOG,
                "Installation succeeded despite activation read-back error",
                error,
            )
            return _finish_installation(manager, latest)
        if (
            (prior.record is None or prior.record.operation is None)
            and latest.revision == prior.revision
            and record == prior.record
        ):
            error.add_note("AppRC installation changes were rolled back.")
            return None
        if (
            record is None
            or record.operation is None
            or record.operation.operation_id != plan.operation_id
            or record.generation_id != plan.generation_id
            or latest.revision is None
        ):
            raise InstallationError(
                "Installation authority changed; rollback was not authorized."
            )
        operation = record.operation
        _command_publication.restore_commands(manager, operation.publication)
        _rollback_resources(manager, plan, latest, resources)
        runtime = plan.target.runtime
        if isinstance(runtime, RuntimeSlot):
            if candidate_existed:
                raise InstallationError(
                    "The resumed runtime candidate retains preparation effects; resume or repair this exact attempt."
                )
            if not try_retire_runtime_slot(
                manager.directory / "runtimes" / str(runtime.slot_id)
            ):
                raise InstallationError(
                    "New runtime candidate is busy; retry recovery after its processes exit."
                )
        previous_operation = (
            prior.record.operation if prior.record is not None else None
        )
        _command_publication.discard_rollback_images(
            manager.directory,
            operation.publication,
            previous_operation.publication
            if previous_operation is not None
            else (),
        )
        manager.rollback_installation(
            operation_id=plan.operation_id,
            expected_revision=latest.revision,
            previous=prior.record,
        )
        error.add_note("AppRC installation changes were rolled back.")
        return None
    except BaseException as rollback_error:
        failures = [error, rollback_error]
        message = f"{error} AppRC installation rollback is incomplete: {rollback_error}"
        try:
            latest = manager.inspect()
            record = latest.record
            if (
                record is not None
                and record.operation is not None
                and record.operation.operation_id == plan.operation_id
                and latest.revision is not None
            ):
                manager.fail_operation(
                    operation_id=plan.operation_id,
                    expected_revision=latest.revision,
                    diagnostic=InstallationDiagnostic(
                        "runtime-incomplete",
                        message,
                        "Inspect the installation and retry the matching checkout command or original setup to resume recovery.",
                    ),
                )
        except BaseException as journal_error:
            failures.append(journal_error)
            message += f" Failure recording also failed: {journal_error}"
        raise InstallationError(
            message
            + " Inspect the installation and retry the matching checkout command or original setup to resume recovery."
        ) from BaseExceptionGroup(
            "Installation and rollback failures", failures
        )


def _snapshot_metadata(
    archive: Path,
    runtime: RuntimeSlot,
    identity: InstallationIdentity,
) -> str:
    """Read expected metadata only from the digest-verified retained archive."""
    from apprc.distribution.metadata import read_project_metadata

    assert_no_links(archive)
    if ut.sha256_file(archive) != runtime.source.digest:
        raise InstallationError("Retained project archive was modified.")
    selected = PurePosixPath(runtime.source.project_path)
    try:
        with ZipFile(archive) as package:
            metadata = package.read((selected / "pyproject.toml").as_posix())
            lock = next(
                (
                    (parent / "uv.lock").as_posix()
                    for parent in (selected, *selected.parents)
                    if (parent / "uv.lock").as_posix() in package.namelist()
                ),
                None,
            )
            if lock is None:
                raise InstallationError(
                    "Retained project archive has no uv.lock."
                )
            with package.open(lock) as stream:
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                if digest.hexdigest() != runtime.source.lock_digest:
                    raise InstallationError(
                        "Retained project lock was modified."
                    )
        temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
        with tempfile.TemporaryDirectory(
            prefix="apprc-snapshot-metadata-", dir=temporary_parent
        ) as stage:
            root = Path(stage)
            (root / "pyproject.toml").write_bytes(metadata)
            captured = read_project_metadata(root)
    except (OSError, ValueError, KeyError, BadZipFile) as error:
        raise InstallationError(
            "Retained snapshot project metadata is invalid."
        ) from error
    if captured.identity != identity and (
        captured.preview is None or captured.preview.identity != identity
    ):
        raise InstallationError(
            "Verified snapshot identity differs from installation authority."
        )
    return captured.version


def _retained_archive(directory: Path, runtime: RuntimeSlot) -> Path:
    archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    assert_no_links(archive)
    if (
        not archive.is_file()
        or ut.sha256_file(archive) != runtime.source.digest
    ):
        raise InstallationError(
            "Retained runtime project archive is unavailable or modified."
        )
    return archive


def _restore_pending_candidate_archive(
    manager: InstallationManager,
    runtime: RuntimeSlot,
    manager_executable: Path,
) -> Path:
    from apprc.distribution.runtime._manager import _executable, _read_product

    if _executable().resolve(strict=True) != manager_executable.resolve(
        strict=True
    ):
        raise InstallationError(
            "Manager executable does not match the running product."
        )

    record = manager.inspect().record
    if record is None:
        raise InstallationError(
            "The pending candidate no longer has saved authority."
        )
    binding, content = _read_product(
        include_project=True, identity=record.identity
    )
    if (
        content is None
        or binding.identity != record.identity
        or binding.source != runtime.source
        or binding.selection != runtime.selection
        or binding.hooks != runtime.hooks
        or hashlib.sha256(content).hexdigest() != runtime.source.digest
    ):
        raise InstallationError(
            "The embedded project does not match the exact pending candidate."
        )
    archive = (
        manager.directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    )
    assert_no_links(archive.parent)
    archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_no_links(archive)
    if archive.exists():
        if ut.sha256_file(archive) != runtime.source.digest:
            raise InstallationError(
                "Exact pending candidate archive was modified."
            )
    else:
        with archive.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return archive


def _checkpoint_activation(
    manager: InstallationManager, operation_id: UUID, revision: str
) -> str:
    """Record the final pre-activation checkpoints for a published command."""
    for step in (OperationStep.SUPPORT_READY, OperationStep.REGISTRATION_READY):
        current = _checkpoint(manager, operation_id, revision, step)
        revision = current.revision or ""
    report("stage", "Saving Installation Record")
    return revision


def _commit_activation(
    manager: InstallationManager,
    *,
    operation_id: UUID,
    revision: str,
    observed: RuntimeSlot | EditableCheckout,
    outputs: list[OwnedOutput],
    command: Path,
    version: str,
) -> InstallationInspection:
    """Commit the candidate, then publish optional registration metadata."""
    result = manager.commit_install(
        operation_id=operation_id,
        expected_revision=revision,
        observed=observed,
        owned_outputs=tuple(outputs),
    )
    report(
        "result",
        "Installation record",
        "RECORDED",
        manager.directory / "installation.json",
    )
    from apprc.distribution.runtime._windows_registration import (
        publish_registration,
    )
    from apprc.distribution.runtime._icons import ready_icon

    result, icon, icon_resolved = ready_icon(result, publish=True)
    result = publish_registration(
        result,
        version,
        command,
        _MAINTENANCE_GROUP.get(),
        icon=icon,
        preserve_icon=not icon_resolved,
    )
    return _finish_installation(manager, result)


def _install_managed_candidate(
    manager: InstallationManager,
    plan: InstallPlan,
    prior: InstallationInspection,
    runtime: RuntimeSlot,
    *,
    manager_executable: Path,
    uv: Path,
    archive: Path | None,
    commands: tuple[tuple[Path, str | None], ...],
    user_path_command: Path | None = None,
    prepared_command: tuple[str, bytes] | None = None,
) -> InstallationInspection:
    """Prepare and activate one managed candidate under its lifecycle lock.

    Callers select installation versus repair and exact command destinations.
    This procedure owns publication, activation and their caught-failure evidence.

    :param manager: Installation whose lifecycle lock is held by the caller.
    :param plan: Fresh or exact resumed installation plan.
    :param prior: Authority before beginning this attempt.
    :param runtime: Exact managed candidate.
    :param manager_executable: Authenticated native command to publish.
    :param uv: Manager-owned runtime preparation executable.
    :param archive: Setup snapshot, or ``None`` to recover the repair snapshot.
    :param commands: Global command destinations and optional link targets.
    :param user_path_command: Automatic Windows command whose directory may be added to user PATH.
    :param prepared_command: Version and command bytes prepared for comparison.
    :return: Activated installation, including deferred housekeeping.
    """
    directory = manager.directory
    stable = directory / _command_filename(plan.command_name)
    previous = prior.record
    prior_outputs = previous.owned_outputs if previous is not None else ()
    resources = _resource_snapshot(plan.target.placement)
    candidate_existed = (directory / "runtimes" / str(runtime.slot_id)).exists()
    activation_started = False
    try:
        current = manager.begin_operation(plan)
        if current.revision is None:
            raise InstallationError(
                "Pending managed installation has no revision."
            )
        if archive is None:
            candidate_archive = (
                directory / "runtimes" / str(runtime.slot_id) / "project.zip"
            )
            if previous is not None and previous.operation is not None:
                archive = (
                    _retained_archive(directory, runtime)
                    if candidate_archive.exists()
                    else _restore_pending_candidate_archive(
                        manager, runtime, manager_executable
                    )
                )
            elif previous is not None and isinstance(
                previous.active_runtime, RuntimeSlot
            ):
                archive = _retained_archive(directory, previous.active_runtime)
            else:
                raise InstallationError(
                    "Managed repair requires an active or pending runtime."
                )
        pending = _command_publication.pending_publication(manager)
        _command_publication.check_owned_stable_command(
            stable,
            (*prior_outputs, *_command_publication.authorized_outputs(pending)),
        )
        observed, revision = _prepare_candidate(
            manager,
            plan,
            runtime,
            archive,
            uv,
            environment=manager.environment,
            manager_executable=manager_executable,
            resources=resources,
        )
        from apprc.distribution.runtime._windows_version import (
            versioned_executable,
        )

        report("stage", "Publishing Command")
        content = (
            prepared_command[1]
            if prepared_command is not None
            and prepared_command[0] == observed.version
            else versioned_executable(
                manager_executable.read_bytes(), observed.version or ""
            )
        )
        publication_specs = (
            (stable, content, None),
            *(
                (path, None if target is not None else content, target)
                for path, target in commands
            ),
        )
        outputs, revision = _command_publication.publish_commands(
            manager,
            plan.operation_id,
            revision,
            publication_specs,
            prior_outputs=prior_outputs,
            stable=stable,
            user_path_command=user_path_command,
        )
        paths = {item.path for item in outputs}
        outputs.extend(item for item in prior_outputs if item.path not in paths)
        revision = _checkpoint_activation(manager, plan.operation_id, revision)
        activation_started = True
        return _commit_activation(
            manager,
            operation_id=plan.operation_id,
            revision=revision,
            observed=observed,
            outputs=outputs,
            command=stable,
            version=observed.version or "",
        )
    except BaseException as error:
        committed = _failed_operation(
            manager,
            plan,
            prior,
            error,
            resources=resources,
            candidate_existed=candidate_existed,
            activation_started=activation_started,
        )
        if committed is not None:
            return committed
        raise


def _repair_managed_application(
    manager: InstallationManager,
    *,
    manager_executable: Path,
    uv: Path,
    expected_revision: str,
) -> InstallationInspection:
    if not manager_executable.is_absolute() or not manager_executable.is_file():
        raise InstallationError(
            "Managed repair requires its native manager executable."
        )
    if not uv.is_absolute() or not uv.is_file():
        raise InstallationError(
            "Managed repair requires an absolute manager uv."
        )
    directory = manager.directory
    with installation_lock(directory):
        prior = manager.inspect()
        if prior.revision != expected_revision:
            raise InstallationError(
                "The installation changed before recovery started. Run doctor and try again."
            )
        record = prior.record
        if record is None or prior.revision is None:
            raise InstallationError(
                "Managed repair requires saved installation authority."
            )
        stable = directory / _command_filename(record.command_name)
        if record.operation is not None:
            intended = record.operation.intended
            if intended is None or not isinstance(
                intended.runtime, RuntimeSlot
            ):
                raise InstallationError(
                    "No managed candidate is available to resume."
                )
            runtime = intended.runtime
            plan = manager.plan_resume()
        else:
            active = record.active_runtime
            if not isinstance(active, RuntimeSlot):
                raise InstallationError(
                    "Editable environments are developer-owned; restore with `uv sync --locked`."
                )
            runtime = RuntimeSlot(
                uuid4(), active.source, active.selection, hooks=active.hooks
            )
            plan = manager.plan_repair(
                record.identity, runtime, record.placement
            )
        pending_publication = _command_publication.pending_publication(manager)
        result = _install_managed_candidate(
            manager,
            plan,
            prior,
            runtime,
            manager_executable=manager_executable,
            uv=uv,
            archive=None,
            commands=tuple(
                (item.path, item.intended.link_target)
                for item in pending_publication
                if item.path != stable
            ),
        )
        from apprc.distribution.runtime import _windows_command_path

        if _windows_command_path.enabled():
            for item in pending_publication:
                if item.path != stable and item.update_user_path:
                    _report_windows_command_path(
                        manager, result, item.path, manager.environment
                    )
        return result


def _rebuild_candidate_runtime(
    slot_directory: Path,
    archive: Path,
    directory: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot,
    uv: Path,
    environment: Mapping[str, str],
) -> None:
    """Recreate a broken exact candidate only while no runtime child holds it."""
    claim = try_acquire_runtime_quiescence(slot_directory)
    if claim is None:
        raise InstallationError(
            "Candidate runtime is busy; retry repair after its active process exits."
        )
    try:
        source_root = slot_directory / "source"
        environment_path = slot_directory / ".venv"
        for target in (source_root, environment_path):
            assert_no_links(target)
            if target.exists():
                if not target.is_dir():
                    raise InstallationError(
                        "Candidate runtime path is not a directory."
                    )
                shutil.rmtree(target)
        materialize_project_snapshot(archive, source_root, runtime.source)
        report("detail", "Synchronizing dependencies with uv...")
        with claim.authorize_bridge():
            sync_runtime_slot(
                uv, directory, identity, runtime, environment=environment
            )
        report("result", "Python environment", "CREATED", environment_path)
        report("result", "Dependencies", "SYNCED")
    finally:
        claim.close()


def _prepare_candidate(
    manager: InstallationManager,
    plan: InstallPlan,
    runtime: RuntimeSlot,
    archive: Path,
    uv: Path,
    *,
    environment: Mapping[str, str],
    manager_executable: Path,
    resources: _ResourceSnapshot = (),
) -> tuple[RuntimeSlot, str]:
    directory = manager.directory
    identity = plan.target.identity
    operation_id = plan.operation_id
    generation_id = plan.generation_id
    revision = manager.inspect().revision
    if revision is None:
        raise InstallationError(
            "Pending installation has no authority revision."
        )
    slot_directory = directory / "runtimes" / str(runtime.slot_id)
    assert_no_links(slot_directory.parent)
    slot_directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_no_links(slot_directory.parent)
    if slot_directory.exists():
        assert_no_links(slot_directory)
        if not slot_directory.is_dir():
            raise InstallationError(
                "Runtime candidate address is not a directory."
            )
    else:
        slot_directory.mkdir(mode=0o700)
    archive_path = slot_directory / "project.zip"
    assert_no_links(archive_path)
    if archive_path.exists():
        if ut.sha256_file(archive_path) != runtime.source.digest:
            raise InstallationError(
                "Retained candidate project archive was modified."
            )
    else:
        assert_no_links(archive)
        if ut.sha256_file(archive) != runtime.source.digest:
            raise InstallationError(
                "Setup project archive differs from the runtime binding."
            )
        with archive.open("rb") as source, archive_path.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    steps = _runtime_steps(manager.inspect())
    source_root = slot_directory / "source"
    environment_path = slot_directory / ".venv"
    expected_version = _snapshot_metadata(archive_path, runtime, identity)
    report("result", "Project snapshot", "VERIFIED")
    rebuilt = False
    if OperationStep.RUNTIME_PREPARED not in steps:
        _rebuild_candidate_runtime(
            slot_directory,
            archive_path,
            directory,
            identity,
            runtime,
            uv,
            environment,
        )
        rebuilt = True
        current = _checkpoint(
            manager, operation_id, revision, OperationStep.SOURCE_VERIFIED
        )
        revision = current.revision or ""
        current = _checkpoint(
            manager, operation_id, revision, OperationStep.RUNTIME_PREPARED
        )
        revision = current.revision or ""
    elif not source_root.is_dir() or not environment_path.is_dir():
        _rebuild_candidate_runtime(
            slot_directory,
            archive_path,
            directory,
            identity,
            runtime,
            uv,
            environment,
        )
        rebuilt = True
    inspection = manager.inspect()
    revision = inspection.revision or revision
    try:
        observed, observations = _probe_runtime_observations(
            directory,
            identity,
            runtime,
            command_name=plan.command_name,
            environment=dict(environment),
            manager_executable=manager_executable,
            expected_revision=revision,
        )
    except InstallationError:
        if rebuilt:
            raise
        _rebuild_candidate_runtime(
            slot_directory,
            archive_path,
            directory,
            identity,
            runtime,
            uv,
            environment,
        )
        rebuilt = True
        inspection = manager.inspect()
        revision = inspection.revision or revision
        observed, observations = _probe_runtime_observations(
            directory,
            identity,
            runtime,
            command_name=plan.command_name,
            environment=dict(environment),
            manager_executable=manager_executable,
            expected_revision=revision,
        )
    if not isinstance(observed, RuntimeSlot):
        raise InstallationError(
            "Managed candidate probe returned an editable runtime."
        )
    if observed.version != expected_version:
        raise InstallationError(
            "Installed distribution version differs from the immutable project snapshot."
        )
    if not rebuilt:
        report("result", "Python environment", "REUSED", environment_path)
    report("result", "Installed runtime", "VALIDATED")
    report("version", expected_version)
    current = _checkpoint(
        manager,
        operation_id,
        revision,
        OperationStep.RUNTIME_VALIDATED,
        observed,
    )
    revision = current.revision or ""
    context = _context(
        directory, operation_id, generation_id, plan.target.placement
    )
    if resources:
        report("stage", "Initializing Resources")
    initialized = _initialize_runtime(
        manager,
        identity,
        runtime,
        plan.command_name,
        context,
        expected_revision=revision,
        manager_executable=manager_executable,
        expected_observations=observations,
    )
    current = _checkpoint(
        manager, operation_id, revision, OperationStep.RESOURCES_READY
    )
    _report_resources(resources, initialized)
    return observed, current.revision or ""


def _report_windows_command_path(
    manager: InstallationManager,
    inspection: InstallationInspection,
    command: Path,
    environment: Mapping[str, str],
) -> None:
    """Expose an owned command only after its installation has activated."""
    from apprc.distribution.runtime import _windows_command_path

    record = inspection.record
    if (
        inspection.status != "ready"
        or record is None
        or record.operation is not None
    ):
        return
    try:
        current = manager.inspect()
        if (
            current.status != "ready"
            or current.revision != inspection.revision
            or current.record != record
        ):
            raise InstallationError(
                "Installation authority changed before updating user PATH."
            )
        assert_no_links(command)
        if not _windows_command_path.is_user_directory(
            command.parent, environment
        ):
            raise InstallationError(
                "The published command is outside the current user's directories."
            )
        if not command.is_file() or not command_is_owned(
            command, record.owned_outputs, ut.sha256_file(command)
        ):
            raise InstallationError(
                "The published command could not be verified."
            )
        if not _windows_command_path.ensure_user_path(
            command.parent, environment
        ):
            if not _windows_command_path.is_on_current_path(
                command.parent, environment
            ):
                report(
                    "detail",
                    "Open a new PowerShell window to use the global command.",
                )
            return
    except Exception as error:
        warn(
            LOG,
            "Unable to update the user PATH; run the installed command by its full path",
            error,
            path=command,
        )
        return
    report("result", "User PATH", "UPDATED", command.parent)
    try:
        _windows_command_path.notify_path_change()
    except OSError as error:
        warn(
            LOG,
            "User PATH was saved but Windows could not refresh existing shells",
            error,
        )
    report("detail", "Open a new PowerShell window to use the global command.")


def require_update_record(
    inspection: InstallationInspection, expected: tuple[UUID, str]
) -> InstallationRecord:
    """Require the same ready installation that was offered to the user."""
    record = inspection.require_usable()
    if (
        record is None
        or record.status != "ready"
        or record.operation is not None
        or (record.generation_id, inspection.revision) != expected
    ):
        raise InstallationError(
            "The installation changed after update was requested. Run update again."
        )
    return record


def recorded_command_directory(
    record: InstallationRecord, directory: Path
) -> Path | None:
    """Read the single recorded global command location without consulting PATH."""
    name = _command_filename(record.command_name)
    stable = directory / name
    parents = {
        path.parent
        for item in record.owned_outputs
        if item.kind == "command"
        and os.path.normcase((path := Path(item.path)).name)
        == os.path.normcase(name)
        and os.path.normcase(str(path)) != os.path.normcase(str(stable))
    }
    if len(parents) > 1:
        raise InstallationError(
            "Multiple recorded command locations. Use the publisher's manual update procedure."
        )
    return next(iter(parents), None)


def _report_setup_change(
    installed: RuntimeSlot | EditableCheckout | None,
    candidate: RuntimeSlot,
    version: str,
    manager_executable: Path,
    installed_digest: str | None,
    *,
    resuming: bool,
) -> tuple[str, bytes] | None:
    """Describe the selected setup and reuse any command prepared for comparison."""
    action = "Install" if installed is None else "Replace"
    incoming = version
    prepared = None
    if isinstance(installed, RuntimeSlot):
        current = installed.version or "Unknown version"
        if installed.version == version:
            current += f" (commit {installed.source.commit[:12]})"
            incoming += f" (commit {candidate.source.commit[:12]})"
            if (
                not resuming
                and installed.source.commit == candidate.source.commit
                and installed_digest is not None
            ):
                from apprc.distribution.runtime._windows_version import (
                    versioned_executable,
                )

                content = versioned_executable(
                    manager_executable.read_bytes(), version
                )
                prepared = (version, content)
                digest = hashlib.sha256(content).hexdigest()
                current += f" · Command SHA-256 {installed_digest[:12]}"
                incoming += f" · Command SHA-256 {digest[:12]}"
                if installed_digest == digest:
                    action = "Reinstall"
    elif isinstance(installed, EditableCheckout):
        current = "Editable checkout"
    else:
        current = "No active installation"
    report("summary", "Resume installation" if resuming else action)
    report(
        "detail",
        f"Installed  {current}",
        path=installed.project
        if isinstance(installed, EditableCheckout)
        else None,
    )
    report("detail", f"Incoming   {incoming}")
    return prepared


def install_application(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: RuntimeSlot,
    placement: InstallationPlacement,
    *,
    command_name: str,
    setup_version: str | None = None,
    project_archive: Path,
    manager_executable: Path,
    uv: Path,
    command_directory: Path | None = None,
    assume_yes: bool = False,
    require_fresh: bool = False,
    other_app_id: str | None = None,
    reserve_other_native_paths: bool = False,
    expected_update: tuple[UUID, str] | None = None,
    preview_alias: str | None = None,
    publish_preview_alias: bool = False,
) -> InstallationInspection:
    if not manager_executable.is_absolute() or not manager_executable.is_file():
        raise InstallationError(
            "Managed installation requires its setup executable."
        )
    if not uv.is_absolute() or not uv.is_file():
        raise InstallationError(
            "Managed installation requires an absolute manager uv."
        )
    if not project_archive.is_absolute() or not project_archive.is_file():
        raise InstallationError(
            "Managed installation requires its embedded project archive."
        )
    directory = manager.directory
    environment = manager.environment
    with installation_lock(directory):
        prior = manager.inspect()
        if expected_update is not None:
            update_record = require_update_record(prior, expected_update)
            if (
                not isinstance(update_record.active_runtime, RuntimeSlot)
                or update_record.identity != identity
                or update_record.command_name != command_name
            ):
                raise InstallationError(
                    "The requested update is for a different managed installation."
                )
            command_directory = recorded_command_directory(
                update_record, directory
            )
        setup_source = runtime.source
        if require_fresh:
            if prior.status != "missing" or any(
                os.path.lexists(path) for _, path in resource_roots(placement)
            ):
                raise InstallationError(
                    "Smoke requires a fresh preview. Remove the existing preview and any retained resources first."
                )
            from apprc.distribution.runtime._uninstall_controller import (
                verify_windows_registration,
            )

            verify_windows_registration(
                manager,
                directory / _command_filename(command_name),
                None,
                _MAINTENANCE_GROUP.get(),
            )
        previous = prior.record
        operation = previous.operation if previous is not None else None
        if previous is not None and operation is not None:
            intended = operation.intended
            if intended is None or not isinstance(
                intended.runtime, RuntimeSlot
            ):
                raise InstallationError(
                    "Pending operation has no managed runtime candidate."
                )
            identity = intended.identity
            runtime = intended.runtime
            command_name = previous.command_name
        if previous is not None and previous.status not in {"removed-retained"}:
            if previous.placement != placement:
                placement = previous.placement
            if (
                previous.operation is None
                and isinstance(previous.active_runtime, EditableCheckout)
                and not assume_yes
            ):
                raise InstallationError(
                    "Switching editable mode requires --yes confirmation."
                )
        stable = directory / _command_filename(command_name)
        prior_outputs = previous.owned_outputs if previous is not None else ()
        pending_publication = _command_publication.pending_publication(manager)
        publication_authority = _command_publication.authorized_outputs(
            pending_publication
        )
        installed_digest = _command_publication.check_owned_stable_command(
            stable, (*prior_outputs, *publication_authority)
        )
        from apprc.distribution.runtime import _windows_command_path

        forbidden = (directory, runtime_prefix(directory, runtime))
        if previous is not None and isinstance(
            previous.active_runtime, EditableCheckout
        ):
            checkout = previous.active_runtime
            forbidden += (
                checkout.project,
                checkout.environment,
                checkout.environment.parent,
            )
        global_command: Path | None = None
        update_user_path = False
        if expected_update is not None:
            if command_directory is not None:
                validate_command_directory(
                    command_directory,
                    forbidden=forbidden,
                    path_entries=(command_directory,),
                )
                global_command = command_directory / _command_filename(
                    command_name
                )
        elif command_directory is not None:
            global_command = _command_directory(
                uv, command_directory, environment, forbidden
            ) / _command_filename(command_name)
        elif pending_publication:
            if len(pending_publication) > 1:
                global_command = pending_publication[1].path
        elif _windows_command_path.enabled():
            name = _command_filename(command_name)
            candidates = (
                Path(item.path).parent
                for item in prior_outputs
                if item.kind == "command"
                and Path(item.path).name.casefold() == name.casefold()
                and Path(item.path) != stable
            )
            global_directory = next(
                (
                    candidate
                    for candidate in candidates
                    if _windows_command_path.is_user_directory(
                        candidate, environment
                    )
                    and _windows_command_path.is_on_path(candidate, environment)
                ),
                None,
            )
            if global_directory is None:
                global_directory = _default_command_directory(uv, environment)
            global_command = global_directory / name
            update_user_path = True
        if other_app_id is not None:
            from apprc.distribution.runtime._native_product import (
                check_other_product_paths,
            )

            check_other_product_paths(
                (
                    directory,
                    *(path for _, path in resource_roots(placement)),
                    *((global_command,) if global_command is not None else ()),
                ),
                other_app_id,
                environment,
                reserve_native_paths=reserve_other_native_paths,
            )
        if global_command is not None and update_user_path:
            global_directory = global_command.parent
            _windows_command_path.prepare_shared_bin(
                global_directory, environment, forbidden=forbidden
            )
            validate_command_directory(
                global_directory,
                forbidden=forbidden,
                path_entries=(global_directory,),
            )
        if pending_publication and command_directory is None:
            update_user_path = any(
                item.path == global_command and item.update_user_path
                for item in pending_publication
            )
        if global_command is not None:
            validate_global_command(
                global_command,
                previous=(*prior_outputs, *publication_authority),
            )
        link_target = None if _windows_command_path.enabled() else str(stable)
        commands = ((global_command, link_target),) if global_command else ()
        if pending_publication:
            # > Resume the accepted output set even if alias availability changed.
            commands += tuple(
                (item.path, item.intended.link_target)
                for item in pending_publication[2:]
            )
        elif (
            global_command is not None
            and preview_alias
            and publish_preview_alias
        ):
            alias = global_command.with_name(_command_filename(preview_alias))
            found = shutil.which(
                preview_alias, path=environment.get("PATH", "")
            )
            try:
                if found is not None and os.path.normcase(
                    os.path.abspath(found)
                ) != os.path.normcase(str(alias)):
                    raise InstallationError(
                        "The short name already resolves to another command."
                    )
                if other_app_id is not None:
                    check_other_product_paths(
                        (alias,), other_app_id, environment
                    )
                validate_global_command(alias, previous=prior_outputs)
                commands += ((alias, link_target),)
            except (OSError, ValueError) as error:
                warn(LOG, "Preview alias was skipped", error, path=alias)
        if operation is not None:
            pending_archive = (
                directory / "runtimes" / str(runtime.slot_id) / "project.zip"
            )
            if pending_archive.is_file():
                if ut.sha256_file(pending_archive) != runtime.source.digest:
                    raise InstallationError(
                        "Exact pending candidate archive was modified."
                    )
                project_archive = pending_archive
            elif ut.sha256_file(project_archive) != runtime.source.digest:
                raise InstallationError(
                    "Setup project snapshot differs from the exact pending candidate."
                )
            plan = manager.plan_resume()
        else:
            plan = manager.plan_install(
                identity, runtime, placement, command_name=command_name
            )
        version = (
            setup_version
            if setup_version is not None and runtime.source == setup_source
            else _snapshot_metadata(project_archive, runtime, identity)
        )
        prepared_command = _report_setup_change(
            previous.active_runtime if previous is not None else None,
            runtime,
            version,
            manager_executable,
            installed_digest,
            resuming=operation is not None,
        )
        report("stage", "Preparing Runtime")
        result = _install_managed_candidate(
            manager,
            plan,
            prior,
            runtime,
            manager_executable=manager_executable,
            uv=uv,
            archive=project_archive,
            commands=commands,
            user_path_command=global_command if update_user_path else None,
            prepared_command=prepared_command,
        )
        if preview_alias and not publish_preview_alias:
            result = _command_publication.retire_command_alias(
                manager, result, _command_filename(preview_alias)
            )
        if (
            _windows_command_path.enabled()
            and update_user_path
            and global_command is not None
        ):
            _report_windows_command_path(
                manager, result, global_command, environment
            )
        return result


def _editable_command_directory(
    manager: InstallationManager,
    runtime: EditableCheckout,
    uv: Path,
    selected: Path | None,
) -> Path:
    environment = manager.environment
    return _command_directory(
        uv,
        selected,
        environment,
        (
            runtime.project,
            runtime.environment,
            runtime.environment.parent,
            manager.directory,
        ),
    )


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
        if expected_update is not None and command_directory is not None:
            validate_command_directory(
                command_directory,
                forbidden=(
                    runtime.project,
                    runtime.environment,
                    runtime.environment.parent,
                    manager.directory,
                ),
                path_entries=(command_directory,),
            )
            selected_directory = command_directory
        else:
            selected_directory = _editable_command_directory(
                manager, runtime, uv, command_directory
            )
        global_command = selected_directory / _command_filename(command_name)
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
        resources = _resource_snapshot(plan.target.placement)
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
            current = _checkpoint(
                manager,
                operation_id,
                current.revision,
                OperationStep.RUNTIME_PREPARED,
            )
            revision = current.revision or ""
            current = _checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.RUNTIME_VALIDATED,
                observed,
            )
            revision = current.revision or ""
            context = _context(
                manager.directory,
                operation_id,
                plan.generation_id,
                plan.target.placement,
            )
            report("result", "Checkout", "REUSED", project)
            report("result", "Environment", "REUSED", environment_path)
            report("detail", "Dependencies: not modified")
            report("version", str(observations["version"]))
            if resources:
                report("stage", "Initializing Resources")
            initialized = _initialize_runtime(
                manager,
                identity,
                runtime,
                command_name,
                context,
                expected_revision=revision,
                manager_executable=None,
                expected_observations=observations,
            )
            current = _checkpoint(
                manager, operation_id, revision, OperationStep.RESOURCES_READY
            )
            revision = current.revision or ""
            _report_resources(resources, initialized)
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
                        versioned_executable(
                            command.read_bytes(), str(observations["version"])
                        ),
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
            revision = _checkpoint_activation(manager, operation_id, revision)
            activation_started = True
            return _commit_activation(
                manager,
                operation_id=operation_id,
                revision=revision,
                observed=observed,
                outputs=outputs,
                command=global_command,
                version=str(observations["version"]),
            )
        except BaseException as error:
            committed = _failed_operation(
                manager,
                plan,
                prior,
                error,
                resources=resources,
                candidate_existed=False,
                activation_started=activation_started,
            )
            if committed is not None:
                return committed
            raise


def offer_configuration_setup(
    inspection: InstallationInspection,
    *,
    skip: bool,
    config_group_name: str = "config",
    runtime_options: CliRuntimeOptionsProtocol | None = None,
    environment: Mapping[str, str] | None = None,
    input_stream: TextIO | None = None,
    raise_on_failure: bool = False,
) -> bool:
    """Dispatch conditional configuration setup through the ready runtime.

    The application runtime owns field eligibility and user confirmation.
    Skipped and noninteractive invocations do not launch another process.

    :param inspection: Captured ready installation authority.
    :param skip: Whether the caller explicitly skipped optional setup.
    :param config_group_name: Mounted configuration command group.
    :param runtime_options: Captured selectors, using the recorded layout.
    :param environment: Captured invocation environment, or the current one.
    :param input_stream: Input whose terminal capability controls dispatch.
    :return: Whether the conditional setup command completed successfully.
    """
    record = inspection.require_usable()
    if record is None or record.active_runtime is None:
        raise InstallationError(
            "Configuration setup requires a usable runtime."
        )
    if "config" not in record.placement.capabilities:
        return False
    stream = input_stream if input_stream is not None else sys.stdin
    if skip or not stream.isatty():
        return False
    arguments: list[str] = []
    if runtime_options is not None:
        from apprc.definition.resolution import CliRuntimeOptions
        from apprc.interfaces.cli.context import cli_runtime_options_to_args

        arguments = cli_runtime_options_to_args(
            replace(
                CliRuntimeOptions.from_options(runtime_options),
                layout=record.placement.layout,
            )
        )
    command_name = record.command_name
    directory = inspection.directory
    with installation_lock(directory):
        latest = inspect_installation(directory, app_id=record.identity.app_id)
        if (
            latest.record is None
            or latest.record.active_runtime != record.active_runtime
        ):
            return False
        lease: RuntimeLease | None = None
        if isinstance(record.active_runtime, RuntimeSlot):
            lease = acquire_runtime_lease(
                directory / "runtimes" / str(record.active_runtime.slot_id)
            )
    try:
        runtime = record.active_runtime
        command = runtime_command(directory, runtime, command_name)
        child_environment = dict(
            environment if environment is not None else os.environ
        )
        if lease is not None:
            child_environment = lease.environment(child_environment)
            spawn_options = lease.subprocess_options()
        else:
            child_environment.pop("_APPRC_RUNTIME_LEASE_HANDLE", None)
            spawn_options = {}
        child_environment = runtime_environment(child_environment)
        if lease is not None:
            child_environment = lease.environment(child_environment)
        child_environment["VIRTUAL_ENV"] = str(
            runtime_prefix(directory, runtime)
        )
        binary = str(
            runtime_prefix(directory, runtime)
            / ("Scripts" if os.name == "nt" else "bin")
        )
        child_environment["PATH"] = (
            binary + os.pathsep + child_environment.get("PATH", "")
        )
        subprocess.run(
            [
                str(command),
                *arguments,
                config_group_name,
                "setup",
                "--offer-missing",
            ],
            env=child_environment,
            check=True,
            **spawn_options,
        )
    except (OSError, subprocess.CalledProcessError):
        if raise_on_failure:
            raise
        return False
    finally:
        if lease is not None:
            lease.close()
    return True


def confirm_desktop_shortcut(
    identity: InstallationIdentity, *, assume_yes: bool
) -> bool:
    """Offer an optional desktop shortcut only in an interactive desktop session."""
    if (
        assume_yes
        or sys.platform not in {"linux", "win32"}
        or sys.stdin is None
        or not sys.stdin.isatty()
    ):
        return False
    import typer
    from apprc.distribution.runtime._os_integration import (
        desktop_shortcut_available,
    )

    if not desktop_shortcut_available(identity):
        return False
    try:
        return typer.confirm("Add Desktop shortcut?", default=False)
    except typer.Abort:
        return False


def publish_optional_shortcuts(
    manager: InstallationManager,
    command: Path,
    identity: InstallationIdentity,
    *,
    display_name: str,
    start_menu: bool,
    desktop: bool,
    launch_enabled: bool,
) -> InstallationInspection:
    """Publish optional shortcuts after Ready and persist only owned outputs."""
    from apprc.distribution.runtime._icons import ready_icon
    from apprc.distribution.runtime._os_integration import publish_shortcuts
    from apprc.user_files.installation.operations import record_owned_outputs

    if start_menu or desktop:
        report("stage", "Publishing Shortcuts")
    directory = manager.directory
    with installation_lock(directory):
        inspection = manager.inspect()
        record = inspection.record
        if (
            record is None
            or record.status != "ready"
            or inspection.revision is None
            or record.identity != identity
            or not any(
                item.kind == "command" and item.path == str(command)
                for item in record.owned_outputs
            )
        ):
            warn(LOG, "Optional shortcuts were not updated")
            return inspection
        previous = tuple(
            item for item in record.owned_outputs if item.kind == "shortcut"
        )
        created: tuple[OwnedOutput, ...] = ()
        try:
            _, icon, _ = ready_icon(inspection)
            created = publish_shortcuts(
                command,
                identity,
                display_name=display_name,
                start_menu=start_menu,
                desktop=desktop,
                launch_enabled=launch_enabled,
                previous=previous,
                icon=icon,
            )
            created_paths = {item.path for item in created}
            outputs = (
                tuple(
                    item
                    for item in record.owned_outputs
                    if item.kind != "shortcut" or item.path not in created_paths
                )
                + created
            )
            result = record_owned_outputs(
                directory,
                app_id=identity.app_id,
                expected_revision=inspection.revision,
                generation_id=record.generation_id,
                owned_outputs=outputs,
            )
            for output in created:
                report("result", "Shortcut", "PUBLISHED", output.path)
            return result
        except Exception as error:
            from apprc.distribution.runtime._os_integration import (
                remove_owned_command,
            )

            for output in created:
                try:
                    remove_owned_command(output)
                except InstallationError:
                    pass
            warn(LOG, "Optional shortcuts were not updated", error)
            return manager.inspect()
