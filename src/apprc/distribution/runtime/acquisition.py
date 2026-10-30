"""Exact distribution source acquisition and immutable runtime constraints."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO
from zipfile import ZipFile, is_zipfile

from apprc.definition.installation import InstallationError, InstallationSource
from apprc.distribution.models import DistributionSpec, relative_destination
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
    windows_acl_is_private,
)


@dataclass(frozen=True, slots=True)
class PreparedSource:
    """A verified local package input and constraints file for one install call."""

    requirement: str
    constraints: Path | None
    source: InstallationSource
    digest: str | None = None
    archive: Path | None = None
    source_root: Path | None = None
    project_directory: Path | None = None


def _assert_private_staging(staging: Path) -> None:
    """Create and validate a private operation-owned staging directory."""
    if not staging.is_absolute():
        raise InstallationError("Source staging directory must be absolute.")
    create_private_directory_if_missing(staging)
    assert_no_links(staging)
    if os.name == "nt":
        if not windows_acl_is_private(staging):
            raise InstallationError(
                "Source staging directory does not have a private Windows ACL."
            )
    elif stat.S_IMODE(staging.stat().st_mode) & 0o077:
        raise InstallationError("Source staging directory must be private.")


def _validate_source(source: InstallationSource) -> None:
    """Validate package identity and every runtime requirement before acquisition."""
    validate_requirement(source.requirement)
    for requirement in (
        *source.runtime_requirements,
        *source.runtime_overrides,
    ):
        validate_requirement(requirement)
    if (
        source.digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", source.digest) is None
    ):
        raise InstallationError("Source digest must be SHA-256.")


def _github_repository_identity(value: str) -> tuple[str, str] | None:
    """Return a normalized owner/repository pair for a public GitHub URL."""
    address = urllib.parse.urlsplit(value)
    path = address.path.rstrip("/")
    parts = path[1:].split("/") if path.startswith("/") else []
    if (
        address.scheme != "https"
        or address.hostname != "github.com"
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
        or len(parts) != 2
    ):
        return None
    repository = parts[1].removesuffix(".git")
    if not parts[0] or not repository:
        return None
    return parts[0].casefold(), repository.casefold()


def _sha256_file(path: Path) -> str:
    """Hash a file without loading its complete contents into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_paths(
    names: Sequence[tuple[str, bool]],
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
        if len(roots) == 1
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


def _archive_inputs(archive: Path, root: Path, *, extract: bool) -> None:
    """Extract or compare original regular inputs, never backend-created files.

    Links and special members are deliberately unsupported: neither tar link
    resolution nor platform-specific ZIP attributes may redirect writes.
    """
    try:
        if is_zipfile(archive):
            with ZipFile(archive) as package:
                members = package.infolist()
                paths, _ = _archive_paths(
                    [(member.filename, member.is_dir()) for member in members]
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
                    [(member.name, member.isdir()) for member in members]
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


def _source_subdirectory(source: InstallationSource) -> str | None:
    """Return the one validated selected subdirectory for immutable main."""
    if source.kind == "release-sdist":
        return None
    if source.kind != "index":
        raise InstallationError(
            "Source is not a materialized immutable archive."
        )
    match = re.fullmatch(
        r"git\+https://github\.com/[^/]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=([^\\\x00\r\n]+))?",
        source.requirement,
    )
    if match is None:
        raise InstallationError(
            "Main source must name one immutable GitHub commit."
        )
    subdirectory = match.group(1)
    if subdirectory is not None:
        try:
            relative_destination(subdirectory)
        except ValueError as error:
            raise InstallationError(
                "Unsafe source project subdirectory."
            ) from error
    return subdirectory


def _materialized_source_paths(
    source: InstallationSource, digest: str, parent: Path
) -> tuple[Path, Path]:
    """Derive the sole content-addressed root and selected project path."""
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise InstallationError("Materialized source digest must be SHA-256.")
    root = parent / f"apprc-source-{digest}"
    subdirectory = _source_subdirectory(source)
    project = (
        root.joinpath(*relative_destination(subdirectory).parts)
        if subdirectory is not None
        else root
    )
    return root, project


def _validate_content_addressed_origin(
    source: InstallationSource, digest: str, actual: Path
) -> Path:
    """Validate an observed origin lexically, including after staging deletion."""
    if (
        not actual.is_absolute()
        or ".." in actual.parts
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise InstallationError("Invalid content-addressed source origin.")
    if source.kind == "wheel":
        if (
            re.fullmatch(
                r"[^-]+-[^-]+-(?:[^-]+-)?[^-]+-[^-]+-[^-]+\.whl",
                actual.name,
            )
            is None
        ):
            raise InstallationError("Invalid content-addressed wheel filename.")
        root = actual.parent
    else:
        subdirectory = _source_subdirectory(source)
        suffix = (
            relative_destination(subdirectory).parts
            if subdirectory is not None
            else ()
        )
        root = actual
        for part in reversed(suffix):
            if root.name != part:
                raise InstallationError(
                    "Content-addressed source has a different selected subdirectory."
                )
            root = root.parent
    if root.name != f"apprc-source-{digest}":
        raise InstallationError("Content-addressed source digest differs.")
    return root


def _selected_project(root: Path, subdirectory: str | None) -> Path:
    """Select exactly the requested repository directory, without guessing."""
    if subdirectory is None:
        project = root
    else:
        try:
            relative = relative_destination(subdirectory)
        except ValueError as error:
            raise InstallationError(
                "Unsafe source project subdirectory."
            ) from error
        project = root.joinpath(*relative.parts)
    assert_no_links(project)
    if not project.is_dir():
        raise InstallationError(
            "Selected source project directory is unavailable or ambiguous."
        )
    markers = ("pyproject.toml", "setup.py", "setup.cfg")
    for marker in markers:
        assert_no_links(project / marker)
    if not any((project / marker).is_file() for marker in markers):
        raise InstallationError(
            "Selected source project directory is unavailable or ambiguous."
        )
    return project


def _materialize_archive(
    source: InstallationSource,
    archive: Path,
    staging: Path,
    digest: str,
) -> PreparedSource:
    """Bind verified source bytes to a private operation-owned project."""
    _assert_private_staging(staging)
    root, expected_project = _materialized_source_paths(source, digest, staging)
    _assert_private_staging(root.parent)
    created = not root.exists()
    if created:
        root.mkdir(mode=0o700)
    elif not root.is_dir():
        raise InstallationError(
            "Content-addressed source path is not a directory."
        )
    try:
        _archive_inputs(archive, root, extract=created)
        project = _selected_project(root, _source_subdirectory(source))
        if project != expected_project:
            raise InstallationError(
                "Selected project differs from its content-addressed source path."
            )
        if _sha256_file(archive) != digest:
            raise InstallationError(
                "Source archive changed during materialization."
            )
    except BaseException:
        if created:
            shutil.rmtree(root)
        raise
    return PreparedSource(
        str(project),
        _write_constraints(source, staging),
        source,
        digest,
        archive,
        root,
        project,
    )


def _main_source_identity(
    source: InstallationSource,
) -> tuple[str, str, str | None] | None:
    """Return repository, full commit and raw project fragment for immutable main."""
    match = re.fullmatch(
        r"git\+https://github\.com/([^/]+)/([^/@]+)@([0-9a-f]{40})(?:#subdirectory=([^\\\x00\r\n]+))?",
        source.requirement,
    )
    if match is None:
        return None
    owner, repository, commit, subdirectory = match.groups()
    return f"https://github.com/{owner}/{repository}", commit, subdirectory


@dataclass(frozen=True, slots=True)
class SourceSelection:
    """Explicit source identity and optional GitHub transport client."""

    source: InstallationSource
    github_client: str | None = None
    package_path: Path | None = None
    subdirectory: str | None = None

    def prepare(self, staging: Path) -> PreparedSource:
        """Acquire selected package bytes and bind them to the source identity.

        :param staging: Private operation-owned staging directory.
        :return: Prepared input retaining the selected immutable identity.
        """
        if self.github_client not in {None, "gh"}:
            raise InstallationError("Unsupported GitHub download client.")
        _validate_source(self.source)
        if self.package_path is not None:
            if (
                not self.package_path.is_absolute()
                or not self.package_path.is_file()
            ):
                raise InstallationError(
                    "Bootstrap package archive is unavailable."
                )
            main_identity = _main_source_identity(self.source)
            if self.source.kind == "index":
                if (
                    main_identity is None
                    or main_identity[2] != self.subdirectory
                ):
                    raise InstallationError(
                        "Bootstrap package does not match its immutable main identity."
                    )
            elif self.source.kind not in {"release-sdist", "wheel"}:
                raise InstallationError(
                    "Bootstrap package archive requires an index or release identity."
                )
            _assert_private_staging(staging)
            assert_no_links(self.package_path)
            real_package = self.package_path.resolve(strict=True)
            parent = real_package.parent
            if os.name == "nt":
                if not windows_acl_is_private(parent):
                    raise InstallationError(
                        "Bootstrap package staging must be private."
                    )
            elif stat.S_IMODE(parent.stat().st_mode) & 0o077:
                raise InstallationError(
                    "Bootstrap package staging must be private."
                )
            if self.source.kind in {"release-sdist", "wheel"}:
                local = replace(self.source, requirement=str(real_package))
                return replace(
                    prepare_source(local, staging),
                    source=self.source,
                )
            digest = _sha256_file(real_package)
            if self.source.digest is not None and digest != self.source.digest:
                raise InstallationError(
                    "Bootstrap package archive differs from its selected digest."
                )
            return _materialize_archive(
                self.source, real_package, staging, digest
            )
        if self.source.kind == "index" and self.source.requirement.startswith(
            "git+https://github.com/"
        ):
            return _prepare_main_archive(self, staging)
        if self.github_client == "gh" and self.source.kind in {
            "release-sdist",
            "wheel",
        }:
            address = urllib.parse.urlsplit(self.source.requirement)
            if address.scheme == "https":
                if address.hostname != "github.com":
                    raise InstallationError(
                        "The gh client only supports GitHub release assets."
                    )
                return _prepare_release_asset(self, staging)
        return prepare_source(self.source, staging)


def _write_constraints(
    source: InstallationSource, staging: Path
) -> Path | None:
    """Write exact runtime constraints for an already selected source.

    :param source: Exact package source carrying its runtime requirements.
    :param staging: Private operation-owned staging directory.
    :return: The constraints file, or ``None`` when no requirements exist.
    """
    if not source.runtime_requirements:
        return None
    target = staging / "runtime-requirements.txt"
    assert_no_links(target)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.writelines(item + "\n" for item in source.runtime_requirements)
    return target


def _prepare_release_asset(
    selection: SourceSelection, staging: Path
) -> PreparedSource:
    """Download a selected release asset through authenticated gh.

    :param selection: Exact release source and explicit GitHub client.
    :param staging: Private operation-owned staging directory.
    :return: Digest-verified local release source retaining remote identity.
    """
    source = selection.source
    _validate_source(source)
    address = urllib.parse.urlsplit(source.requirement)
    path_parts = address.path.split("/")
    if (
        address.scheme != "https"
        or address.hostname != "github.com"
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
        or len(path_parts) != 7
        or path_parts[0] != ""
        or path_parts[3:5] != ["releases", "download"]
        or any(not part for part in path_parts[1:])
    ):
        raise InstallationError(
            "Authenticated release source is not a GitHub asset."
        )
    owner, repository = (urllib.parse.unquote(part) for part in path_parts[1:3])
    repository = repository.removesuffix(".git")
    tag, filename = (urllib.parse.unquote(part) for part in path_parts[5:7])
    if any(
        part in {"", ".", ".."} or "/" in part or "\\" in part
        for part in (owner, repository, tag, filename)
    ):
        raise InstallationError(
            "Authenticated release asset identity is unsafe."
        )
    _assert_private_staging(staging)
    target = staging / filename
    assert_no_links(target)
    if target.exists():
        raise InstallationError(
            "Authenticated release package already exists in staging."
        )
    subprocess.run(
        [
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            f"{owner}/{repository}",
            "--dir",
            str(staging),
            "--pattern",
            filename,
        ],
        check=True,
    )
    local = replace(source, requirement=str(target))
    preparation_staging = (
        staging / "wheel-materialization" if source.kind == "wheel" else staging
    )
    prepared = prepare_source(local, preparation_staging)
    return replace(prepared, source=source)


def _prepare_main_archive(
    selection: SourceSelection, staging: Path
) -> PreparedSource:
    """Acquire one immutable main commit archive before package installation.

    :param selection: Immutable GitHub source and selected client.
    :param staging: Private operation-owned staging directory.
    :return: Local archive input with digest and retained source identity.
    """
    source = selection.source
    match = re.fullmatch(
        r"git\+https://github\.com/([^/]+)/([^/@]+)@([0-9a-f]{40})(?:#subdirectory=([^\\\x00\r\n]+))?",
        source.requirement,
    )
    if match is None:
        raise InstallationError(
            "Main source must name one immutable GitHub commit."
        )
    owner, repository, commit, _ = match.groups()
    repository = repository.removesuffix(".git")
    _assert_private_staging(staging)
    target = staging / "source.tar.gz"
    assert_no_links(target)
    if selection.github_client == "gh":
        with target.open("xb") as output:
            subprocess.run(
                ["gh", "api", f"repos/{owner}/{repository}/tarball/{commit}"],
                check=True,
                stdout=output,
            )
    else:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repository}/tarball/{commit}",
            headers={"User-Agent": "AppRC distribution"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            with target.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
    if not target.is_file() or target.stat().st_size == 0:
        raise InstallationError("GitHub main package archive is unavailable.")
    digest = _sha256_file(target)
    if source.digest is not None and digest != source.digest:
        raise InstallationError(
            "Downloaded main archive differs from its selected digest."
        )
    return _materialize_archive(source, target, staging, digest)


def installation_source(spec: DistributionSpec) -> InstallationSource:
    """Convert one author-selected source identity into exact backend inputs."""
    metadata = spec.metadata
    if spec.source_mode == "checkout":
        project = metadata.project_root.joinpath(*metadata.project_path.parts)
        if not project.is_absolute():
            raise InstallationError("Editable project root must be absolute.")
        return InstallationSource(
            "editable",
            str(project),
            runtime_requirements=spec.runtime_requirements,
            runtime_overrides=spec.runtime_overrides,
        )
    if spec.source_mode == "main":
        repository = spec.repository_url
        if repository is None:
            raise InstallationError(
                "Remote main requires a credential-free HTTPS repository URL."
            )
        address = urllib.parse.urlsplit(repository)
        if (
            address.hostname != "github.com"
            or address.scheme != "https"
            or not address.hostname
            or address.username is not None
            or address.password is not None
            or address.query
            or address.fragment
        ):
            raise InstallationError(
                "Remote main requires a credential-free HTTPS repository URL."
            )
        requirement = f"git+{repository.rstrip('/')}@{spec.release_commit}"
        if str(metadata.project_path) != ".":
            requirement += f"#subdirectory={metadata.project_path}"
        validate_requirement(requirement)
        return InstallationSource(
            "index",
            requirement,
            version=metadata.version,
            runtime_requirements=spec.runtime_requirements,
            runtime_overrides=spec.runtime_overrides,
        )
    if spec.source_mode in {"release", "wheel"}:
        asset = spec.release_asset
        if asset is None:
            raise InstallationError("Release asset identity is missing.")
        parsed = urllib.parse.urlsplit(asset)
        if parsed.scheme == "https":
            requirement = asset
        elif parsed.scheme:
            raise InstallationError(
                "Release assets require HTTPS or an explicit local file."
            )
        else:
            path = Path(asset)
            if path.is_absolute():
                requirement = str(path)
            else:
                relative = relative_destination(asset)
                requirement = str(
                    metadata.project_root.joinpath(*relative.parts)
                )
        kind = "release-sdist" if spec.source_mode == "release" else "wheel"
        return InstallationSource(
            kind,
            requirement,
            version=spec.release_version,
            digest=spec.release_digest,
            runtime_requirements=spec.runtime_requirements,
            runtime_overrides=spec.runtime_overrides,
        )
    if spec.source_mode == "index":
        return InstallationSource(
            "index",
            f"{metadata.identity.distribution}=={metadata.version}",
            version=metadata.version,
            runtime_requirements=spec.runtime_requirements,
            runtime_overrides=spec.runtime_overrides,
        )
    raise InstallationError(
        f"Unsupported distribution source mode: {spec.source_mode}."
    )


def parse_source_arguments(
    spec: DistributionSpec,
    arguments: Sequence[str],
) -> tuple[SourceSelection, tuple[str, ...]]:
    """Consume private transport inputs before application CLI parsing.

    :param spec: Authored source identity and repository metadata.
    :param arguments: Full installer argv after the executable name.
    :return: Selected source/client and untouched application arguments.
    """
    names = {
        "--source-mode": "mode",
        "--source-repository": "repository",
        "--source-commit": "commit",
        "--source-package": "package",
        "--github-client": "client",
    }
    selected: dict[str, str] = {}
    remaining: list[str] = []
    values = tuple(arguments)
    index = 0
    while index < len(values):
        argument = values[index]
        if argument == "--":
            remaining.extend(values[index:])
            break
        field = names.get(argument)
        if field is None:
            remaining.append(argument)
            index += 1
            continue
        if field in selected or index + 1 >= len(values):
            raise InstallationError(
                f"Bootstrap source argument {argument} is duplicated or incomplete."
            )
        selected[field] = values[index + 1]
        index += 2
    client = selected.pop("client", None)
    if client not in {None, "gh"}:
        raise InstallationError("GitHub client must be gh.")
    package_path = Path(selected["package"]) if "package" in selected else None
    transport = {
        key: value for key, value in selected.items() if key not in {"package"}
    }
    if not transport:
        if package_path is not None and spec.source_mode != "release":
            raise InstallationError(
                "A package archive requires a release or immutable main identity."
            )
        return SourceSelection(
            installation_source(spec), client, package_path
        ), tuple(remaining)
    if spec.source_mode not in {"checkout", "main"} or set(transport) != {
        "mode",
        "repository",
        "commit",
    }:
        raise InstallationError(
            "Remote-main bootstrap source arguments must be supplied together."
        )
    if spec.repository_url is None:
        raise InstallationError("Remote-main source repository is missing.")
    configured_repository = _github_repository_identity(spec.repository_url)
    selected_repository = _github_repository_identity(transport["repository"])
    if (
        transport["mode"] != "main"
        or configured_repository is None
        or selected_repository != configured_repository
    ):
        raise InstallationError(
            "Bootstrap source mode or repository differs from this application."
        )
    commit = transport["commit"]
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise InstallationError(
            "Bootstrap main commit must be a full lowercase Git SHA."
        )
    repository = spec.repository_url.rstrip("/")
    address = urllib.parse.urlsplit(repository)
    if (
        address.hostname != "github.com"
        or address.scheme != "https"
        or not address.hostname
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
    ):
        raise InstallationError(
            "Remote-main source requires a credential-free HTTPS repository URL."
        )
    requirement = f"git+{repository}@{commit}"
    subdirectory = str(spec.metadata.project_path)
    if subdirectory != ".":
        requirement += f"#subdirectory={subdirectory}"
    source = InstallationSource(
        "index",
        requirement,
        version=spec.metadata.version,
        runtime_requirements=spec.runtime_requirements,
        runtime_overrides=spec.runtime_overrides,
    )
    validate_requirement(source.requirement)
    if package_path is not None and (
        not package_path.is_absolute() or not package_path.is_file()
    ):
        raise InstallationError(
            "Bootstrap package archive must be an existing absolute file."
        )
    return SourceSelection(
        source,
        client,
        package_path,
        subdirectory if subdirectory != "." else None,
    ), tuple(remaining)


def validate_requirement(value: str) -> None:
    """Reject backend options, line injection and URL-embedded credentials."""
    if (
        not value
        or value != value.strip()
        or value.startswith("-")
        or "\n" in value
        or "\r" in value
    ):
        raise InstallationError(
            "Requirements must be individual PEP 508 values, not backend options."
        )
    match = re.search(r"\s@\s*([A-Za-z][A-Za-z0-9+.-]*://\S+)", value)
    address = (
        match.group(1)
        if match is not None
        else value
        if "://" in value
        else None
    )
    if address is None:
        return
    parsed = urllib.parse.urlsplit(address)
    if parsed.username is not None or parsed.password is not None:
        raise InstallationError(
            "Package source URLs must not persist credentials."
        )
    sensitive = {
        "access_token",
        "api_key",
        "auth",
        "key",
        "password",
        "secret",
        "token",
    }
    if any(
        key.casefold() in sensitive
        for key, _ in urllib.parse.parse_qsl(parsed.query)
    ):
        raise InstallationError(
            "Package source URLs must not persist credential query parameters."
        )


def prepare_source(source: InstallationSource, staging: Path) -> PreparedSource:
    """Verify source identity and materialize exact release requirements privately.

    :param source: Explicit editable, release, wheel, or index acquisition identity.
    :param staging: Private operation-owned staging directory outside package targets.
    :return: Backend inputs that cannot silently float to another release.
    """
    _assert_private_staging(staging)
    _validate_source(source)
    if source.kind == "editable":
        project = Path(source.requirement)
        if (
            not project.is_absolute()
            or not (project / "pyproject.toml").is_file()
        ):
            raise InstallationError(
                "Editable source must be the absolute live project checkout."
            )
        assert_no_links(project)
        assert_no_links(project / "pyproject.toml")
        requirement = str(project)
    elif source.kind in {"release-sdist", "wheel"}:
        if not source.version or (
            source.kind == "release-sdist" and not source.runtime_requirements
        ):
            raise InstallationError(
                "Release assets require exact versions; sdists require runtime constraints."
            )
        if (
            not source.digest
            or re.fullmatch(r"[0-9a-f]{64}", source.digest) is None
        ):
            raise InstallationError(
                "Release assets require an exact SHA-256 digest."
            )
        parsed = urllib.parse.urlsplit(source.requirement)
        if parsed.scheme == "https":
            if parsed.username or parsed.password or not parsed.hostname:
                raise InstallationError(
                    "Package source URL must not contain credentials."
                )
            filename = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
            if (
                not filename
                or filename in {".", ".."}
                or "/" in filename
                or "\\" in filename
            ):
                raise InstallationError("Release asset filename is unsafe.")
            target = staging / (
                filename if source.kind == "wheel" else "source.tar.gz"
            )
            request = urllib.request.Request(
                source.requirement, headers={"User-Agent": "AppRC distribution"}
            )
            digest = hashlib.sha256()
            assert_no_links(target)
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                target.open("xb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != source.digest:
                target.unlink(missing_ok=True)
                raise InstallationError(
                    "Downloaded source digest differs from the selected release asset."
                )
        else:
            source_path = Path(source.requirement)
            if not source_path.is_absolute() or not source_path.is_file():
                raise InstallationError(
                    "Release source must be an absolute local asset or HTTPS URL."
                )
            assert_no_links(source_path)
            target = staging / (
                source_path.name if source.kind == "wheel" else "source.tar.gz"
            )
            assert_no_links(target)
            if source_path == target:
                observed_digest = _sha256_file(source_path)
            else:
                digest = hashlib.sha256()
                with (
                    source_path.open("rb") as input_stream,
                    target.open("xb") as output,
                ):
                    while chunk := input_stream.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                observed_digest = digest.hexdigest()
            if observed_digest != source.digest:
                if source_path != target:
                    target.unlink(missing_ok=True)
                raise InstallationError(
                    "Local package asset digest differs from the selected release asset."
                )
        if source.kind == "wheel":
            root = staging / f"apprc-source-{source.digest}"
            wheel = root / target.name
            _validate_content_addressed_origin(source, source.digest, wheel)
            root.mkdir(mode=0o700)
            with target.open("rb") as original, wheel.open("xb") as output:
                shutil.copyfileobj(original, output)
            wheel.chmod(0o600)
            if (
                _sha256_file(target) != source.digest
                or _sha256_file(wheel) != source.digest
            ):
                raise InstallationError("Wheel changed during private staging.")
            return PreparedSource(
                str(wheel),
                _write_constraints(source, staging),
                source,
                source.digest,
                target,
                root,
            )
        return _materialize_archive(source, target, staging, source.digest)
    elif source.kind == "index" and source.requirement.startswith(
        "git+https://github.com/"
    ):
        return _prepare_main_archive(SourceSelection(source), staging)
    elif source.kind == "index":
        requirement = source.requirement
    else:
        raise InstallationError(
            f"Unsupported package source kind: {source.kind}."
        )

    constraints = _write_constraints(source, staging)
    return PreparedSource(requirement, constraints, source)
