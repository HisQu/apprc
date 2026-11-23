"""Managed candidate preparation and retained snapshot recovery."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

import apprc.utils as ut
from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallPlan,
    OperationContext,
    OperationStep,
    RuntimeSlot,
)
from apprc.distribution.runtime._install_progress import report
from apprc.distribution.runtime._leases import try_acquire_runtime_quiescence
from apprc.distribution.runtime.acquisition import materialize_project_snapshot
from apprc.distribution.runtime.backend import runtime_prefix, sync_runtime_slot
from apprc.distribution.runtime.probe import _probe_runtime_observations
from apprc.user_files.app_home.locations import assert_no_links

from .resources import ResourceSnapshot, initialize_resources, report_resources
from .transaction import checkpoint

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager


def prepare_candidate(
    manager: InstallationManager,
    plan: InstallPlan,
    runtime: RuntimeSlot,
    archive: Path,
    uv: Path,
    *,
    environment: Mapping[str, str],
    manager_executable: Path,
    resources: ResourceSnapshot = (),
) -> tuple[RuntimeSlot, str]:
    """Prepare or reuse the exact pending runtime under the installation lock.

    :param manager: Manager whose installation lock the caller holds.
    :param plan: Pending installation or repair plan.
    :param runtime: Exact managed candidate.
    :param archive: Setup or retained project snapshot.
    :param uv: Manager-owned executable for locked synchronization.
    :param environment: Environment supplied to synchronization and validation.
    :param manager_executable: Native manager used to validate the runtime.
    :param resources: Resource state captured before initialization.
    :return: Validated slot and authority revision after resource initialization.
    """
    directory = manager.directory
    identity = plan.target.identity
    operation_id = plan.operation_id
    revision = manager.inspect().revision
    if revision is None:
        raise InstallationError(
            "Pending installation has no authority revision."
        )

    environment_path = runtime_prefix(directory, runtime)
    slot_directory = environment_path.parent
    archive_path = _retain_candidate_archive(slot_directory, archive, runtime)
    record = manager.inspect().record
    operation = record.operation if record is not None else None
    steps = operation.steps if operation is not None else ()
    expected_version = snapshot_metadata(archive_path, runtime, identity)
    report("result", "Project snapshot", "VERIFIED")

    already_prepared = OperationStep.RUNTIME_PREPARED in steps
    rebuilt = (
        not already_prepared
        or not (slot_directory / "source").is_dir()
        or not environment_path.is_dir()
    )
    if rebuilt:
        _rebuild_candidate_runtime(
            directory, archive_path, identity, runtime, uv, environment
        )
    if not already_prepared:
        revision = checkpoint(
            manager, operation_id, revision, OperationStep.SOURCE_VERIFIED
        )
        revision = checkpoint(
            manager, operation_id, revision, OperationStep.RUNTIME_PREPARED
        )

    while True:
        revision = manager.inspect().revision or revision
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
                directory, archive_path, identity, runtime, uv, environment
            )
            rebuilt = True
        else:
            break
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
    revision = checkpoint(
        manager,
        operation_id,
        revision,
        OperationStep.RUNTIME_VALIDATED,
        observed,
    )

    context = OperationContext(
        directory, operation_id, plan.generation_id, plan.target.placement
    )
    if resources:
        report("stage", "Initializing Resources")
    initialized = initialize_resources(
        manager,
        identity,
        runtime,
        plan.command_name,
        context,
        expected_revision=revision,
        manager_executable=manager_executable,
        expected_observations=observations,
    )
    revision = checkpoint(
        manager, operation_id, revision, OperationStep.RESOURCES_READY
    )
    report_resources(resources, initialized)
    return observed, revision


def _retain_candidate_archive(
    slot_directory: Path, archive: Path, runtime: RuntimeSlot
) -> Path:
    """Reuse a verified retained copy or persist the exact setup snapshot."""
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
    return archive_path


def _rebuild_candidate_runtime(
    directory: Path,
    archive: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot,
    uv: Path,
    environment: Mapping[str, str],
) -> None:
    """Recreate a broken exact candidate only while no runtime child holds it."""
    environment_path = runtime_prefix(directory, runtime)
    slot_directory = environment_path.parent
    claim = try_acquire_runtime_quiescence(slot_directory)
    if claim is None:
        raise InstallationError(
            "Candidate runtime is busy; retry repair after its active process exits."
        )
    with claim:
        source_root = slot_directory / "source"
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


def snapshot_metadata(
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


def retained_archive(directory: Path, runtime: RuntimeSlot) -> Path:
    """Return the exact on-disk project snapshot for this slot."""
    archive = runtime_prefix(directory, runtime).with_name("project.zip")
    assert_no_links(archive)
    if (
        not archive.is_file()
        or ut.sha256_file(archive) != runtime.source.digest
    ):
        raise InstallationError(
            "Retained runtime project archive is unavailable or modified."
        )
    return archive


def restore_pending_candidate_archive(
    manager: InstallationManager,
    runtime: RuntimeSlot,
    manager_executable: Path,
) -> Path:
    """Restore the pending slot archive from its authenticated setup product."""
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
    archive = runtime_prefix(manager.directory, runtime).with_name(
        "project.zip"
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
