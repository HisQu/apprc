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


def download_release_setup(
    source: GitHubReleaseSource,
    *,
    app_id: str,
    target: NativeTarget,
    directory: Path,
    environment: Mapping[str, str],
    release_tag: str | None = None,
) -> tuple[Path, str]:
    """Verify the setup from the exact tag or the latest stable release.

    :param release_tag: Exact published tag, which may identify a prerelease.
    :return: Downloaded setup path and its verified SHA-256 digest.
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
    try:
        if source.public:
            release_path = (
                f"tags/{quote(release_tag, safe='')}"
                if release_tag is not None
                else "latest"
            )
            release_url = f"https://api.github.com/repos/{repository}/releases/{release_path}"
            with urlopen(
                Request(release_url, headers=headers), timeout=60
            ) as response:
                release = json.load(response)
            tag_key, draft_key, preview_key = "tag_name", "draft", "prerelease"
        else:
            gh = shutil.which("gh", path=environment.get("PATH"))
            if gh is None:
                raise ValueError(
                    "Install GitHub CLI and run `gh auth login` to update "
                    f"from {selection}."
                )
            result = subprocess.run(
                [
                    gh,
                    "release",
                    "view",
                    "--repo",
                    f"github.com/{repository}",
                    "--json",
                    "tagName,isDraft,isPrerelease",
                    *(["--", release_tag] if release_tag is not None else []),
                ],
                env=dict(environment),
                capture_output=True,
                check=True,
                timeout=60,
            )
            release = json.loads(result.stdout)
            tag_key, draft_key, preview_key = (
                "tagName",
                "isDraft",
                "isPrerelease",
            )
        if (
            not isinstance(release, dict)
            or not isinstance(tag := release.get(tag_key), str)
            or not tag.strip()
            or tag in {".", ".."}
            or release.get(draft_key) is not False
            or not isinstance(prerelease := release.get(preview_key), bool)
            or (prerelease if release_tag is None else tag != release_tag)
        ):
            required = (
                "published stable" if release_tag is None else "published"
            )
            raise ValueError(
                f"GitHub did not return a {required} release for {selection}."
            )
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
        guidance = (
            " Check `gh auth status` and access to the release."
            if not source.public
            else ""
        )
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
    return setup, digest
