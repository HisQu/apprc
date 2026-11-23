"""Read the verified product embedded in a native setup executable."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from pathlib import Path

from apprc.definition.installation import InstallationError
from apprc.distribution.models import (
    NativeBinding,
    _PREVIEW_ALIAS_MEMBER,
    _PREVIEW_ALIAS_POLICY,
    preview_alias_name,
    read_native_bindings,
    read_preview_default,
)


def read_products(
    executable: Path,
    expected_size: object,
    expected_digest: object,
    *,
    include_project: bool = False,
) -> tuple[NativeBinding, NativeBinding | None, bytes | None, bool, bool]:
    """Verify the appended archive and optionally load its project snapshot."""
    if (
        type(expected_size) is not int
        or expected_size <= 0
        or not isinstance(expected_digest, str)
        or len(expected_digest) != 64
    ):
        raise RuntimeError(
            "Native manager archive verification metadata is unavailable."
        )
    size = executable.stat().st_size
    start = size - expected_size
    if start < 0:
        raise RuntimeError("Native manager archive is truncated.")
    digest = hashlib.sha256()
    with executable.open("rb") as stream:
        stream.seek(start)
        for chunk in iter(lambda: stream.read(131072), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise RuntimeError("Native manager archive changed after loading.")
    with zipfile.ZipFile(executable) as archive:
        binding, preview = read_native_bindings(archive)
        preview_default = read_preview_default(archive)
        aliases = [
            item
            for item in archive.infolist()
            if item.filename == _PREVIEW_ALIAS_MEMBER
        ]
        if aliases and (
            len(aliases) != 1
            or preview is None
            or preview_alias_name(
                preview.command_name, binding.identity.commands
            )
            is None
            or aliases[0].file_size != len(_PREVIEW_ALIAS_POLICY)
            or archive.read(aliases[0]) != _PREVIEW_ALIAS_POLICY
        ):
            raise ValueError(
                "Native setup has an invalid preview alias policy."
            )
        project = archive.read("project.zip") if include_project else None
    if (
        project is not None
        and hashlib.sha256(project).hexdigest() != binding.source.digest
    ):
        raise RuntimeError(
            "Embedded project snapshot differs from its binding."
        )
    return binding, preview, project, preview_default, bool(aliases)


def check_other_product_paths(
    paths: tuple[Path, ...],
    other_app_id: str,
    environment: Mapping[str, str],
    *,
    reserve_native_paths: bool = False,
) -> None:
    """Protect the other identity's captured paths and published files."""
    from apprc.distribution.runtime._uninstall_controller import (
        check_protected_removal_paths,
    )
    from apprc.user_files.installation.discovery import (
        inspect_installation,
        installation_directory,
        native_user_directories,
    )
    from apprc.user_files.installation.planning import resource_roots

    directory = installation_directory(other_app_id, environment=environment)
    inspection = inspect_installation(directory, app_id=other_app_id)
    if inspection.status == "invalid":
        raise InstallationError(
            f"Cannot verify separation from {other_app_id}. Inspect its installation first."
        )
    protected = [directory]
    if reserve_native_paths:
        protected.extend(
            native_user_directories(other_app_id, environment=environment)
        )
    record = inspection.record
    if record is not None:
        protected.extend(path for _, path in resource_roots(record.placement))
        protected.extend(
            Path(output.path)
            for output in record.owned_outputs
            if output.kind in {"command", "shortcut"}
        )
        operation = record.operation
        if operation is not None:
            protected.extend(
                path for _, path in resource_roots(operation.placement)
            )
            if operation.intended is not None:
                protected.extend(
                    path
                    for _, path in resource_roots(operation.intended.placement)
                )
            protected.extend(output.path for output in operation.publication)
    check_protected_removal_paths(paths, tuple(protected))
