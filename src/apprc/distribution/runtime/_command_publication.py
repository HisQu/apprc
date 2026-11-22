"""Journal and publish installation commands under the lifecycle lock."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import apprc.utils as ut
from apprc.definition.installation import (
    InstallationError,
    InstallationInspection,
    OwnedOutput,
    PublicationImage,
    PublicationOutput,
)
from apprc.distribution.runtime._install_progress import report
from apprc.distribution.runtime._os_integration import (
    command_is_owned,
    publish_global_command,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation.operations import (
    record_owned_outputs,
    record_publication,
)

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager


def check_owned_stable_command(
    destination: Path,
    previous: tuple[OwnedOutput, ...],
) -> str | None:
    """Check exact ownership of a stable executable, when present.

    :param destination: Stable executable address.
    :param previous: Recorded ownership accepted at that address.
    :return: Current digest, or ``None`` if the executable is absent.
    """
    assert_no_links(destination.parent)
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallationError(
            f"Refusing to replace unsafe stable command: {destination}."
        )
    digest = ut.sha256_file(destination)
    if not command_is_owned(destination, previous, digest):
        raise InstallationError(
            f"Refusing to replace unowned stable command: {destination}."
        )
    return digest


def _publish_stable_command(
    destination: Path,
    source: Path,
    *,
    previous: tuple[OwnedOutput, ...],
) -> OwnedOutput:
    check_owned_stable_command(destination, previous)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".apprc-tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with (
            source.open("rb") as source_stream,
            os.fdopen(descriptor, "wb") as target,
        ):
            shutil.copyfileobj(source_stream, target)
            target.flush()
            os.fsync(target.fileno())
        if os.name != "nt":
            temporary.chmod(0o700)
        digest = ut.sha256_file(temporary)
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
        raise InstallationError(
            f"Cannot transactionally replace unsafe output: {path}."
        )
    return _publication_bytes(
        operation_id,
        index,
        path.read_bytes(),
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _publication_content(directory: Path, image: PublicationImage) -> bytes:
    if image.content is None:
        raise InstallationError(
            "Publication image does not contain file bytes."
        )
    path = directory / image.content
    assert_no_links(path)
    if not path.is_file():
        raise InstallationError("Retained publication image is unavailable.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != image.digest:
        raise InstallationError("Retained publication image was modified.")
    return content


def _persist_publication_image(
    directory: Path,
    image: PublicationImage | None,
    content: bytes | None,
) -> None:
    if image is None or image.content is None:
        return
    if content is None or hashlib.sha256(content).hexdigest() != image.digest:
        raise InstallationError(
            "Publication recovery bytes do not match their authority."
        )
    path = directory / image.content
    assert_no_links(path)
    if path.exists():
        if not path.is_file():
            raise InstallationError(
                "Retained publication path is not a regular file."
            )
        existing = path.read_bytes()
        if existing == content:
            return
        if not content.startswith(existing):
            raise InstallationError(
                "Retained publication image contains unknown bytes."
            )
        with path.open("ab") as stream:
            stream.write(content[len(existing) :])
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
    *,
    user_path_command: Path | None = None,
) -> tuple[PublicationOutput, ...]:
    directory = manager.directory
    publication: list[PublicationOutput] = []
    retained: list[
        tuple[
            PublicationImage | None,
            bytes | None,
            PublicationImage,
            bytes | None,
        ]
    ] = []
    for index, (path, intended_bytes, link_target) in enumerate(outputs):
        previous = _publication_image(operation_id, index * 2, path)
        previous_bytes = (
            path.read_bytes()
            if previous is not None and previous.content is not None
            else None
        )
        intended = _publication_image(
            operation_id,
            index * 2 + 1,
            path,
            content=intended_bytes,
            link_target=link_target,
        )
        if intended is None:
            raise InstallationError(
                "Command publication requires an intended image."
            )
        for image in (previous, intended):
            if image is not None and image.content is not None:
                retained_path = directory / image.content
                assert_no_links(retained_path)
                if retained_path.exists():
                    raise InstallationError(
                        "Unowned publication recovery path already exists."
                    )
        publication.append(
            PublicationOutput(
                path,
                previous,
                intended,
                update_user_path=path == user_path_command,
            )
        )
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


def authorized_outputs(
    publication: tuple[PublicationOutput, ...],
) -> tuple[OwnedOutput, ...]:
    """Accept exact intended output from a pending or resumed publication.

    :param publication: Command intent captured in the installation record.
    :return: Ownership entries derived from each recorded intended digest.
    """
    return tuple(
        OwnedOutput("command", str(item.path), item.intended.digest)
        for item in publication
    )


def pending_publication(
    manager: InstallationManager,
) -> tuple[PublicationOutput, ...]:
    """Read the current operation's recorded command intent.

    :param manager: Installation owning the operation.
    :return: Recorded output intents, or an empty tuple without an operation.
    """
    record = manager.inspect().record
    operation = record.operation if record is not None else None
    return operation.publication if operation is not None else ()


def _publication_source(directory: Path, item: PublicationOutput) -> Path:
    if item.intended.content is None:
        raise InstallationError(
            "Command publication requires retained file bytes."
        )
    path = directory / item.intended.content
    assert_no_links(path)
    if not path.is_file() or ut.sha256_file(path) != item.intended.digest:
        raise InstallationError(
            "Retained command publication bytes are unavailable or modified."
        )
    return path


def _ensure_command_publication(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    outputs: tuple[tuple[Path, bytes | None, str | None], ...],
    *,
    user_path_command: Path | None = None,
) -> tuple[tuple[PublicationOutput, ...], str]:
    existing = pending_publication(manager)
    if existing:
        if tuple(item.path for item in existing) != tuple(
            item[0] for item in outputs
        ):
            raise InstallationError(
                "Pending publication addresses different command outputs."
            )
        current = manager.inspect()
        if current.revision is None:
            raise InstallationError(
                "Pending publication has no authority revision."
            )
        for item, (_path, intended_bytes, _link_target) in zip(
            existing, outputs
        ):
            for image, candidate in (
                (item.previous, None),
                (item.intended, intended_bytes),
            ):
                if image is None or image.content is None:
                    continue
                image_path = manager.directory / image.content
                assert_no_links(image_path)
                if image_path.exists() and image_path.is_file():
                    if ut.sha256_file(image_path) == image.digest:
                        continue
                if candidate is None:
                    try:
                        if (
                            ut.sha256_file(item.path) == image.digest
                            and item.path.is_file()
                        ):
                            candidate = item.path.read_bytes()
                    except OSError:
                        candidate = None
                _persist_publication_image(manager.directory, image, candidate)

        return existing, current.revision
    publication = _record_command_publication(
        manager,
        operation_id,
        revision,
        outputs,
        user_path_command=user_path_command,
    )
    current = manager.inspect()
    if current.revision is None:
        raise InstallationError(
            "Recorded publication has no authority revision."
        )
    return publication, current.revision


def publish_commands(
    manager: InstallationManager,
    operation_id: UUID,
    revision: str,
    outputs: tuple[tuple[Path, bytes | None, str | None], ...],
    *,
    prior_outputs: tuple[OwnedOutput, ...],
    stable: Path | None = None,
    user_path_command: Path | None = None,
) -> tuple[list[OwnedOutput], str]:
    """Persist publication intent, then publish each command in recorded order.

    :param manager: Installation whose lifecycle lock is held by the caller.
    :param operation_id: Pending operation that owns publication.
    :param revision: Expected authority revision before recording new intent.
    :param outputs: Ordered destinations with intended bytes or link targets.
    :param prior_outputs: Previously owned output accepted for replacement.
    :param stable: Managed stable executable address, when one is published.
    :param user_path_command: Global command eligible to update user PATH.
    :return: Published commands in recorded order and the revised authority.
    """
    publication, revision = _ensure_command_publication(
        manager,
        operation_id,
        revision,
        outputs,
        user_path_command=user_path_command,
    )
    authority = (*prior_outputs, *authorized_outputs(publication))
    published: list[OwnedOutput] = []
    for item in publication:
        if item.path == stable:
            output = _publish_stable_command(
                item.path,
                _publication_source(manager.directory, item),
                previous=authority,
            )
            report("result", "Native executable", "PUBLISHED", item.path)
        else:
            source = (
                Path(item.intended.link_target)
                if item.intended.link_target is not None
                else _publication_source(manager.directory, item)
            )
            output = publish_global_command(
                item.path, source, previous=authority
            )
            report("result", "Global command", "PUBLISHED", item.path)
        published.append(output)
    return published, revision


def cleanup_publication_images(
    manager: InstallationManager,
    inspection: InstallationInspection,
) -> InstallationInspection:
    """Remove unchanged publication images after activation.

    :param manager: Installation whose lifecycle lock is held by the caller.
    :param inspection: Activated authority with the retained outputs.
    :return: Authority retaining any publication images that changed.
    """
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
        if (
            not path.is_file()
            or output.digest is None
            or ut.sha256_file(path) != output.digest
        ):
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
    manager: InstallationManager,
    path: Path,
    published: OwnedOutput | None = None,
) -> bool:
    """Restore recorded command intent, including publishers that raised early.

    :param manager: Locked installation owning the pending publication.
    :param path: Exact destination recorded before publication.
    :param published: Optional expected ownership of an already returned output.
    :return: Whether the destination now matches its recorded previous image.
    """
    record = manager.inspect().record
    operation = record.operation if record is not None else None
    if operation is None:
        return False
    intent = next(
        (item for item in operation.publication if item.path == path),
        None,
    )
    if intent is None or (
        published is not None and intent.intended.digest != published.digest
    ):
        return False
    assert_no_links(path.parent)
    if path.is_symlink():
        actual = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
    elif path.is_file():
        actual = ut.sha256_file(path)
    else:
        return not path.exists() and intent.previous is None
    previous = intent.previous
    if previous is not None and actual == previous.digest:
        if previous.link_target is not None:
            return (
                path.is_symlink() and os.readlink(path) == previous.link_target
            )
        if not path.is_symlink() and (
            previous.mode is None
            or stat.S_IMODE(path.stat().st_mode) == previous.mode
        ):
            return True
    if actual != intent.intended.digest:
        return False
    if path.is_symlink() != (intent.intended.link_target is not None):
        return False
    if intent.previous is None:
        path.unlink()
        return True
    if intent.previous.link_target is not None:
        temporary = path.with_name(
            f".{path.name}.{operation.operation_id}.apprc-tmp"
        )
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
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def restore_commands(
    manager: InstallationManager, publication: tuple[PublicationOutput, ...]
) -> None:
    """Restore durable before-images in reverse publication order.

    :param manager: Installation whose lifecycle lock is held by the caller.
    :param publication: Recorded outputs to restore, in publication order.
    """
    for item in reversed(publication):
        if not _restore_pending_publication(manager, item.path):
            raise InstallationError(
                f"Command changed outside this installation attempt: {item.path}."
            )


def discard_rollback_images(
    directory: Path,
    publication: tuple[PublicationOutput, ...],
    previous_publication: tuple[PublicationOutput, ...],
) -> None:
    """Remove exact-owned rollback images that are absent from prior authority.

    :param directory: Authority directory protected by the lifecycle lock.
    :param publication: Pending publication restored before this cleanup.
    :param previous_publication: Images still referenced by the prior authority.
    """
    prior_images = {
        image.content
        for item in previous_publication
        for image in (item.previous, item.intended)
        if image is not None and image.content is not None
    }
    for item in publication:
        for image in (item.previous, item.intended):
            if (
                image is None
                or image.content is None
                or image.content in prior_images
            ):
                continue
            path = directory / image.content
            assert_no_links(path)
            if path.exists():
                if not path.is_file() or ut.sha256_file(path) != image.digest:
                    raise InstallationError(
                        f"Publication recovery image changed: {path}."
                    )
                path.unlink()
