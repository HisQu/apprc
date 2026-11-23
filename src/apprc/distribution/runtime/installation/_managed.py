"""Install, replace or repair a managed runtime and publish its commands."""

from __future__ import annotations

import apprc.utils as ut

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationInspection,
    InstallPlan,
    InstallationIdentity,
    InstallationPlacement,
    RuntimeSlot,
)
from apprc.distribution.runtime import _command_publication
from apprc.distribution.runtime._install_progress import report, warn
from apprc.distribution.runtime._os_integration import (
    validate_command_directory,
    validate_global_command,
)
from apprc.distribution.runtime.backend import (
    runtime_prefix,
)
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.planning import resource_roots

from ._candidate import (
    prepare_candidate,
    retained_archive,
    restore_pending_candidate_archive,
    snapshot_metadata,
)
from ._commands import (
    command_filename,
    recorded_command_directory,
    select_command_directory,
    select_windows_global_command,
    update_windows_user_path,
)
from ._resources import capture_resource_snapshot
from ._transaction import (
    _MAINTENANCE_GROUP,
    checkpoint_activation,
    commit_activation,
    recover_installation_failure,
    require_update_record,
)

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager

LOG = logging.getLogger(__name__)


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
                directory / command_filename(command_name),
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
        stable = directory / command_filename(command_name)
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
                global_command = command_directory / command_filename(
                    command_name
                )
        elif command_directory is not None:
            global_command = select_command_directory(
                uv, command_directory, environment, forbidden
            ) / command_filename(command_name)
        elif pending_publication:
            if len(pending_publication) > 1:
                global_command = pending_publication[1].path
        elif _windows_command_path.enabled():
            global_command = select_windows_global_command(
                uv, environment, stable, prior_outputs
            )
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
            alias = global_command.with_name(command_filename(preview_alias))
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
            else snapshot_metadata(project_archive, runtime, identity)
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
        result = _activate_managed_candidate(
            manager,
            plan,
            prior,
            manager_executable=manager_executable,
            uv=uv,
            archive=project_archive,
            commands=commands,
            user_path_command=global_command if update_user_path else None,
            prepared_command=prepared_command,
        )
        if preview_alias and not publish_preview_alias:
            result = _command_publication.retire_command_alias(
                manager, result, command_filename(preview_alias)
            )
        if (
            _windows_command_path.enabled()
            and update_user_path
            and global_command is not None
        ):
            update_windows_user_path(
                manager, result, global_command, environment
            )
        return result


def repair_managed_installation(
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
        stable = directory / command_filename(record.command_name)
        if record.operation is not None:
            intended = record.operation.intended
            if intended is None or not isinstance(
                intended.runtime, RuntimeSlot
            ):
                raise InstallationError(
                    "No managed candidate is available to resume."
                )
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
        result = _activate_managed_candidate(
            manager,
            plan,
            prior,
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
                    update_windows_user_path(
                        manager, result, item.path, manager.environment
                    )
        return result


def _activate_managed_candidate(
    manager: InstallationManager,
    plan: InstallPlan,
    prior: InstallationInspection,
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
    :param manager_executable: Authenticated native command to publish.
    :param uv: Manager-owned runtime preparation executable.
    :param archive: Setup snapshot, or ``None`` to recover the repair snapshot.
    :param commands: Global command destinations and optional link targets.
    :param user_path_command: Automatic Windows command whose directory may be added to user PATH.
    :param prepared_command: Version and command bytes prepared for comparison.
    :return: Activated installation, including deferred housekeeping.
    """
    runtime = plan.target.runtime
    assert isinstance(runtime, RuntimeSlot)
    directory = manager.directory
    stable = directory / command_filename(plan.command_name)
    previous = prior.record
    prior_outputs = previous.owned_outputs if previous is not None else ()
    resources = capture_resource_snapshot(plan.target.placement)
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
                    retained_archive(directory, runtime)
                    if candidate_archive.exists()
                    else restore_pending_candidate_archive(
                        manager, runtime, manager_executable
                    )
                )
            elif previous is not None and isinstance(
                previous.active_runtime, RuntimeSlot
            ):
                archive = retained_archive(directory, previous.active_runtime)
            else:
                raise InstallationError(
                    "Managed repair requires an active or pending runtime."
                )
        pending = _command_publication.pending_publication(manager)
        _command_publication.check_owned_stable_command(
            stable,
            (*prior_outputs, *_command_publication.authorized_outputs(pending)),
        )
        observed, revision = prepare_candidate(
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
        revision = checkpoint_activation(manager, plan.operation_id, revision)
        activation_started = True
        return commit_activation(
            manager,
            operation_id=plan.operation_id,
            revision=revision,
            observed=observed,
            outputs=outputs,
            command=stable,
            version=observed.version or "",
        )
    except BaseException as error:
        committed = recover_installation_failure(
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
