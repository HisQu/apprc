"""Verified project archive materialization and private staging safeguards."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tarfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import IO
from zipfile import BadZipFile, ZipFile, is_zipfile

from apprc.definition.installation import InstallationError, ProjectSnapshot
from apprc.distribution.models import relative_destination
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    _path_permissions_are_private,
    create_private_directory_if_missing,
)


def _assert_private_staging(staging: Path) -> None:
    """Create and validate a private operation-owned staging directory."""
    if not staging.is_absolute():
        raise InstallationError("Source staging directory must be absolute.")
    create_private_directory_if_missing(staging)
    assert_no_links(staging)
    if not _path_permissions_are_private(staging):
        if os.name == "nt":
            raise InstallationError(
                "Source staging directory does not have a private Windows ACL."
            )
        raise InstallationError("Source staging directory must be private.")


def _sha256_file(path: Path) -> str:
    """Hash a file without loading its complete contents into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_paths(
    names: Sequence[tuple[str, bool]],
    *,
    strip_wrapper: bool = True,
) -> tuple[tuple[Path, ...], str | None]:
    """Validate portable member names and remove only an unambiguous wrapper."""
    paths = []
    seen: set[str] = set()
    files: set[str] = set()
    for name, directory in names:
        cleaned = name.rstrip("/")
        while cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if cleaned in {"", "."} and directory:
            paths.append(Path("."))
            continue
        try:
            relative = relative_destination(cleaned)
        except ValueError as error:
            raise InstallationError(
                "Unsafe source archive member path."
            ) from error
        if any(
            part.endswith((" ", "."))
            or part.split(".")[0].casefold()
            in {
                "con",
                "prn",
                "aux",
                "nul",
                *(f"com{i}" for i in range(1, 10)),
                *(f"lpt{i}" for i in range(1, 10)),
            }
            for part in relative.parts
        ):
            raise InstallationError(
                "Source archive has an ambiguous native path."
            )
        key = str(relative).casefold()
        if key in seen:
            raise InstallationError(
                "Source archive has duplicate member paths."
            )
        seen.add(key)
        if not directory:
            files.add(key)
        paths.append(Path(*relative.parts))
    for path in paths:
        if any(
            parent.as_posix().casefold() in files for parent in path.parents
        ):
            raise InstallationError(
                "Source archive has conflicting member paths."
            )
    roots = {path.parts[0] for path in paths if path.parts}
    wrapper = (
        next(iter(roots))
        if strip_wrapper
        and len(roots) == 1
        and all(
            not path.parts or len(path.parts) > 1 or directory
            for path, (_, directory) in zip(paths, names, strict=True)
        )
        else None
    )
    return (
        tuple(
            Path(*path.parts[1:]) if wrapper and path.parts else path
            for path in paths
        ),
        wrapper,
    )


def _archive_inputs(
    archive: Path,
    root: Path,
    *,
    extract: bool,
    strip_wrapper: bool = True,
) -> None:
    """Extract or compare original regular inputs, never backend-created files.

    Links and special members are deliberately unsupported: neither tar link
    resolution nor platform-specific ZIP attributes may redirect writes.
    """
    try:
        # > ZIP probing can recognize a wheel embedded near the end of a TAR.
        # > Prefer the outer TAR so its project inputs are not skipped.
        if not tarfile.is_tarfile(archive) and is_zipfile(archive):
            with ZipFile(archive) as package:
                members = package.infolist()
                paths, _ = _archive_paths(
                    [
                        (member.orig_filename, member.is_dir())
                        for member in members
                    ],
                    strip_wrapper=strip_wrapper,
                )
                if any(
                    stat.S_IFMT(member.external_attr >> 16)
                    not in {0, stat.S_IFREG, stat.S_IFDIR}
                    for member in members
                ):
                    raise InstallationError(
                        "Source archive contains a link or special member."
                    )
                for member, relative in zip(members, paths, strict=True):
                    mode = member.external_attr >> 16
                    if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise InstallationError(
                            "Source archive contains a link or special member."
                        )
                    target = root / relative
                    if member.is_dir():
                        if extract:
                            target.mkdir(parents=True, exist_ok=True)
                        continue
                    with package.open(member) as stream:
                        _archive_input(
                            stream, target, extract=extract, mode=mode
                        )
        else:
            with tarfile.open(archive, "r:*") as package:
                members = package.getmembers()
                paths, _ = _archive_paths(
                    [(member.name, member.isdir()) for member in members],
                    strip_wrapper=strip_wrapper,
                )
                if any(
                    not member.isdir() and not member.isfile()
                    for member in members
                ):
                    raise InstallationError(
                        "Source archive contains a link or special member."
                    )
                for member, relative in zip(members, paths, strict=True):
                    if not member.isdir() and not member.isfile():
                        raise InstallationError(
                            "Source archive contains a link or special member."
                        )
                    target = root / relative
                    if member.isdir():
                        if extract:
                            target.mkdir(parents=True, exist_ok=True)
                        continue
                    stream = package.extractfile(member)
                    if stream is None:
                        raise InstallationError(
                            "Source archive member is unavailable."
                        )
                    with stream:
                        _archive_input(
                            stream, target, extract=extract, mode=member.mode
                        )
    except (OSError, tarfile.TarError, ValueError) as error:
        raise InstallationError(
            f"Source archive cannot be materialized or verified: {error}"
        ) from error


def _archive_input(
    stream: IO[bytes], target: Path, *, extract: bool, mode: int
) -> None:
    """Copy one regular member or compare authored bytes after a build."""
    assert_no_links(target)
    if not extract and (
        target.name.casefold() == "pkg-info"
        or any(part.casefold().endswith(".egg-info") for part in target.parts)
    ):
        return

    if extract:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            shutil.copyfileobj(stream, output)
        target.chmod(0o700 if mode & 0o111 else 0o600)
    else:
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        if digest.hexdigest() != _sha256_file(target):
            raise InstallationError(
                "Materialized source input differs from its verified archive."
            )


def materialize_project_snapshot(
    archive: Path,
    destination: Path,
    source: ProjectSnapshot,
) -> None:
    """Verify an immutable project ZIP before materializing its original tree.

    The archive and selected lock are the integrity authority; build products
    subsequently created in the source tree are not compared with the archive.

    :param archive: Retained project ZIP whose bytes match the saved snapshot.
    :param destination: Private, empty final slot source directory.
    :param source: Validated immutable snapshot declaration.
    """
    assert_no_links(archive)
    if _sha256_file(archive) != source.digest:
        raise InstallationError("Project snapshot SHA-256 does not match.")
    relative = (
        PurePosixPath(".")
        if source.project_path == "."
        else relative_destination(source.project_path)
    )
    try:
        with ZipFile(archive) as package:
            members = package.infolist()
            paths, _ = _archive_paths(
                [(member.orig_filename, member.is_dir()) for member in members],
                strip_wrapper=False,
            )
            if any(
                stat.S_IFMT(member.external_attr >> 16)
                not in {0, stat.S_IFREG, stat.S_IFDIR}
                for member in members
            ):
                raise InstallationError(
                    "Project snapshot contains a link or special member."
                )
            files = {
                path.as_posix(): member
                for path, member in zip(paths, members, strict=True)
                if not member.is_dir()
            }
            metadata = (relative / "pyproject.toml").as_posix()
            if metadata not in files:
                raise InstallationError(
                    "Project snapshot has no selected pyproject.toml."
                )
            lock = next(
                (
                    files[(parent / "uv.lock").as_posix()]
                    for parent in (relative, *relative.parents)
                    if (parent / "uv.lock").as_posix() in files
                ),
                None,
            )
            if lock is None:
                raise InstallationError("Project snapshot has no uv.lock.")
            with package.open(lock) as stream:
                lock_digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    lock_digest.update(chunk)
                digest = lock_digest.hexdigest()
            if digest != source.lock_digest:
                raise InstallationError(
                    "Project snapshot lock SHA-256 differs."
                )
    except (OSError, ValueError, BadZipFile) as error:
        raise InstallationError(f"Invalid project snapshot: {error}") from error
    _assert_private_staging(destination)
    if any(destination.iterdir()):
        raise InstallationError(
            "Project materialization directory is not empty."
        )
    _archive_inputs(archive, destination, extract=True, strip_wrapper=False)
    if _sha256_file(archive) != source.digest:
        raise InstallationError(
            "Project snapshot changed during materialization."
        )
