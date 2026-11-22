"""Acquire and verify native setup assets shared by authoring and updating."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from apprc.distribution.models import (
    GitHubReleaseSource,
    NativeBinding,
    read_native_bindings,
)
from apprc.distribution.native import NativeTarget, _artifact_info
from apprc.user_files.app_home.locations import assert_no_links


if TYPE_CHECKING:
    from packaging.version import Version


def _read_native_checksums(path: Path, *, app_id: str) -> dict[str, str]:
    """Parse a native manifest independently of local target completeness."""
    assert_no_links(path)
    result: dict[str, str] = {}
    lines = (
        path.read_text(encoding="ascii").splitlines() if path.exists() else []
    )
    if path.exists() and not lines:
        raise ValueError(
            "Existing SHA256SUMS is empty; refusing output replacement."
        )
    allowed = {
        f"{app_id}-setup-linux-x86_64",
        f"{app_id}-setup-windows-x86_64.exe",
    }
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None or match.group(2) in result:
            raise ValueError(
                "Existing SHA256SUMS is malformed; refusing output replacement."
            )
        digest, name = match.groups()
        if name not in allowed:
            raise ValueError("Existing SHA256SUMS contains an unknown output.")
        result[name] = digest
    return result


def _inspect_native_products(
    path: Path, *, app_id: str, target: NativeTarget
) -> tuple[NativeBinding, NativeBinding | None]:
    """Inspect a setup's executable and embedded project without executing it.

    :param path: Native setup executable, including its appended SDK archive.
    :param app_id: Expected application identity.
    :param target: Expected executable format and architecture.
    :return: Decoded bindings after embedded project integrity checks.
    """
    assert_no_links(path)
    _artifact_info(path, target)
    try:
        with ZipFile(path) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("Native archive has duplicate entries.")
            binding, preview = read_native_bindings(archive)
            project = archive.read("project.zip")
        if binding.identity.app_id != app_id:
            raise ValueError("Native artifact belongs to another application.")
        if hashlib.sha256(project).hexdigest() != binding.source.digest:
            raise ValueError("Native project archive SHA-256 differs.")
        with ZipFile(io.BytesIO(project)) as snapshot:
            if len(snapshot.namelist()) != len(set(snapshot.namelist())):
                raise ValueError("Project archive has duplicate entries.")
            relative = PurePosixPath(binding.source.project_path)
            metadata = tomllib.loads(
                snapshot.read(str(relative / "pyproject.toml")).decode("utf-8")
            )
            lock = next(
                (
                    str(parent / "uv.lock")
                    for parent in (relative, *relative.parents)
                    if str(parent / "uv.lock") in snapshot.namelist()
                ),
                None,
            )
            if (
                lock is None
                or hashlib.sha256(snapshot.read(lock)).hexdigest()
                != binding.source.lock_digest
            ):
                raise ValueError("Native project lock SHA-256 differs.")
            declaration = metadata.get("project", {})
            if declaration.get("version") != binding.version:
                raise ValueError("Native binding and project versions differ.")
            project_name = declaration.get("name", "")
            if (
                not isinstance(project_name, str)
                or re.sub(r"[-_.]+", "-", project_name).lower()
                != binding.identity.distribution
            ):
                raise ValueError(
                    "Native binding and project distribution differ."
                )
            for product in (binding, preview):
                if product is not None and not set(
                    product.identity.commands
                ).issubset(declaration.get("scripts", {})):
                    raise ValueError(
                        "Native command is absent from the project."
                    )
        return binding, preview
    except (BadZipFile, KeyError, UnicodeError) as error:
        raise ValueError(f"Invalid native artifact {path}: {error}") from error


def _inspect_native_setup(
    path: Path, *, app_id: str, target: NativeTarget
) -> NativeBinding:
    binding, _ = _inspect_native_products(path, app_id=app_id, target=target)
    return binding


class DownloadedReleaseSetup(NamedTuple):
    """A verified release setup and the selection used to find it."""

    path: Path
    digest: str
    tag: str
    version: Version | None


def _lookup_release_tag(
    repository: str,
    tag: str | None,
    gh: str | None,
    environment: Mapping[str, str],
    headers: Mapping[str, str],
) -> str | None:
    """Read and validate release metadata, with None reserved for a missing tag."""
    suffix = f"tags/{quote(tag, safe='')}" if tag is not None else "latest"
    endpoint = f"repos/{repository}/releases/{suffix}"
    selection = (
        f"{repository} at tag {tag!r}" if tag is not None else repository
    )
    tag_key, draft_key, prerelease_key = "tag_name", "draft", "prerelease"
    guidance = (
        " Check `gh auth status` and access to the release." if gh else ""
    )
    try:
        if gh is None:
            try:
                with urlopen(
                    Request(
                        f"https://api.github.com/{endpoint}",
                        headers=dict(headers),
                    ),
                    timeout=60,
                ) as response:
                    release = json.load(response)
            except HTTPError as error:
                if tag is not None and error.code == 404:
                    error.close()
                    return None
                raise
        elif tag is not None:
            result = subprocess.run(
                [gh, "api", "--hostname", "github.com", "--include", endpoint],
                env=dict(environment),
                capture_output=True,
                check=False,
                timeout=60,
            )
            head, separator, body = result.stdout.replace(
                b"\r\n", b"\n"
            ).partition(b"\n\n")
            status = re.match(
                rb"HTTP/[0-9.]+ ([0-9]{3})(?: |$)", head.split(b"\n", 1)[0]
            )
            if separator and status and status[1] == b"404":
                return None
            if (
                result.returncode
                or not separator
                or not status
                or status[1] != b"200"
            ):
                raise ValueError(
                    "GitHub CLI did not return a successful release response."
                )
            release = json.loads(body)
        else:
            result = subprocess.run(
                [
                    gh,
                    "release",
                    "view",
                    "--repo",
                    f"github.com/{repository}",
                    "--json",
                    "tagName,isDraft,isPrerelease",
                ],
                env=dict(environment),
                capture_output=True,
                check=True,
                timeout=60,
            )
            release = json.loads(result.stdout)
            tag_key, draft_key, prerelease_key = (
                "tagName",
                "isDraft",
                "isPrerelease",
            )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError(
            f"Could not look up the release for {selection}.{guidance}"
        ) from error
    if (
        not isinstance(release, dict)
        or not isinstance(published_tag := release.get(tag_key), str)
        or not published_tag.strip()
        or published_tag in {".", ".."}
        or release.get(draft_key) is not False
        or not isinstance(prerelease := release.get(prerelease_key), bool)
        or (prerelease if tag is None else published_tag != tag)
    ):
        required = "published stable" if tag is None else "published"
        raise ValueError(
            f"GitHub did not return a {required} release for {selection}.{guidance}"
        )
    return published_tag


def _version_tags(version: Version, *, windows: bool) -> tuple[str, ...]:
    """Return bounded exact tag spellings for one package version."""
    spellings = [str(version)]
    if (
        len(version.release) == 3
        and version.pre is not None
        and not version.epoch
        and version.post is None
        and version.dev is None
        and version.local is None
    ):
        phase, number = version.pre
        label = {"a": "alpha", "b": "beta", "rc": "rc"}[phase]
        spellings.append(f"{version.base_version}-{label}.{number}")
    if windows:
        release = version.release
        suffix = str(version)[len(version.base_version) :]
        while len(release) > 1 and release[-1] == 0:
            release = release[:-1]
            spellings.append(".".join(map(str, release)) + suffix)
    return tuple(
        tag for spelling in spellings for tag in (f"v{spelling}", spelling)
    )


def _resolve_release_version(
    repository: str,
    requested: Version,
    gh: str | None,
    environment: Mapping[str, str],
    headers: Mapping[str, str],
) -> tuple[str, Version]:
    """Select a matching tag across the package and Windows interpretations."""
    from packaging.version import Version

    from apprc.distribution.runtime._windows_version import (
        package_version_from_windows_number,
    )

    candidates = [(requested, False)]
    if not requested.epoch and str(requested) == requested.base_version:
        decoded = package_version_from_windows_number(requested.release)
        if decoded is not None:
            candidates.append((Version(decoded), True))
    matches: list[tuple[str, Version]] = []
    for version, windows in candidates:
        for tag in _version_tags(version, windows=windows):
            if (
                _lookup_release_tag(repository, tag, gh, environment, headers)
                is not None
            ):
                matches.append((tag, version))
                break
    if len(matches) > 1:
        tags = " and ".join(repr(tag) for tag, _ in matches)
        raise ValueError(
            f"Version {requested} matches releases {tags} in {repository}. "
            "Select one with --release TAG."
        )
    if not matches:
        guidance = (
            " Check `gh auth status` and access to the release." if gh else ""
        )
        raise ValueError(
            f"No published release matches version {requested} in {repository}.{guidance}"
        )
    return matches[0]


def download_release_setup(
    source: GitHubReleaseSource,
    *,
    app_id: str,
    target: NativeTarget,
    directory: Path,
    environment: Mapping[str, str],
    release_tag: str | None = None,
    requested_version: Version | None = None,
) -> DownloadedReleaseSetup:
    """Verify the setup from the exact tag or the latest stable release.

    :param release_tag: Exact published tag, which may identify a prerelease.
    :param requested_version: Package or Windows version to resolve.
    :return: Downloaded setup, verified digest, and release selection.
    """
    if release_tag is not None and (
        not release_tag.strip() or release_tag in {".", ".."}
    ):
        raise ValueError("--release requires a valid, nonempty release tag.")
    suffix = (
        "windows-x86_64.exe"
        if target == "x86_64-pc-windows-msvc"
        else "linux-x86_64"
    )
    setup = directory / f"{app_id}-setup-{suffix}"
    manifest = directory / "SHA256SUMS"
    headers = {"User-Agent": "AppRC updater"}
    repository = source.repository
    selection = (
        f"{repository} at tag {release_tag!r}"
        if release_tag is not None
        else repository
    )
    gh: str | None = None
    if not source.public:
        gh = shutil.which("gh", path=environment.get("PATH"))
        if gh is None:
            raise ValueError(
                "Install GitHub CLI and run `gh auth login` to update "
                f"from {selection}."
            )
    guidance = (
        " Check `gh auth status` and access to the release." if gh else ""
    )
    version = None
    if requested_version is not None:
        tag, version = _resolve_release_version(
            repository, requested_version, gh, environment, headers
        )
        selection = f"{repository} at tag {tag!r}"
    else:
        tag = _lookup_release_tag(
            repository, release_tag, gh, environment, headers
        )
        if tag is None:
            raise ValueError(
                f"No published release was found for {selection}.{guidance}"
            )
    try:
        if gh is None:
            base = f"https://github.com/{repository}/releases/download/{quote(tag, safe='')}"
            for asset in (setup, manifest):
                with (
                    urlopen(
                        Request(f"{base}/{asset.name}", headers=headers),
                        timeout=120,
                    ) as response,
                    asset.open("xb") as output,
                ):
                    shutil.copyfileobj(response, output)
        else:
            subprocess.run(
                [
                    gh,
                    "release",
                    "download",
                    "--repo",
                    f"github.com/{repository}",
                    "--pattern",
                    setup.name,
                    "--pattern",
                    manifest.name,
                    "--dir",
                    str(directory),
                    "--",
                    tag,
                ],
                env=dict(environment),
                capture_output=True,
                check=True,
                timeout=180,
            )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        UnicodeError,
    ) as error:
        raise ValueError(
            f"Could not download the setup for {selection}. Verify the release "
            f"and its setup assets.{guidance}"
        ) from error

    try:
        if not setup.is_file() or not manifest.is_file():
            raise ValueError(
                f"The release must provide both {setup.name} and {manifest.name}."
            )
        checksums = _read_native_checksums(manifest, app_id=app_id)
        assert_no_links(setup)
        with setup.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except (OSError, ValueError) as error:
        raise ValueError(
            f"Could not verify setup assets for {selection}. {error}"
        ) from error
    if checksums.get(setup.name) != digest:
        raise ValueError(
            f"The downloaded setup for {selection} does not match its release checksum."
        )
    return DownloadedReleaseSetup(setup, digest, tag, version)
