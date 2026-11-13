"""Transactional managed runtime installation and editable registration."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, TextIO
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from apprc.definition.installation import (
    EditableCheckout,
    InstallationDiagnostic,
    InstallationError,
    InstallPlan,
    InstallationIdentity,
    InstallationPlacement,
    OperationContext,
    OperationStep,
    OwnedOutput,
    PublicationImage,
    PublicationOutput,
    RuntimeSlot,
)
from apprc.definition.paths import ResourceKind
from apprc.distribution.runtime._integration import (
    publish_global_command,
    publish_windows_registration,
    windows_registration_intent,
    remove_owned_command,
    remove_windows_registration,
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
    _sha256_file,
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
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    record_owned_outputs,
    record_publication,
)

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager

_MAINTENANCE_GROUP: contextvars.ContextVar[str] = contextvars.ContextVar(
    "apprc_installation_maintenance_group", default="app"
)


@contextmanager
def installation_maintenance_group(name: str) -> Iterator[None]:
    """Bind native command-group metadata to one installation transaction."""
    if not name or name in {".", ".."} or any(char in name for char in "/\\\x00"):
        raise InstallationError("Maintenance group name is invalid.")
    token = _MAINTENANCE_GROUP.set(name)
    try:
        yield
    finally:
        _MAINTENANCE_GROUP.reset(token)


def _command_filename(command_name: str) -> str:
    if not command_name or command_name in {".", ".."} or any(
        character in command_name for character in "/\\\x00"
    ):
        raise InstallationError("Primary command must be a single filename.")
    return command_name + (".exe" if os.name == "nt" else "")


def _path_entries(environment: Mapping[str, str]) -> tuple[Path, ...]:
    return tuple(
        Path(item).expanduser().absolute()
        for item in environment.get("PATH", "").split(os.pathsep)
        if item
    )


def _command_directory(
    uv: Path,
    selected: Path | None,
    environment: Mapping[str, str],
    forbidden: tuple[Path, ...],
) -> Path:
    if selected is None:
        result = subprocess.run(
            [str(uv), "tool", "dir", "--bin", "--no-config"],
            env=dict(environment),
            capture_output=True,
            text=True,
            check=True,
        )
        selected = Path(result.stdout.strip())
    validate_command_directory(
        selected,
        forbidden=forbidden,
        path_entries=_path_entries(environment),
    )
    return selected


def _check_owned_command(
    destination: Path, previous: tuple[OwnedOutput, ...],
) -> None:
    assert_no_links(destination.parent)
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallationError(f"Refusing to replace unsafe stable command: {destination}.")
    digest = _sha256_file(destination)
    if not any(
        item.kind == "command"
        and item.path == str(destination)
        and item.digest == digest
        for item in previous
    ):
        raise InstallationError(f"Refusing to replace unowned stable command: {destination}.")


def _publish_stable_command(
    destination: Path,
    source: Path,
    *,
    previous: tuple[OwnedOutput, ...],
) -> OwnedOutput:
    _check_owned_command(destination, previous)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".apprc-tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(source_stream, target)
            target.flush()
            os.fsync(target.fileno())
        if os.name != "nt":
            temporary.chmod(0o700)
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return OwnedOutput("command", str(destination), digest)


def _publication_bytes(
    operation_id: UUID,
    index: int,
    content: bytes,
    *,
    mode: int | None = None,
) -> PublicationImage:
    return PublicationImage(
        digest=hashlib.sha256(content).hexdigest(),
        content=f".publication-{operation_id}-{index}",
        mode=mode,
    )


def _publication_image(
    operation_id: UUID,
    index: int,
    path: Path,
    *,
    content: bytes | None = None,
    link_target: str | None = None,
) -> PublicationImage | None:
    if content is not None:
        return _publication_bytes(operation_id, index, content)
    if link_target is not None:
        return PublicationImage(
            digest=hashlib.sha256(os.fsencode(link_target)).hexdigest(),
            link_target=link_target,
        )
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return PublicationImage(
            digest=hashlib.sha256(os.fsencode(target)).hexdigest(),
            link_target=target,
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallationError(f"Cannot transactionally replace unsafe output: {path}.")
    return _publication_bytes(
        operation_id, index, path.read_bytes(), mode=stat.S_IMODE(metadata.st_mode)
    )


def _publication_content(directory: Path, image: PublicationImage) -> bytes:
    if image.content is None:
        raise InstallationError("Publication image does not contain file bytes.")
    path = directory / image.content
    assert_no_links(path)
    if not path.is_file():
        raise InstallationError("Retained publication image is unavailable.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != image.digest:
        raise InstallationError("Retained publication image was modified.")
    return content


def _persist_publication_image(
    directory: Path, image: PublicationImage | None, content: bytes | None,
) -> None:
    if image is None or image.content is None:
        return
    if content is None or hashlib.sha256(content).hexdigest() != image.digest:
        raise InstallationError("Publication recovery bytes do not match their authority.")
    path = directory / image.content
    assert_no_links(path)
    if path.exists():
        if not path.is_file():
            raise InstallationError("Retained publication path is not a regular file.")
        existing = path.read_bytes()
        if existing == content:
            return
        if not content.startswith(existing):
            raise InstallationError("Retained publication image contains unknown bytes.")
        with path.open("ab") as stream:
            stream.write(content[len(existing):])
            stream.flush()
            os.fsync(stream.fileno())
        return
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _record_command_publication(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    outputs: tuple[tuple[Path, bytes | None, str | None], ...],
) -> tuple[PublicationOutput, ...]:
    directory = manager.directory
    publication: list[PublicationOutput] = []
    retained: list[tuple[PublicationImage | None, bytes | None, PublicationImage, bytes | None]] = []
    for index, (path, intended_bytes, link_target) in enumerate(outputs):
        previous = _publication_image(operation_id, index * 2, path)
        previous_bytes = path.read_bytes() if previous is not None and previous.content is not None else None
        intended = _publication_image(
            operation_id,
            index * 2 + 1,
            path,
            content=intended_bytes,
            link_target=link_target,
        )
        if intended is None:
            raise InstallationError("Command publication requires an intended image.")
        for image in (previous, intended):
            if image is not None and image.content is not None:
                retained_path = directory / image.content
                assert_no_links(retained_path)
                if retained_path.exists():
                    raise InstallationError("Unowned publication recovery path already exists.")
        publication.append(PublicationOutput(path, previous, intended))
        retained.append((previous, previous_bytes, intended, intended_bytes))
    recorded = tuple(publication)
    result = record_publication(
        directory,
        operation_id=operation_id,
        expected_revision=revision,
        publication=recorded,
    )
    for previous, previous_bytes, intended, intended_bytes in retained:
        _persist_publication_image(directory, previous, previous_bytes)
        _persist_publication_image(directory, intended, intended_bytes)
    if result.revision is None:
        raise InstallationError("Publication intent has no authority revision.")
    return recorded





def _publication_authorized_outputs(
    publication: tuple[PublicationOutput, ...],
) -> tuple[OwnedOutput, ...]:
    return tuple(
        OwnedOutput("command", str(item.path), item.intended.digest)
        for item in publication
    )


def _existing_publication(
    manager: InstallationManager,
) -> tuple[PublicationOutput, ...]:
    record = manager.inspect().record
    operation = record.operation if record is not None else None
    return operation.publication if operation is not None else ()


def _publication_source(directory: Path, item: PublicationOutput) -> Path:
    if item.intended.content is None:
        raise InstallationError("Command publication requires retained file bytes.")
    path = directory / item.intended.content
    assert_no_links(path)
    if not path.is_file() or _sha256_file(path) != item.intended.digest:
        raise InstallationError("Retained command publication bytes are unavailable or modified.")
    return path


def _ensure_command_publication(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    outputs: tuple[tuple[Path, bytes | None, str | None], ...],
) -> tuple[tuple[PublicationOutput, ...], str]:
    existing = _existing_publication(manager)
    if existing:
        if tuple(item.path for item in existing) != tuple(item[0] for item in outputs):
            raise InstallationError("Pending publication addresses different command outputs.")
        current = manager.inspect()
        if current.revision is None:
            raise InstallationError("Pending publication has no authority revision.")
        for item, (_path, intended_bytes, _link_target) in zip(existing, outputs):
            for image, candidate in (
                (item.previous, None),
                (item.intended, intended_bytes),
            ):
                if image is None or image.content is None:
                    continue
                image_path = manager.directory / image.content
                assert_no_links(image_path)
                if image_path.exists() and image_path.is_file():
                    if _sha256_file(image_path) == image.digest:
                        continue
                if candidate is None:
                    try:
                        if _sha256_file(item.path) == image.digest and item.path.is_file():
                            candidate = item.path.read_bytes()
                    except OSError:
                        candidate = None
                _persist_publication_image(manager.directory, image, candidate)


        return existing, current.revision
    publication = _record_command_publication(
        manager, operation_id, revision, outputs
    )
    current = manager.inspect()
    if current.revision is None:
        raise InstallationError("Recorded publication has no authority revision.")
    return publication, current.revision


def _ensure_registration_intent(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    identity: InstallationIdentity,
    command: Path,
    prior_outputs: tuple[OwnedOutput, ...],
) -> tuple[OwnedOutput | None, str]:
    if os.name != "nt":
        return None, revision
    inspection = manager.inspect()
    intent = windows_registration_intent(
        manager.directory, identity, command,
        maintenance_group_name=_MAINTENANCE_GROUP.get(),
    )
    record = inspection.record
    operation = record.operation if record is not None else None
    if operation is not None and operation.registration is not None:
        if operation.registration != intent:
            raise InstallationError("Pending Windows registration differs from the intended recipe.")
        if inspection.revision is None:
            raise InstallationError("Pending registry intent has no authority revision.")
        return operation.registration, inspection.revision
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, intent.path.removeprefix("HKCU\\"),
            0, winreg.KEY_QUERY_VALUE,
        ) as key:
            prior = any(
                item.kind == "hkcu" and item.path == intent.path
                and item.values == intent.values for item in prior_outputs
            )
            subkeys, count, _ = winreg.QueryInfoKey(key)
            values = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
            if (
                not prior or subkeys or set(values) != set(dict(intent.values))
                or any(
                    values[name] != (value, winreg.REG_SZ)
                    for name, value in intent.values
                )
            ):
                raise InstallationError("Refusing to claim an unowned Windows uninstall key.")
    except FileNotFoundError:
        pass
    from apprc.user_files.installation.operations import record_registration
    updated = record_registration(
        manager.directory,
        operation_id=operation_id,
        expected_revision=revision,
        registration=intent,
    )
    if updated.revision is None:
        raise InstallationError("Recorded registry intent has no authority revision.")
    return intent, updated.revision


def _cleanup_publication_images(
    manager: InstallationManager, inspection: InstallationInspection,
) -> InstallationInspection:
    record = inspection.record
    if record is None or inspection.revision is None:
        return inspection
    retained = tuple(
        output
        for output in record.owned_outputs
        if output.kind == "support" and output.path.startswith(".publication-")
    )
    if not retained:
        return inspection
    keep: list[OwnedOutput] = []
    for output in retained:
        path = manager.directory / output.path
        assert_no_links(path)
        if not path.exists():
            continue
        if not path.is_file() or output.digest is None or _sha256_file(path) != output.digest:
            keep.append(output)
            continue
        path.unlink()
    remaining = tuple(
        output for output in record.owned_outputs if output not in retained
    ) + tuple(keep)
    return record_owned_outputs(
        manager.directory,
        app_id=record.identity.app_id,
        expected_revision=inspection.revision,
        generation_id=record.generation_id,
        owned_outputs=remaining,
    )

def _restore_pending_publication(
    manager: InstallationManager, path: Path, published: OwnedOutput,
) -> bool:
    record = manager.inspect().record
    operation = record.operation if record is not None else None
    if operation is None or published.digest is None:
        return False
    intent = next(
        (item for item in operation.publication if item.path == path),
        None,
    )
    if intent is None or intent.intended.digest != published.digest:
        return False
    assert_no_links(path.parent)
    if path.is_symlink():
        actual = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
    elif path.is_file():
        actual = _sha256_file(path)
    else:
        return False
    if actual != intent.intended.digest:
        return False
    if intent.previous is None:
        path.unlink()
        return True
    if intent.previous.link_target is not None:
        temporary = path.with_name(f".{path.name}.{operation.operation_id}.apprc-tmp")
        assert_no_links(temporary)
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(intent.previous.link_target)
    else:
        content = _publication_content(manager.directory, intent.previous)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".apprc-tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if intent.previous.mode is not None:
            os.chmod(temporary, intent.previous.mode)
    os.replace(temporary, path)
    return True


def _runtime_steps(inspection: InstallationInspection) -> frozenset[OperationStep]:
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
        raise InstallationError(f"{step.value} checkpoint has no authority revision.")
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
        "config", "appdata", "cache", "state"
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
            raise InstallationError("Selected logs resource root is unsafe.") from error
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
) -> None:
    hooks = runtime.hooks
    if identity.apprc_reference is None:
        manager.initialize(context=context)
        if hooks.initialize is not None:
            raise InstallationError("An initialization hook requires an AppRC declaration.")
        _validate_selected_resource_ownership(identity, context.placement)
        return
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
        raise InstallationError("Initialization returned invalid resource capabilities.")
    enabled = {name for name, value in capabilities.items() if value}
    if not enabled.issubset(context.placement.capabilities):
        raise InstallationError(
            "Initialized resource capabilities exceed the selected placement."
        )
    paths = result["paths"]
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise InstallationError("Initialization returned invalid resource paths.")
    resource_paths = {
        "config": context.placement.config_dir,
        "appdata": context.placement.appdata_dir,
        "cache": context.placement.cache_dir,
        "state": context.placement.state_dir,
    }
    if any(enabled_name and resource_paths[name] is None for name, enabled_name in capabilities.items()):
        raise InstallationError("Initialized capability has no selected resource path.")
    expected_paths = [
        str(resource_paths[name])
        for name in ("config", "appdata", "cache", "state")
        if capabilities[name]
    ]
    if capabilities["state"] and context.placement.logs_dir is not None:
        expected_paths.append(str(context.placement.logs_dir))
    if paths != expected_paths:
        raise InstallationError("Initialized resource paths differ from the selected placement.")
    _validate_selected_resource_ownership(identity, context.placement)


def _retire_recorded_runtimes(manager: InstallationManager) -> InstallationInspection:
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


def _failed_operation(
    manager: InstallationManager, operation_id: UUID, error: BaseException,
) -> None:
    latest = manager.inspect()
    record = latest.record
    if (
        record is None
        or record.operation is None
        or record.operation.operation_id != operation_id
        or latest.revision is None
    ):
        return
    manager.fail_operation(
        operation_id=operation_id,
        expected_revision=latest.revision,
        diagnostic=InstallationDiagnostic(
            "runtime-incomplete",
            str(error),
            "Use the original setup to resume this exact runtime candidate or inspect and repair the installation.",
        ),
    )


def _snapshot_metadata(
    archive: Path,
    runtime: RuntimeSlot,
    identity: InstallationIdentity,
) -> str:
    """Read expected metadata only from the digest-verified retained archive."""
    from apprc.distribution.metadata import read_project_metadata

    assert_no_links(archive)
    if _sha256_file(archive) != runtime.source.digest:
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
                raise InstallationError("Retained project archive has no uv.lock.")
            with package.open(lock) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != runtime.source.lock_digest:
                    raise InstallationError("Retained project lock was modified.")
        with tempfile.TemporaryDirectory(prefix="apprc-snapshot-metadata-") as stage:
            root = Path(stage)
            (root / "pyproject.toml").write_bytes(metadata)
            captured = read_project_metadata(root)
    except (OSError, ValueError, KeyError, BadZipFile) as error:
        raise InstallationError("Retained snapshot project metadata is invalid.") from error
    if captured.identity != identity:
        raise InstallationError("Verified snapshot identity differs from installation authority.")
    return captured.version


def _retained_archive(directory: Path, runtime: RuntimeSlot) -> Path:
    archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    assert_no_links(archive)
    if not archive.is_file() or _sha256_file(archive) != runtime.source.digest:
        raise InstallationError("Retained runtime project archive is unavailable or modified.")
    return archive


def _restore_pending_candidate_archive(
    manager: InstallationManager,
    runtime: RuntimeSlot,
    manager_executable: Path,
) -> Path:
    from apprc.distribution.runtime._manager import _executable, _read_product

    if _executable().resolve(strict=True) != manager_executable.resolve(strict=True):
        raise InstallationError("Manager executable does not match the running product.")

    binding, content = _read_product(include_project=True)
    record = manager.inspect().record
    if (
        content is None
        or record is None
        or binding.identity != record.identity
        or binding.source != runtime.source
        or binding.selection != runtime.selection
        or binding.hooks != runtime.hooks
        or hashlib.sha256(content).hexdigest() != runtime.source.digest
    ):
        raise InstallationError(
            "The embedded project does not match the exact pending candidate."
        )
    archive = manager.directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    assert_no_links(archive.parent)
    archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_no_links(archive)
    if archive.exists():
        if _sha256_file(archive) != runtime.source.digest:
            raise InstallationError("Exact pending candidate archive was modified.")
    else:
        with archive.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return archive
def _repair_managed_application(
    manager: InstallationManager,
    *,
    manager_executable: Path,
    uv: Path,
) -> InstallationInspection:
    if not manager_executable.is_absolute() or not manager_executable.is_file():
        raise InstallationError("Managed repair requires its native manager executable.")
    if not uv.is_absolute() or not uv.is_file():
        raise InstallationError("Managed repair requires an absolute manager uv.")
    directory = manager.directory
    with installation_lock(directory):
        prior = manager.inspect()
        record = prior.record
        if record is None or prior.revision is None:
            raise InstallationError("Managed repair requires saved installation authority.")
        stable = directory / _command_filename(record.command_name)
        if record.operation is not None:
            intended = record.operation.intended
            if intended is None or not isinstance(intended.runtime, RuntimeSlot):
                raise InstallationError("No managed candidate is available to resume.")
            runtime = intended.runtime
            plan = InstallPlan(
                directory,
                prior.revision,
                record.generation_id,
                intended,
                record.operation.operation_id,
                record.generation_id,
                "repair",
                record.command_name,
            )
        else:
            active = record.active_runtime
            if not isinstance(active, RuntimeSlot):
                raise InstallationError(
                    "Editable environments are developer-owned; restore with `uv sync --locked`."
                )
            runtime = RuntimeSlot(
                uuid4(), active.source, active.selection, hooks=active.hooks
            )
            plan = manager.plan_repair(record.identity, runtime, record.placement)
        if record.operation is not None:
            candidate_archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
            archive = (
                _retained_archive(directory, runtime)
                if candidate_archive.exists()
                else _restore_pending_candidate_archive(
                    manager, runtime, manager_executable
                )
            )
        else:
            archive = _retained_archive(directory, active)
        current = manager.begin_operation(plan)
        if current.revision is None:
            raise InstallationError("Managed repair has no authority revision.")
        prior_outputs = record.owned_outputs
        pending_publication = _existing_publication(manager)
        _check_owned_command(
            stable,
            (*prior_outputs, *_publication_authorized_outputs(pending_publication)),
        )
        committed = False
        published: OwnedOutput | None = None
        published_commands: list[tuple[Path, OwnedOutput]] = []
        windows_output: OwnedOutput | None = None
        windows_registered = False
        outputs: list[OwnedOutput] = []
        try:
            observed, revision = _prepare_candidate(
                manager, plan, runtime, archive, uv,
                environment=manager.environment,
                manager_executable=manager_executable,
            )
            publication_specs = [(stable, manager_executable.read_bytes(), None)]
            publication_specs.extend(
                (
                    item.path,
                    (
                        None if item.intended.link_target is not None
                        else manager_executable.read_bytes()
                    ),
                    item.intended.link_target,
                )
                for item in pending_publication
                if item.path != stable
            )
            pending_publication, revision = _ensure_command_publication(
                manager,
                plan.operation_id,
                revision,
                tuple(publication_specs),
            )
            publication_authority = _publication_authorized_outputs(pending_publication)
            published = _publish_stable_command(
                stable,
                _publication_source(directory, pending_publication[0]),
                previous=(*prior_outputs, *publication_authority),
            )
            published_commands.append((stable, published))
            outputs = [published]
            for item in pending_publication[1:]:
                if item.intended.link_target is not None:
                    output = publish_global_command(
                        item.path,
                        Path(item.intended.link_target),
                        previous=(*prior_outputs, *publication_authority),
                    )
                else:
                    output = publish_global_command(
                        item.path,
                        _publication_source(directory, item),
                        previous=(*prior_outputs, *publication_authority),
                    )
                published_commands.append((item.path, output))
                outputs.append(output)
            registration_intent, revision = _ensure_registration_intent(
                manager, plan.operation_id, revision, record.identity, stable,
                prior_outputs,
            )
            windows_output = publish_windows_registration(
                directory,
                record.identity,
                stable,
                previous=(
                    *prior_outputs,
                    *((registration_intent,) if registration_intent is not None else ()),
                ),
                maintenance_group_name=_MAINTENANCE_GROUP.get(),
            )
            windows_registered = (
                windows_output is not None and windows_output not in prior_outputs
            )
            if windows_output is not None:
                outputs.append(windows_output)
            output_paths = {item.path for item in outputs}
            outputs.extend(
                item for item in prior_outputs if item.path not in output_paths
            )
            current = _checkpoint(
                manager, plan.operation_id, revision, OperationStep.SUPPORT_READY
            )
            current = _checkpoint(
                manager, plan.operation_id, current.revision or "",
                OperationStep.REGISTRATION_READY,
            )
            result = manager.commit_install(
                operation_id=plan.operation_id,
                expected_revision=current.revision or "",
                observed=observed,
                owned_outputs=tuple(outputs),
            )
            committed = True
            result = _cleanup_publication_images(manager, result)
            return _retire_recorded_runtimes(manager) if result.record else result
        except BaseException as error:
            if not committed:
                for path, output in published_commands:
                    _restore_pending_publication(manager, path, output)
                if windows_registered and windows_output is not None:
                    remove_windows_registration(windows_output)
                _failed_operation(manager, plan.operation_id, error)
            raise




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
        raise InstallationError("Candidate runtime is busy; retry repair after its active process exits.")
    try:
        source_root = slot_directory / "source"
        environment_path = slot_directory / ".venv"
        for target in (source_root, environment_path):
            assert_no_links(target)
            if target.exists():
                if not target.is_dir():
                    raise InstallationError("Candidate runtime path is not a directory.")
                shutil.rmtree(target)
        source_root.mkdir(mode=0o700)
        materialize_project_snapshot(archive, source_root, runtime.source)
        with claim.authorize_bridge():
            sync_runtime_slot(uv, directory, identity, runtime, environment=environment)
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
) -> tuple[RuntimeSlot, str]:
    directory = manager.directory
    identity = plan.target.identity
    operation_id = plan.operation_id
    generation_id = plan.generation_id
    revision = manager.inspect().revision
    if revision is None:
        raise InstallationError("Pending installation has no authority revision.")
    slot_directory = directory / "runtimes" / str(runtime.slot_id)
    assert_no_links(slot_directory.parent)
    slot_directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_no_links(slot_directory.parent)
    if slot_directory.exists():
        assert_no_links(slot_directory)
        if not slot_directory.is_dir():
            raise InstallationError("Runtime candidate address is not a directory.")
    else:
        slot_directory.mkdir(mode=0o700)
    archive_path = slot_directory / "project.zip"
    assert_no_links(archive_path)
    if archive_path.exists():
        if _sha256_file(archive_path) != runtime.source.digest:
            raise InstallationError("Retained candidate project archive was modified.")
    else:
        assert_no_links(archive)
        if _sha256_file(archive) != runtime.source.digest:
            raise InstallationError("Setup project archive differs from the runtime binding.")
        with archive.open("rb") as source, archive_path.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    steps = _runtime_steps(manager.inspect())
    source_root = slot_directory / "source"
    environment_path = slot_directory / ".venv"
    expected_version = _snapshot_metadata(archive_path, runtime, identity)
    if OperationStep.RUNTIME_PREPARED not in steps:
        _rebuild_candidate_runtime(
            slot_directory, archive_path, directory, identity, runtime, uv, environment
        )
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
            slot_directory, archive_path, directory, identity, runtime, uv, environment
        )
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
        _rebuild_candidate_runtime(
            slot_directory, archive_path, directory, identity, runtime, uv, environment
        )
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
        raise InstallationError("Managed candidate probe returned an editable runtime.")
    if observed.version != expected_version:
        raise InstallationError(
            "Installed distribution version differs from the immutable project snapshot."
        )
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
    _initialize_runtime(
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
    return observed, current.revision or ""


def install_application(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: RuntimeSlot,
    placement: InstallationPlacement,
    *,
    command_name: str,
    project_archive: Path,
    manager_executable: Path,
    uv: Path,
    command_directory: Path | None = None,
    assume_yes: bool = False,
) -> InstallationInspection:
    if not manager_executable.is_absolute() or not manager_executable.is_file():
        raise InstallationError("Managed installation requires its setup executable.")
    if not uv.is_absolute() or not uv.is_file():
        raise InstallationError("Managed installation requires an absolute manager uv.")
    if not project_archive.is_absolute() or not project_archive.is_file():
        raise InstallationError("Managed installation requires its embedded project archive.")
    directory = manager.directory
    environment = manager.environment
    with installation_lock(directory):
        prior = manager.inspect()
        previous = prior.record
        if previous is not None and previous.operation is not None:
            intended = previous.operation.intended
            if intended is None or not isinstance(intended.runtime, RuntimeSlot):
                raise InstallationError("Pending operation has no managed runtime candidate.")
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
                raise InstallationError("Switching editable mode requires --yes confirmation.")
        stable = directory / _command_filename(command_name)
        prior_outputs = previous.owned_outputs if previous is not None else ()
        pending_publication = _existing_publication(manager)
        publication_authority = _publication_authorized_outputs(pending_publication)
        _check_owned_command(stable, (*prior_outputs, *publication_authority))
        global_directory: Path | None = None
        global_command: Path | None = None
        if command_directory is not None:
            global_directory = _command_directory(
                uv,
                command_directory,
                environment,
                (directory, runtime_prefix(directory, runtime)),
            )
            global_command = global_directory / _command_filename(command_name)
            validate_global_command(
                global_command,
                previous=(*prior_outputs, *publication_authority),
            )
        if global_command is None and len(pending_publication) > 1:
            global_command = pending_publication[1].path
            global_directory = global_command.parent
            validate_global_command(
                global_command,
                previous=(*prior_outputs, *publication_authority),
            )
        if previous is not None and previous.operation is not None:
            intended = previous.operation.intended
            if intended is None or not isinstance(intended.runtime, RuntimeSlot):
                raise InstallationError("Pending candidate is not a managed runtime.")
            runtime = intended.runtime
            pending_archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
            if pending_archive.is_file():
                if _sha256_file(pending_archive) != runtime.source.digest:
                    raise InstallationError("Exact pending candidate archive was modified.")
                project_archive = pending_archive
            elif _sha256_file(project_archive) != runtime.source.digest:
                raise InstallationError(
                    "Setup project snapshot differs from the exact pending candidate."
                )
            plan = InstallPlan(
                directory,
                prior.revision or "",
                previous.generation_id,
                intended,
                previous.operation.operation_id,
                previous.generation_id,
                "repair",
                previous.command_name,
            )
        else:
            plan = manager.plan_install(
                identity, runtime, placement, command_name=command_name
            )
        current = manager.begin_operation(plan)
        if current.revision is None:
            raise InstallationError("Pending managed installation has no revision.")
        operation_id = plan.operation_id
        stable_output: OwnedOutput | None = None
        global_output: OwnedOutput | None = None
        committed = False
        windows_output: OwnedOutput | None = None
        windows_registered = False
        try:
            observed, revision = _prepare_candidate(
                manager,
                plan,
                runtime,
                project_archive,
                uv,
                environment=environment,
                manager_executable=manager_executable,
            )
            publication_specs: tuple[tuple[Path, bytes | None, str | None], ...] = (
                (stable, manager_executable.read_bytes(), None),
            )
            if global_command is not None:
                publication_specs += (
                    (global_command, None, str(stable))
                    if os.name != "nt"
                    else (global_command, manager_executable.read_bytes(), None),
                )
            pending_publication, revision = _ensure_command_publication(
                manager, operation_id, revision, publication_specs
            )
            publication_authority = _publication_authorized_outputs(pending_publication)
            stable_output = _publish_stable_command(
                stable,
                _publication_source(directory, pending_publication[0]),
                previous=(*prior_outputs, *publication_authority),
            )
            outputs = [stable_output]
            if global_command is not None:
                if len(pending_publication) < 2:
                    raise InstallationError("Pending global command publication is missing.")
                if pending_publication[1].intended.link_target is not None:
                    global_output = publish_global_command(
                        global_command,
                        stable,
                        previous=(*prior_outputs, *publication_authority),
                    )
                else:
                    global_output = publish_global_command(
                        global_command,
                        _publication_source(directory, pending_publication[1]),
                        previous=(*prior_outputs, *publication_authority),
                    )
                outputs.append(global_output)
            registration_intent, revision = _ensure_registration_intent(
                manager, operation_id, revision, identity, stable, prior_outputs
            )
            windows_output = publish_windows_registration(
                directory, identity, stable,
                previous=(
                    *prior_outputs,
                    *((registration_intent,) if registration_intent is not None else ()),
                ),
                maintenance_group_name=_MAINTENANCE_GROUP.get(),
            )
            if windows_output is not None:
                outputs.append(windows_output)
                windows_registered = not any(
                    item.kind == "hkcu" and item.path == windows_output.path
                    for item in prior_outputs
                )
            output_paths = {item.path for item in outputs}
            outputs.extend(
                item for item in prior_outputs if item.path not in output_paths
            )
            current = _checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.SUPPORT_READY,
            )
            revision = current.revision or ""
            current = _checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.REGISTRATION_READY,
            )
            revision = current.revision or ""
            result = manager.commit_install(
                operation_id=operation_id,
                expected_revision=revision,
                observed=observed,
                owned_outputs=tuple(outputs),
            )
            committed = True
            result = _cleanup_publication_images(manager, result)
            return _retire_recorded_runtimes(manager) if result.record else result
        except BaseException as error:
            if not committed:
                if stable_output is not None:
                    _restore_pending_publication(manager, stable, stable_output)
                if global_output is not None and global_command is not None:
                    _restore_pending_publication(manager, global_command, global_output)
                if windows_registered and windows_output is not None:
                    remove_windows_registration(windows_output)
                _failed_operation(manager, operation_id, error)
            raise


def _editable_command_directory(
    manager: InstallationManager, runtime: EditableCheckout, uv: Path, selected: Path | None,
) -> Path:
    environment = manager.environment
    return _command_directory(
        uv,
        selected,
        environment,
        (runtime.project, runtime.environment, runtime.environment.parent, manager.directory),
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
        raise InstallationError("Editable distribution metadata probe is invalid.") from error
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("distribution"), str)
        or metadata["distribution"].lower().replace("_", "-")
        != identity.distribution.lower().replace("_", "-")
        or not isinstance(metadata.get("commands"), dict)
        or not set(identity.commands).issubset(metadata["commands"])
    ):
        raise InstallationError("Editable environment does not own the declared distribution commands.")


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
) -> InstallationInspection:
    """Register the existing checkout environment without managing its files."""
    if not runtime.project.is_absolute() or not runtime.environment.is_absolute():
        raise InstallationError("Editable paths must be absolute.")
    project = runtime.project.resolve(strict=True)
    environment_path = runtime.environment.resolve(strict=True)
    from apprc.definition.resolution import resolve_editable_environment

    if (
        resolve_editable_environment(project).resolve(strict=True) != environment_path
        or not (project / "pyproject.toml").is_file()
    ):
        raise InstallationError(
            "Editable registration requires the selected project's existing workspace .venv."
        )
    runtime = EditableCheckout(project, environment_path, runtime.hooks)
    if Path(sys.prefix).resolve(strict=True) != environment_path:
        raise InstallationError(
            "The current interpreter is not this checkout's .venv; run `uv run --locked <command> app install -e`."
        )
    interpreter = runtime_interpreter(manager.directory, runtime)
    if not interpreter.is_file():
        raise InstallationError(
            "Editable environment is unavailable; run `uv run --locked <command> app install -e`."
        )
    environment = manager.environment
    _validate_editable_metadata(interpreter, identity, environment)
    with installation_lock(manager.directory):
        prior = manager.inspect()
        previous = prior.record
        if previous is not None and previous.status != "removed-retained":
            prior_runtime = previous.active_runtime
            same_checkout = isinstance(prior_runtime, EditableCheckout) and (
                prior_runtime.project.resolve(strict=False) == project
                and prior_runtime.environment.resolve(strict=False) == environment_path
            )
            if not same_checkout and not assume_yes:
                raise InstallationError("Switching installation ownership requires --yes confirmation.")
            placement = previous.placement
        selected_directory = _editable_command_directory(
            manager, runtime, uv, command_directory
        )
        global_command = selected_directory / _command_filename(command_name)
        prior_outputs = previous.owned_outputs if previous is not None else ()
        pending_publication = _existing_publication(manager)
        publication_authority = _publication_authorized_outputs(pending_publication)
        validate_global_command(
            global_command,
            previous=(*prior_outputs, *publication_authority),
        )
        if previous is not None and previous.operation is not None:
            plan = manager.plan_repair(identity, runtime, placement)
            if plan.target.runtime != runtime:
                raise InstallationError("Pending registration addresses another checkout.")
        else:
            plan = manager.plan_install(
                identity, runtime, placement, command_name=command_name
            )
        current = manager.begin_operation(plan)
        if current.revision is None:
            raise InstallationError("Pending editable registration has no revision.")
        operation_id = plan.operation_id
        committed = False
        published: OwnedOutput | None = None
        try:
            observed, observations = _probe_runtime_observations(
                manager.directory,
                identity,
                runtime,
                command_name=command_name,
                environment=dict(environment),
                expected_revision=current.revision,
            )
            if not isinstance(observed, EditableCheckout):
                raise InstallationError("Editable probe returned a managed runtime.")
            current = _checkpoint(
                manager, operation_id, current.revision, OperationStep.RUNTIME_PREPARED
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
            _initialize_runtime(
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
            command = runtime_command(manager.directory, runtime, command_name)
            publication_specs = (
                ((global_command, None, str(command)),)
                if os.name != "nt"
                else ((global_command, command.read_bytes(), None),)
            )
            pending_publication, revision = _ensure_command_publication(
                manager, operation_id, revision, publication_specs
            )
            publication_authority = _publication_authorized_outputs(pending_publication)
            if pending_publication[0].intended.link_target is not None:
                output = publish_global_command(
                    global_command,
                    Path(pending_publication[0].intended.link_target),
                    previous=(*prior_outputs, *publication_authority),
                )
            else:
                output = publish_global_command(
                    global_command,
                    _publication_source(manager.directory, pending_publication[0]),
                    previous=(*prior_outputs, *publication_authority),
                )
            published = output
            outputs = [
                *(
                    item for item in prior_outputs
                    if item.path != output.path
                ),
                output,
            ]
            current = _checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.SUPPORT_READY,
            )
            revision = current.revision or ""
            current = _checkpoint(
                manager,
                operation_id,
                revision,
                OperationStep.REGISTRATION_READY,
            )
            revision = current.revision or ""
            result = manager.commit_install(
                operation_id=operation_id,
                expected_revision=revision,
                observed=observed,
                owned_outputs=tuple(outputs),
            )
            committed = True
            result = _cleanup_publication_images(manager, result)
            return _retire_recorded_runtimes(manager) if result.record else result
        except BaseException as error:
            if not committed:
                if published is not None:
                    _restore_pending_publication(manager, global_command, published)
                _failed_operation(manager, operation_id, error)
            raise


def offer_configuration_setup(
    inspection: InstallationInspection,
    *,
    skip: bool,
    input_stream: TextIO | None = None,
) -> bool:
    """Offer the primary runtime's optional config setup after Ready."""
    record = inspection.require_usable()
    if record is None or record.active_runtime is None:
        raise InstallationError("Configuration setup requires a usable runtime.")
    if "config" not in record.placement.capabilities:
        return False
    command_name = record.command_name
    guidance = f"Run `{command_name} config setup` to configure the application."
    if skip:
        print(guidance)
        return False
    stream = input_stream if input_stream is not None else sys.stdin
    if not stream.isatty():
        print(guidance)
        return False
    print(f"Run `{command_name} config setup` now? [y/N]")
    answer = input_stream.readline() if input_stream is not None else input()
    if answer.strip().lower() not in {"y", "yes"}:
        print(guidance)
        return False
    directory = inspection.directory
    with installation_lock(directory):
        latest = inspect_installation(directory, app_id=record.identity.app_id)
        if latest.record is None or latest.record.active_runtime != record.active_runtime:
            print(guidance)
            return False
        lease: RuntimeLease | None = None
        if isinstance(record.active_runtime, RuntimeSlot):
            lease = acquire_runtime_lease(
                directory / "runtimes" / str(record.active_runtime.slot_id)
            )
    runtime = record.active_runtime
    command = runtime_command(directory, runtime, command_name)
    environment = dict(os.environ)
    if lease is not None:
        environment = lease.environment(environment)
        spawn_options = lease.subprocess_options()
    else:
        environment.pop("_APPRC_RUNTIME_LEASE_HANDLE", None)
        spawn_options = {}
    environment = runtime_environment(environment)
    if lease is not None:
        environment = lease.environment(environment)
    environment["VIRTUAL_ENV"] = str(runtime_prefix(directory, runtime))
    binary = str(runtime_prefix(directory, runtime) / ("Scripts" if os.name == "nt" else "bin"))
    environment["PATH"] = binary + os.pathsep + environment.get("PATH", "")
    try:
        subprocess.run(
            [str(command), "config", "setup"],
            env=environment,
            check=True,
            **spawn_options,
        )
    except (OSError, subprocess.CalledProcessError):
        print(guidance)
        return False
    finally:
        if lease is not None:
            lease.close()
    return True


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
    from apprc.distribution.runtime._integration import publish_shortcuts
    from apprc.user_files.installation.operations import record_owned_outputs

    directory = manager.directory
    with installation_lock(directory):
        inspection = manager.inspect()
        record = inspection.record
        if (
            record is None or record.status != "ready" or inspection.revision is None
            or record.identity != identity
        ):
            print("Warning: optional shortcuts were not updated.", file=sys.stderr)
            return inspection
        previous = tuple(item for item in record.owned_outputs if item.kind == "shortcut")
        created: tuple[OwnedOutput, ...] = ()
        try:
            created = publish_shortcuts(
                command, identity, display_name=display_name,
                start_menu=start_menu, desktop=desktop,
                launch_enabled=launch_enabled, previous=previous,
            )
            created_paths = {item.path for item in created}
            outputs = tuple(
                item for item in record.owned_outputs
                if item.kind != "shortcut" or item.path not in created_paths
            ) + created
            return record_owned_outputs(
                directory,
                app_id=identity.app_id,
                expected_revision=inspection.revision,
                generation_id=record.generation_id,
                owned_outputs=outputs,
            )
        except Exception as error:
            from apprc.distribution.runtime._integration import remove_owned_command

            for output in created:
                try:
                    remove_owned_command(output)
                except InstallationError:
                    pass
            print(f"Warning: optional shortcuts were not updated: {error}", file=sys.stderr)
            return manager.inspect()
