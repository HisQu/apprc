"""Verified ephemeral wheel-bundle preparation for managed installation."""

from __future__ import annotations

import json
import re
import shutil
import urllib.parse
from email.parser import BytesParser
from pathlib import Path
from typing import NoReturn
from zipfile import BadZipFile, ZipFile

from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import parse_tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from apprc.definition.installation import InstallationError, InstallationSource
from apprc.distribution.models import (
    BundledWheel,
    PreparedWheelBundle,
    relative_destination,
)
from apprc.distribution.runtime.acquisition import (
    _assert_private_staging,
    _sha256_file,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import _path_permissions_are_private


def _fail(message: str) -> NoReturn:
    raise InstallationError(message)


def _validate_entry(entry: BundledWheel) -> tuple[str, Version, str | None]:
    """Validate portable inventory claims without touching their wheel paths."""
    required_strings = (entry.name, entry.version, entry.filename, entry.digest)
    optional_strings = (
        entry.marker,
        entry.repository,
        entry.commit,
        entry.subdirectory,
        entry.original_requirement,
    )
    if any(not isinstance(value, str) for value in required_strings) or any(
        value is not None and not isinstance(value, str)
        for value in optional_strings
    ):
        _fail("Invalid wheel bundle inventory fields.")
    try:
        normalized = canonicalize_name(entry.name)
        relative = relative_destination(entry.filename)
        version = Version(entry.version)
        filename_name, filename_version, _, _ = parse_wheel_filename(
            entry.filename
        )
        marker = (
            str(Requirement(f"x; {entry.marker}").marker)
            if entry.marker is not None
            else None
        )
    except (InvalidRequirement, TypeError, ValueError) as error:
        raise InstallationError("Invalid wheel bundle identity.") from error
    if (
        not normalized
        or len(relative.parts) != 1
        or str(relative) != entry.filename
        or filename_name != normalized
        or filename_version != version
        or re.fullmatch(r"[0-9a-f]{64}", entry.digest) is None
    ):
        _fail("Invalid or unsafe wheel bundle identity.")
    provenance = (
        entry.repository,
        entry.commit,
        entry.subdirectory,
        entry.original_requirement,
    )
    if any(value is not None for value in provenance):
        _validate_provenance(entry, normalized)
    return normalized, version, marker


def _validate_entries(entries: tuple[BundledWheel, ...]) -> None:
    """Reject ambiguous inventory identities before any wheel-path access."""
    if not isinstance(entries, tuple) or not entries:
        _fail("Prepared wheel bundle inventory must be a nonempty tuple.")
    identities: set[tuple[str, Version, str | None]] = set()
    filenames: set[str] = set()
    for entry in entries:
        if not isinstance(entry, BundledWheel):
            _fail("Prepared wheel bundle has an invalid inventory row.")
        normalized, version, marker = _validate_entry(entry)
        identity = (normalized, version, marker)
        if identity in identities or entry.filename in filenames:
            _fail("Duplicate or ambiguous wheel bundle identity.")
        identities.add(identity)
        filenames.add(entry.filename)


def _override_line(directory: Path, entry: BundledWheel) -> str:
    marker = f" ; {entry.marker}" if entry.marker else ""
    return (
        f"{entry.name} @ {(directory / 'wheels' / entry.filename).as_uri()}"
        f"{marker}\n"
    )


def _read_inventory(payload: Path) -> tuple[BundledWheel, ...]:
    inventory = payload / "inventory.json"
    assert_no_links(inventory)
    try:
        document: object = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InstallationError("Invalid wheel bundle inventory.") from error
    if not isinstance(document, list) or not document:
        _fail("Invalid wheel bundle inventory.")
    fields = set(BundledWheel.__dataclass_fields__)
    required = {"name", "version", "filename", "digest"}
    entries: list[BundledWheel] = []
    for item in document:
        if (
            not isinstance(item, dict)
            or set(item) - fields
            or not required <= set(item)
        ):
            _fail("Invalid wheel bundle inventory entry.")
        entries.append(BundledWheel(**item))
    result = tuple(entries)
    _validate_entries(result)
    return result


def _validate_provenance(entry: BundledWheel, normalized: str) -> None:
    if (
        not entry.repository
        or any(character in entry.repository for character in "?#@")
        or not re.fullmatch(r"[0-9a-f]{40}", entry.commit or "")
    ):
        _fail("Wheel repository provenance must name an immutable commit.")
    try:
        requirement = Requirement(entry.original_requirement or "")
    except InvalidRequirement as error:
        raise InstallationError(
            "Invalid immutable wheel requirement."
        ) from error
    address = urllib.parse.urlsplit(requirement.url or "")
    if (
        canonicalize_name(requirement.name) != normalized
        or not requirement.url
        or address.scheme not in {"git+https", "git+ssh"}
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment.partition("=")[0] not in {"", "subdirectory"}
        or not address.hostname
    ):
        _fail(
            "Wheel repository provenance differs from its immutable package identity."
        )
    repository_path, separator, revision = address.path.rpartition("@")
    if not separator or not repository_path or revision != entry.commit:
        _fail("Wheel original requirement does not pin its repository commit.")
    original_repository = address._replace(
        scheme=address.scheme.removeprefix("git+"),
        path=address.path.rsplit("@", 1)[0],
        fragment="",
    ).geturl()
    if original_repository != entry.repository:
        _fail(
            "Wheel original requirement does not match its repository identity."
        )
    if address.fragment.startswith("subdirectory="):
        selected = urllib.parse.unquote(address.fragment.partition("=")[2])
        try:
            safe = relative_destination(selected)
        except ValueError as error:
            raise InstallationError(
                "Wheel repository subdirectory is unsafe."
            ) from error
        if str(safe) != selected or selected != entry.subdirectory:
            _fail(
                "Wheel repository subdirectory differs from immutable provenance."
            )
    elif entry.subdirectory is not None:
        _fail(
            "Wheel repository subdirectory differs from immutable provenance."
        )


def _validate_wheel(path: Path, entry: BundledWheel) -> None:
    assert_no_links(path)
    if not path.is_file() or _sha256_file(path) != entry.digest:
        _fail("Bundle wheel digest mismatch.")
    try:
        name, version, _, tags = parse_wheel_filename(entry.filename)
        if name != canonicalize_name(entry.name) or version != Version(
            entry.version
        ):
            _fail("Wheel filename differs from inventory identity.")
        with ZipFile(path) as archive:
            metadata_paths = [
                item
                for item in archive.namelist()
                if item.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                _fail("Wheel has ambiguous metadata.")
            metadata_path = metadata_paths[0]
            metadata = BytesParser().parsebytes(archive.read(metadata_path))
            wheel_metadata = BytesParser().parsebytes(
                archive.read(metadata_path.removesuffix("METADATA") + "WHEEL")
            )
        if (
            canonicalize_name(metadata.get("Name", "")) != name
            or Version(metadata.get("Version", "")) != version
        ):
            _fail("Wheel metadata differs from filename identity.")
        declared = set().union(
            *(parse_tag(value) for value in wheel_metadata.get_all("Tag", []))
        )
        if declared != tags:
            _fail("Wheel metadata tags differ from filename tags.")
    except (BadZipFile, OSError, InvalidVersion, ValueError, KeyError) as error:
        if isinstance(error, InstallationError):
            raise
        raise InstallationError("Invalid wheel archive or metadata.") from error


def _validate_graph(
    source: InstallationSource, entries: tuple[BundledWheel, ...]
) -> None:
    """Match bundled wheels to exact trusted pins without resolving the graph."""
    requirements: list[Requirement] = []
    for value in source.runtime_requirements:
        try:
            requirements.append(Requirement(value))
        except InvalidRequirement as error:
            raise InstallationError(
                "Invalid bundle runtime requirement."
            ) from error
    if not requirements:
        _fail("Wheel bundle requires an immutable complete runtime graph.")
    for entry in entries:
        name = canonicalize_name(entry.name)
        version = Version(entry.version)
        marker = (
            Requirement(f"x; {entry.marker}").marker
            if entry.marker is not None
            else None
        )
        if not any(
            canonicalize_name(requirement.name) == name
            and requirement.url is None
            and str(requirement.specifier) == f"=={version}"
            and requirement.marker == marker
            for requirement in requirements
        ):
            _fail(
                "Bundle wheel does not match an exact pin in the runtime graph."
            )


def _root_entry(
    source: InstallationSource,
    distribution: str,
    entries: tuple[BundledWheel, ...],
) -> BundledWheel:
    root_name = canonicalize_name(distribution)
    roots = [
        entry for entry in entries if canonicalize_name(entry.name) == root_name
    ]
    if len(roots) != 1:
        _fail("Bundle must contain exactly one root distribution wheel.")
    root = roots[0]
    if (
        source.kind != "wheel"
        or source.digest != root.digest
        or source.version != root.version
    ):
        _fail("Bundle root wheel differs from selected source identity.")
    address = urllib.parse.urlsplit(source.requirement)
    encoded_path = address.path if address.scheme else source.requirement
    basename = Path(urllib.parse.unquote(encoded_path)).name
    if basename != root.filename:
        _fail("Bundle root wheel filename differs from selected source.")
    return root


def _validate_bundle(
    bundle: PreparedWheelBundle,
    *,
    source: InstallationSource,
    distribution: str,
) -> None:
    if not isinstance(bundle.wheels, tuple):
        _fail("Prepared wheel bundle inventory must be an immutable tuple.")
    _validate_entries(bundle.wheels)
    root = _root_entry(source, distribution, bundle.wheels)
    _validate_graph(source, bundle.wheels)
    directory = bundle.directory
    staging = directory.parent
    if (
        not directory.is_absolute()
        or directory.name != "wheel-bundle"
        or not directory.is_dir()
    ):
        _fail("Prepared wheel bundle has invalid private staging.")
    assert_no_links(staging)
    assert_no_links(directory)
    if not _path_permissions_are_private(
        staging
    ) or not _path_permissions_are_private(directory):
        _fail("Prepared wheel bundle directory must be private.")
    for entry in bundle.wheels:
        _validate_wheel(directory / "wheels" / entry.filename, entry)
    for path in (bundle.override_file, bundle.runtime_requirements_file):
        assert_no_links(path)
        if not path.is_file():
            _fail("Prepared wheel bundle inputs are missing.")
    root_name = canonicalize_name(root.name)
    expected_overrides = "".join(
        _override_line(directory, entry)
        for entry in bundle.wheels
        if canonicalize_name(entry.name) != root_name
    )
    if bundle.override_file.read_text(encoding="utf-8") != expected_overrides:
        _fail("Prepared wheel overrides differ from verified bundle wheels.")
    expected_requirements = "".join(
        value + "\n" for value in source.runtime_requirements
    )
    if (
        bundle.runtime_requirements_file.read_text(encoding="utf-8")
        != expected_requirements
    ):
        _fail("Prepared wheel requirements differ from selected source graph.")


def prepare_wheel_bundle(
    payload_directory: Path,
    staging: Path,
    *,
    source: InstallationSource,
    distribution: str,
) -> PreparedWheelBundle:
    """Copy and verify portable wheel payloads into private managed-install inputs.

    Filename and wheel metadata tags must agree; uv evaluates compatibility with
    the eventual application interpreter.

    :param payload_directory: Directory containing inventory and exported graph.
    :param staging: Existing or creatable private operation staging directory.
    :param source: Trusted content-addressed root wheel identity and graph.
    :param distribution: Root distribution name whose wheel is supplied separately.
    :return: Revalidatable ephemeral backend input bundle.
    """

    try:
        _assert_private_staging(staging)
        assert_no_links(payload_directory)
        entries = _read_inventory(payload_directory)
        _root_entry(source, distribution, entries)
        _validate_graph(source, entries)
        runtime_path = payload_directory / "runtime-requirements.txt"
        assert_no_links(runtime_path)
        runtime_text = runtime_path.read_text(encoding="utf-8")
        if runtime_text != "".join(
            value + "\n" for value in source.runtime_requirements
        ):
            _fail(
                "Bundle runtime requirements differ from selected source graph."
            )
        bundle_directory = staging / "wheel-bundle"
        bundle_directory.mkdir(mode=0o700)
        wheels_directory = bundle_directory / "wheels"
        wheels_directory.mkdir(mode=0o700)
        for entry in entries:
            original = payload_directory / entry.filename
            _validate_wheel(original, entry)
            target = wheels_directory / entry.filename
            with (
                original.open("rb") as input_stream,
                target.open("xb") as output,
            ):
                shutil.copyfileobj(input_stream, output)
            target.chmod(0o600)
        bundle = PreparedWheelBundle(bundle_directory, entries)
        root_name = canonicalize_name(distribution)
        bundle.override_file.write_text(
            "".join(
                _override_line(bundle_directory, entry)
                for entry in entries
                if canonicalize_name(entry.name) != root_name
            ),
            encoding="utf-8",
        )
        bundle.runtime_requirements_file.write_text(
            runtime_text, encoding="utf-8"
        )
        _validate_bundle(bundle, source=source, distribution=distribution)
        return bundle
    except InstallationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise InstallationError("Invalid wheel bundle payload.") from error


def validate_prepared_bundle(
    bundle: PreparedWheelBundle,
    *,
    source: InstallationSource,
    distribution: str,
) -> None:
    """Revalidate private wheel bytes and generated backend files before mutation.

    :param bundle: Previously prepared ephemeral bundle.
    :param source: Immutable planned source identity and runtime graph.
    :param distribution: Root distribution name omitted from wheel overrides.
    :return: None after all staged inputs are proven unchanged.
    """
    try:
        _validate_bundle(bundle, source=source, distribution=distribution)
    except InstallationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise InstallationError("Prepared wheel bundle is invalid.") from error
