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
    InstallationInspection,
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


def ready_icon(
    inspection: InstallationInspection, *, publish: bool = False
) -> tuple[InstallationInspection, Path | None]:
    """Resolve the active product's owned icon under the lifecycle lock.

    Only managed project snapshots supply artwork. Publication records the exact
    digest before writing the file, so an interrupted write can be retried.
    """
    record = inspection.require_usable()
    if (
        record is None
        or inspection.revision is None
        or not isinstance(record.active_runtime, RuntimeSlot)
        or sys.platform not in {"win32", "linux"}
    ):
        return inspection, None

    runtime = record.active_runtime
    directory = inspection.directory
    source = PurePosixPath(runtime.source.project_path)
    archive = directory / "runtimes" / str(runtime.slot_id) / "project.zip"
    platform = "windows" if sys.platform == "win32" else "linux"
    try:
        assert_no_links(archive)
        with archive.open("rb") as stream, zipfile.ZipFile(stream) as snapshot:
            document = tomllib.loads(
                snapshot.read((source / "pyproject.toml").as_posix()).decode(
                    "utf-8"
                )
            )
            relative = _icon_paths(document).get(platform)
            if relative is None:
                return inspection, None
            stream.seek(0)
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != runtime.source.digest
            ):
                raise ValueError("Retained icon source archive was modified.")
            content = snapshot.read((source / relative).as_posix())
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
            return inspection, destination
        if not publish:
            return inspection, None
        if output not in record.owned_outputs:
            inspection = record_owned_outputs(
                directory,
                app_id=record.identity.app_id,
                expected_revision=inspection.revision,
                generation_id=record.generation_id,
                owned_outputs=(*record.owned_outputs, output),
            )
        write_bytes_atomic(destination, content)
        return inspection, destination
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        warn(LOG, "Application icon was not installed", error)
        return inspection, None
