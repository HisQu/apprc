"""Managed presentation assets stored under installation ownership."""

from __future__ import annotations

import hashlib
import logging
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

import apprc.utils as ut
from apprc.definition.installation import (
    EditableCheckout,
    InstallationInspection,
    InstallationRecord,
    OwnedOutput,
    RuntimeSlot,
)
from apprc.distribution.metadata import _icon_paths
from apprc.distribution.runtime._install_progress import warn
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.installation.operations import record_owned_outputs


LOG = logging.getLogger(__name__)


def _read_icon(
    directory: Path, runtime: RuntimeSlot | EditableCheckout, platform: str
) -> tuple[PurePosixPath, bytes] | None:
    if isinstance(runtime, EditableCheckout):
        metadata = runtime.project / "pyproject.toml"
        assert_no_links(metadata)
        with metadata.open("rb") as stream:
            relative = _icon_paths(tomllib.load(stream)).get(platform)
        if relative is None:
            return None
        asset = runtime.project.joinpath(*relative.parts)
        assert_no_links(asset)
        if not asset.is_file():
            raise ValueError("Declared checkout icon is not a regular file.")
        return relative, asset.read_bytes()

    source = PurePosixPath(runtime.source.project_path)
    archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    assert_no_links(archive)
    with archive.open("rb") as stream:
        if (
            hashlib.file_digest(stream, "sha256").hexdigest()
            != runtime.source.digest
        ):
            raise ValueError("Retained icon source archive was modified.")
        stream.seek(0)
        with zipfile.ZipFile(stream) as snapshot:
            document = tomllib.loads(
                snapshot.read((source / "pyproject.toml").as_posix()).decode(
                    "utf-8"
                )
            )
            relative = _icon_paths(document).get(platform)
            if relative is None:
                return None
            return relative, snapshot.read((source / relative).as_posix())


def ready_icon(
    inspection: InstallationInspection, *, publish: bool = False
) -> tuple[InstallationInspection, Path | None, bool]:
    """Resolve the active product's owned icon under the lifecycle lock.

    Artwork comes from the managed snapshot or the verified editable checkout.
    Publication records the exact digest first so failures can be retried.
    The final value distinguishes a resolved icon or omission from a failure.
    """
    record = inspection.require_usable()
    if (
        record is None
        or inspection.revision is None
        or record.active_runtime is None
        or sys.platform not in {"win32", "linux"}
    ):
        return inspection, None, True

    runtime = record.active_runtime
    directory = inspection.directory
    platform = "windows" if sys.platform == "win32" else "linux"
    try:
        artwork = _read_icon(directory, runtime, platform)
        if artwork is None:
            return inspection, None, True
        relative, content = artwork
        digest = hashlib.sha256(content).hexdigest()
        output = OwnedOutput(
            "support", f"icon-{digest}{relative.suffix.lower()}", digest
        )
        destination = directory / output.path
        assert_no_links(destination)
        if destination.exists():
            if (
                output not in record.owned_outputs
                or not destination.is_file()
                or ut.sha256_file(destination) != digest
            ):
                raise ValueError(
                    "Icon conflicts with an unowned or modified support file."
                )
            return inspection, destination, True
        if not publish:
            return inspection, None, False
        if output not in record.owned_outputs:
            inspection = record_owned_outputs(
                directory,
                app_id=record.identity.app_id,
                expected_revision=inspection.revision,
                generation_id=record.generation_id,
                owned_outputs=(*record.owned_outputs, output),
            )
        write_bytes_atomic(destination, content)
        return inspection, destination, True
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        warn(LOG, "Application icon was not installed", error)
        return inspection, None, False


def windows_icon_location(icon: Path) -> str:
    """Format a Windows Installed apps icon location."""
    return f'"{icon}",0'


def registered_icon(
    directory: Path, record: InstallationRecord
) -> bytes | None:
    """Read the icon only if both the registration and file are saved outputs."""
    location = next(
        (
            dict(item.values).get("DisplayIcon")
            for item in record.owned_outputs
            if item.kind == "hkcu"
        ),
        None,
    )
    if location is None:
        return None
    for item in record.owned_outputs:
        if (
            item.kind != "support"
            or not item.digest
            or item.path != f"icon-{item.digest}.ico"
        ):
            continue
        path = directory / item.path
        if windows_icon_location(path) == location:
            assert_no_links(path)
            if path.is_file():
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() == item.digest:
                    return content
            return None
    return None
