"""Adapt authenticated installer payloads to ordinary managed wheel sources."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import cast
from zipfile import BadZipFile, ZipFile

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationSource,
)
from apprc.definition.paths import Paths
from apprc.distribution._frontend import RUNTIME_PAYLOAD_FILENAME
from apprc.distribution.models import (
    AppCapabilities,
    DistributionSpec,
    ProjectMetadata,
    relative_destination,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    SourceSelection,
    _archive_inputs,
    _assert_private_staging,
    _validate_source,
    installation_source,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation.codec import _decode, _pairs
from apprc.user_files.installation.discovery import inspect_installation

RETAINED_PAYLOAD = PurePosixPath(RUNTIME_PAYLOAD_FILENAME)


@dataclass(frozen=True, slots=True)
class _PayloadSources:
    """Portable build inputs, authenticated as payload data rather than authority."""

    origin: InstallationSource
    source: InstallationSource
    targets: tuple[str, ...]


def _payload_identity(spec: DistributionSpec) -> dict[str, object]:
    """Use the existing release identity for the inner asset manifest."""
    return {
        "app_id": spec.metadata.identity.app_id,
        "distribution": spec.metadata.identity.distribution,
        "version": spec.release_version or spec.metadata.version,
        "commit": spec.release_commit,
        "payload_format": spec.payload_format,
    }


def _read_owned_payload(
    directory: Path, spec: DistributionSpec
) -> tuple[bytes, InstallationSource]:
    """Read only the exact retained bytes and source owned by saved authority."""
    inspection = inspect_installation(
        directory, app_id=spec.metadata.identity.app_id
    )
    record = inspection.record
    if record is None:
        raise InstallationError(
            "Saved payload requires installation authority."
        )
    if record.operation is not None:
        if (
            record.operation.kind not in {"install", "replace", "repair"}
            or record.operation.intended is None
        ):
            raise InstallationError(
                "Saved payload cannot resume this operation."
            )
        source = record.operation.intended.source
    else:
        snapshot = record.current or record.last_successful
        if snapshot is None:
            raise InstallationError(
                "Saved payload has no recorded application source."
            )
        source = snapshot.source
    claims = {
        item.digest
        for item in record.owned_outputs
        if item.kind == "support" and item.path == str(RETAINED_PAYLOAD)
    }
    path = directory / RETAINED_PAYLOAD
    assert_no_links(path)
    content = path.read_bytes() if len(claims) == 1 and path.is_file() else None
    if content is None or hashlib.sha256(content).hexdigest() not in claims:
        raise InstallationError(
            "Retained installer payload differs from recorded ownership."
        )
    return content, source


def _unpack_payload(
    archive: Path, root: Path, spec: DistributionSpec
) -> _PayloadSources:
    """Reuse source extraction and schema codecs, then verify the exact inner closure."""
    _assert_private_staging(root)
    try:
        with ZipFile(archive) as package:
            names = package.namelist()
            if any(PurePosixPath(name).name != name for name in names):
                raise InstallationError(
                    "Installer payload must contain flat asset names."
                )
        _archive_inputs(archive, root, extract=True)
        sources = cast(
            _PayloadSources,
            _decode(
                json.loads(
                    (root / "sources.json").read_bytes(),
                    object_pairs_hook=_pairs,
                ),
                _PayloadSources,
                "installer-payload.sources",
            ),
        )
        from apprc.distribution.runtime.bundles import _read_inventory

        entries = _read_inventory(root)
        expected = {
            "sources.json",
            "inventory.json",
            "runtime-requirements.txt",
            *(entry.filename for entry in entries),
        }
        if "launch" in names and "x86_64-unknown-linux-gnu" in sources.targets:
            expected.add("launch")
        if set(names) != expected:
            raise InstallationError(
                "Installer payload differs from its exact inventory."
            )
    except (OSError, ValueError, KeyError, BadZipFile) as error:
        raise InstallationError("Installer payload is invalid.") from error
    _validate_source(sources.origin)
    _validate_source(sources.source)
    target = (
        "x86_64-pc-windows-msvc"
        if os.name == "nt"
        else "x86_64-unknown-linux-gnu"
    )
    if (
        (os.name != "nt" and sys.platform != "linux")
        or platform.machine().casefold() not in {"x86_64", "amd64"}
        or target not in sources.targets
    ):
        raise InstallationError(
            "Installer payload targets a different platform."
        )
    if not installation_source(spec).matches_observation(sources.origin):
        raise InstallationError(
            "Installer payload differs from its authored source."
        )
    if (
        sources.source.kind != "wheel"
        or sources.source.version != spec.metadata.version
    ):
        raise InstallationError(
            "Installer payload requires its exact application wheel."
        )
    try:
        name = relative_destination(sources.source.requirement)
    except ValueError as error:
        raise InstallationError(
            "Installer payload wheel filename is invalid."
        ) from error
    if len(name.parts) != 1 or name.suffix != ".whl":
        raise InstallationError(
            "Installer payload wheel must have a portable filename."
        )
    return sources


def prepare_installation_source(
    spec: DistributionSpec,
    selection: SourceSelection,
    staging: Path,
    *,
    repair_from: Path | None = None,
) -> PreparedSource:
    """Prepare ordinary sources or adapt one authenticated bundled release to wheels.

    Fresh installation still acquires and validates the original release package
    before adaptation. Saved repair instead authenticates the retained archive
    through existing output ownership and requires the exact recorded wheel source.
    No temporary paths become installation authority.

    :param spec: Selected authored installer identity and original transport inputs.
    :param selection: Source selected by the existing argument parser.
    :param staging: New private operation staging directory.
    :param repair_from: Explicit installation address for saved bundle recovery.
    :return: Verified normal backend input with optional retained support bytes.
    """
    reference = Path(__file__).with_name(f"{RUNTIME_PAYLOAD_FILENAME}.sha256")
    if repair_from is None and not reference.is_file():
        return selection.prepare(staging)
    if repair_from is not None:
        inspection = inspect_installation(
            repair_from, app_id=spec.metadata.identity.app_id
        )
        record = inspection.record
        if record is None or not any(
            item.kind == "support" and item.path == str(RETAINED_PAYLOAD)
            for item in record.owned_outputs
        ):
            return selection.prepare(staging)
        content, recorded_source = _read_owned_payload(repair_from, spec)
    else:
        assert_no_links(reference)
        archive_path = (
            Path(sys.argv[0]).absolute().with_name(RUNTIME_PAYLOAD_FILENAME)
        )
        assert_no_links(archive_path)
        content = archive_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != reference.read_text(
            encoding="ascii"
        ):
            raise InstallationError(
                "Installer payload differs from its authored SHA-256."
            )
        recorded_source = None
    _assert_private_staging(staging)
    archive = staging / str(RETAINED_PAYLOAD)
    with archive.open("xb") as stream:
        stream.write(content)
    extracted = staging / "payload"
    sources = _unpack_payload(archive, extracted, spec)
    if recorded_source is None:
        if not selection.source.matches_observation(sources.origin):
            raise InstallationError(
                "Selected transport differs from the compiled payload origin."
            )
        selection.prepare(staging / "origin")
    elif recorded_source != sources.source or selection.source not in {
        sources.origin,
        sources.source,
    }:
        raise InstallationError(
            "Saved payload differs from the recorded repair source."
        )
    # > Import optional distribution dependencies only for a real bundle operation.
    from apprc.distribution.runtime.bundles import prepare_wheel_bundle

    prepared = SourceSelection(
        sources.source, package_path=extracted / sources.source.requirement
    ).prepare(staging / "application")
    bundle = prepare_wheel_bundle(
        extracted,
        staging / "application",
        source=sources.source,
        distribution=spec.metadata.identity.distribution,
    )
    support = {RETAINED_PAYLOAD: content}
    launcher = extracted / "launch"
    if os.name != "nt" and launcher.is_file():
        support[PurePosixPath("launch")] = launcher.read_bytes()
    return replace(prepared, bundle=bundle, support_files=support)


def load_installer_spec(*, script: Path | None = None) -> DistributionSpec:
    """Read portable author inputs without importing application configuration.

    The real generated entry address identifies an editable checkout regardless
    of caller CWD. Downloaded and saved entries retain their original remote source
    contract and do not treat their extraction directory as application source.

    :param script: Actual generated entry; defaults to the current script address.
    :return: Authored source, identity and capability declarations.
    """
    try:
        data = json.loads(
            Path(__file__).with_name("bundle.json").read_bytes(),
            object_pairs_hook=_pairs,
        )
        if not isinstance(data, dict):
            raise InstallationError("Installer inputs must be a JSON object.")
        distribution_path = relative_destination(data["distribution_path"])
        entry = (script or Path(sys.argv[0])).resolve()
        project_root = entry.parent
        if entry.name in {"main-installer.py", "main-installer.pyz"}:
            for candidate in entry.parents:
                expected = candidate.joinpath(
                    *distribution_path.parts,
                    "artifacts",
                    "installer",
                    entry.name,
                )
                if expected.resolve() == entry:
                    project_root = candidate
                    break
        identity = InstallationIdentity(
            app_id=data["app_id"],
            distribution=data["distribution"],
            import_package=data["import_package"],
            apprc_reference=data["apprc_reference"],
            commands=tuple(data["commands"]),
        )
        metadata = ProjectMetadata(
            project_root=project_root,
            identity=identity,
            version=data["version"],
            project_path=PurePosixPath(data["project_path"]),
            distribution_path=distribution_path,
            launcher_command=data["launcher_command"],
            python_requirement=data["python_requirement"],
            runtime_python=data["runtime_python"],
        )
        return DistributionSpec(
            metadata=metadata,
            capabilities=AppCapabilities(
                paths=Paths(**data["paths"]),
                user_dotenv=data["user_dotenv"],
                workspaces=data["workspaces"],
                workspace_registry=data["workspace_registry"],
            ),
            source_mode=data["source_mode"],
            payload_format=data["payload_format"],
            repository_url=data["repository_url"],
            release_version=data["release_version"],
            release_commit=data["release_commit"],
            release_asset=data["release_asset"],
            release_digest=data["release_digest"],
            runtime_requirements=tuple(data["runtime_requirements"]),
            runtime_overrides=tuple(data["runtime_overrides"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise InstallationError(
            "Bundled installer declarations are invalid."
        ) from error
