"""Compile locked runtime requirements into a portable wheel inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, compatible_tags, cpython_tags, platform_tags
from packaging.utils import (
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from apprc.definition.installation import InstallationError, InstallationSource
from apprc.distribution.runtime.acquisition import (
    _archive_inputs,
    _selected_project,
    _sha256_file,
    validate_requirement,
)
from apprc.distribution.runtime.bundles import (
    _validate_entries,
    _validate_graph,
    _validate_wheel,
)
from apprc.distribution.models import (
    BundledWheel,
    CompiledWheelBundle,
    DistributionSpec,
    relative_destination,
)
from apprc.distribution.native import NativeTarget
from apprc.user_files.app_home.locations import assert_no_links


@dataclass(frozen=True, slots=True)
class _GitPackage:
    name: str
    version: str
    repository: str
    commit: str
    subdirectory: str | None
    marker: str | None
    requirement: str


@dataclass(frozen=True, slots=True)
class _WorkspacePackage:
    name: str
    version: str
    marker: str | None
    requested_extras: tuple[str, ...]


def _run(argv: list[str], *, cwd: Path, environment: Mapping[str, str]) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise InstallationError(
            f"Bundle build command failed ({Path(argv[0]).name}): "
            f"{result.stderr[-4000:]}"
        )
    return result.stdout


def _repository(value: str) -> str:
    address = urllib.parse.urlsplit(value.removeprefix("git+"))
    if (
        address.scheme not in {"https", "ssh"}
        or not address.hostname
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
    ):
        raise InstallationError(
            "Bundle repositories must use credential-free HTTPS or SSH URLs."
        )
    path = address.path.rstrip("/")
    decoded_path = urllib.parse.unquote(path)
    if (
        not path
        or "\\" in decoded_path
        or any(part in {".", ".."} for part in decoded_path.split("/"))
    ):
        raise InstallationError(
            "Bundle repository selector has an unsafe path."
        )
    try:
        port = address.port
    except ValueError as error:
        raise InstallationError(
            "Bundle repository URL has an invalid port."
        ) from error
    host = address.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if address.scheme == "https" else 22
    if port is not None and port != default_port:
        host += f":{port}"
    return urllib.parse.urlunsplit(
        (
            address.scheme.lower(),
            host,
            path.removesuffix(".git"),
            "",
            "",
        )
    )


def _is_default_pypi_index(value: str) -> bool:
    address = urllib.parse.urlsplit(value)
    try:
        port = address.port
    except ValueError:
        return False
    return (
        address.scheme.lower() == "https"
        and address.hostname is not None
        and address.hostname.lower() == "pypi.org"
        and port in {None, 443}
        and address.path.rstrip("/") == "/simple"
        and address.username is None
        and address.password is None
        and not address.query
        and not address.fragment
    )


def _validate_locked_origins(packages: list[dict[str, object]]) -> None:
    for package in packages:
        index = package.get("index")
        if index is not None and (
            not isinstance(index, str) or not _is_default_pypi_index(index)
        ):
            raise InstallationError(
                "Locked non-default package indexes are unsupported in portable "
                "wheel bundles; use default PyPI or a direct PEP 508 URL."
            )
        for source_name in ("archive", "sdist"):
            source = package.get(source_name)
            if source is None:
                continue
            if not isinstance(source, dict):
                raise InstallationError(
                    f"Locked {source_name} source metadata is invalid."
                )
            address = source.get("url")
            if source.get("path") is not None or (
                isinstance(address, str)
                and urllib.parse.urlsplit(address).scheme == "file"
            ):
                raise InstallationError(
                    "Local archive sources are unsupported in portable wheel bundles."
                )
        wheels = package.get("wheels", [])
        if not isinstance(wheels, list) or any(
            not isinstance(wheel, dict) for wheel in wheels
        ):
            raise InstallationError("Locked wheel source metadata is invalid.")
        for wheel in wheels:
            assert isinstance(wheel, dict)
            address = wheel.get("url")
            if wheel.get("path") is not None or (
                isinstance(address, str)
                and urllib.parse.urlsplit(address).scheme == "file"
            ):
                raise InstallationError(
                    "Local wheel sources are unsupported in portable wheel bundles."
                )


def _git_source(package: Mapping[str, object]) -> _GitPackage | None:
    source = package.get("vcs")
    if source is None:
        return None
    if (
        not isinstance(source, dict)
        or source.get("type") != "git"
        or not isinstance(source.get("url"), str)
    ):
        raise InstallationError("Locked non-Git VCS sources are unsupported.")
    revision = source.get("commit-id")
    requested = source.get("requested-revision", revision)
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", revision) is None
        or not isinstance(requested, str)
        or requested.lower() != revision.lower()
    ):
        raise InstallationError(
            "Locked Git runtime source must identify a full immutable commit."
        )
    repository = _repository(source["url"])
    subdirectory = source.get("subdirectory")
    if subdirectory is not None:
        if not isinstance(subdirectory, str):
            raise InstallationError("Locked Git subdirectory must be a string.")
        try:
            safe = relative_destination(subdirectory)
        except ValueError as error:
            raise InstallationError(
                "Locked Git subdirectory is unsafe."
            ) from error
        if str(safe) != subdirectory:
            raise InstallationError("Locked Git subdirectory is not canonical.")
    name, version = package.get("name"), package.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise InstallationError("Locked Git package is missing its identity.")
    marker = package.get("marker")
    if marker is not None and not isinstance(marker, str):
        raise InstallationError("Locked package marker is invalid.")
    requested_extras = package.get("requested-extras", [])
    if not isinstance(requested_extras, list) or not all(
        isinstance(extra, str) for extra in requested_extras
    ):
        raise InstallationError("Locked Git package extras are invalid.")
    extra_suffix = (
        f"[{','.join(sorted(requested_extras))}]" if requested_extras else ""
    )
    requirement = f"{name}{extra_suffix} @ git+{repository}@{revision.lower()}"
    if subdirectory:
        requirement += (
            f"#subdirectory={urllib.parse.quote(subdirectory, safe='/')}"
        )
    return _GitPackage(
        name,
        version,
        repository,
        revision.lower(),
        subdirectory,
        marker,
        requirement,
    )


def _active(
    marker: str | None, environment: Mapping[str, str] | None
) -> bool | None:
    if marker is None:
        return True
    if environment is None:
        return None
    parsed_marker = _marker(marker)
    return (
        parsed_marker.evaluate(environment, context="lock_file")
        if parsed_marker is not None
        else True
    )


def _marker(value: str | None) -> Marker | None:
    if value is None:
        return None
    try:
        return Requirement(f"x; {value}").marker
    except InvalidRequirement as error:
        raise InstallationError("Locked package marker is invalid.") from error


def _git_reference(value: str) -> tuple[str, str, str | None] | None:
    address = urllib.parse.urlsplit(value.removeprefix("git+"))
    if address.scheme not in {"https", "ssh"}:
        return None
    repository_path, separator, commit = address.path.rpartition("@")
    if not separator or not commit:
        return None
    try:
        repository = _repository(
            urllib.parse.urlunsplit(
                (address.scheme, address.netloc, repository_path, "", "")
            )
        )
    except InstallationError:
        return None
    fragment = urllib.parse.parse_qs(address.fragment, keep_blank_values=True)
    if (
        any(key != "subdirectory" for key in fragment)
        or len(fragment.get("subdirectory", [])) > 1
    ):
        return None
    subdirectory = fragment.get("subdirectory", [None])[0]
    return repository, commit.lower(), subdirectory


def _workspace_patterns(
    project_root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pyproject = project_root / "pyproject.toml"
    assert_no_links(pyproject)
    try:
        configuration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise InstallationError(
            "Could not read the lock project's workspace configuration."
        ) from error
    tool = configuration.get("tool", {})
    uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
    workspace = uv.get("workspace") if isinstance(uv, dict) else None
    if workspace is None:
        return (), ()
    if not isinstance(workspace, dict):
        raise InstallationError("uv workspace configuration must be a table.")
    patterns: list[tuple[str, ...]] = []
    for key in ("members", "exclude"):
        values = workspace.get(key, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise InstallationError(
                f"uv workspace {key} must be a list of paths."
            )
        normalized: list[str] = []
        for value in values:
            path = PurePosixPath(value)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in value
                or "\x00" in value
            ):
                raise InstallationError(
                    f"uv workspace {key} contains an unsafe path."
                )
            normalized.append(str(path))
        patterns.append(tuple(normalized))
    return patterns[0], patterns[1]


def _directory_project(
    package: Mapping[str, object], *, source_root: Path
) -> Path | None:
    source = package.get("directory")
    if source is None:
        return None
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise InstallationError(
            "Locked local package has an invalid directory source."
        )
    raw_path = source["path"]
    pure_path = PurePosixPath(raw_path)
    if (
        "://" in raw_path
        or "\\" in raw_path
        or "\x00" in raw_path
        or not raw_path
    ):
        raise InstallationError("Locked local package path is unsafe.")
    path = Path("/") if pure_path.is_absolute() else source_root.absolute()
    for part in pure_path.parts:
        if part in {"/", ".", ""}:
            continue
        path = path.parent if part == ".." else path / part
        assert_no_links(path)
    try:
        package_root = path.resolve(strict=True)
    except OSError as error:
        raise InstallationError(
            "Locked local package directory is unavailable."
        ) from error
    subdirectory = source.get("subdirectory")
    if subdirectory is not None:
        if not isinstance(subdirectory, str):
            raise InstallationError(
                "Locked local package subdirectory is invalid."
            )
        try:
            safe_subdirectory = relative_destination(subdirectory)
        except ValueError as error:
            raise InstallationError(
                "Locked local package subdirectory is unsafe."
            ) from error
        if str(safe_subdirectory) != subdirectory:
            raise InstallationError(
                "Locked local package subdirectory is not canonical."
            )
    else:
        safe_subdirectory = None
    return _selected_project(
        package_root,
        str(safe_subdirectory) if safe_subdirectory is not None else None,
    )


def _workspace_directory(
    package: Mapping[str, object],
    *,
    source_root: Path,
    project_root: Path,
    members: tuple[str, ...],
    excluded: tuple[str, ...],
) -> Path | None:
    project = _directory_project(package, source_root=source_root)
    if project is None:
        return None
    root = project_root.resolve(strict=True)
    if not project.is_relative_to(root):
        raise InstallationError(
            "External locked path sources are unsupported; declare this package "
            "as a workspace member or publish it to an index."
        )
    relative = PurePosixPath(project.relative_to(root).as_posix())
    if project != root and (
        not members
        or not any(relative.match(pattern) for pattern in members)
        or any(relative.match(pattern) for pattern in excluded)
    ):
        raise InstallationError(
            "Locked local path source is not a declared uv workspace member."
        )
    name, version = package.get("name"), package.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise InstallationError(
            "Locked workspace package is missing its identity."
        )
    try:
        Requirement(f"{name}=={version}")
    except InvalidRequirement as error:
        raise InstallationError(
            "Locked workspace package identity is invalid."
        ) from error
    return project


def _project_lock(project_root: Path) -> Path:
    """Find the selected project's nearest existing lock without changing it."""
    project_root = project_root.resolve(strict=True)
    lock_file = next(
        (
            parent / "uv.lock"
            for parent in (project_root, *project_root.parents)
            if (parent / "uv.lock").is_file()
        ),
        None,
    )
    if lock_file is None:
        raise InstallationError("The application has no existing uv.lock.")
    assert_no_links(lock_file)
    return lock_file


def _normalize_directory_versions(
    packages: list[dict[str, object]],
    *,
    lock_file: Path,
    project_root: Path,
    root_name: str,
    root_version: str,
) -> None:
    """Recover directory versions from exact source identities in uv's lock."""
    project_root = project_root.resolve(strict=True)
    try:
        locked = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise InstallationError(
            "Could not read the existing uv.lock."
        ) from error
    locked_packages = locked.get("package")
    if not isinstance(locked_packages, list) or not all(
        isinstance(package, dict) for package in locked_packages
    ):
        raise InstallationError(
            "uv.lock has no valid locked package inventory."
        )
    members, excluded = _workspace_patterns(lock_file.parent)
    root_records = 0
    for package in packages:
        if "directory" not in package:
            continue
        name = package.get("name")
        if not isinstance(name, str):
            raise InstallationError("Locked directory package has no name.")
        project = _directory_project(package, source_root=lock_file.parent)
        candidates: list[str] = []
        for locked_package in locked_packages:
            locked_name = locked_package.get("name")
            source = locked_package.get("source")
            if (
                not isinstance(locked_name, str)
                or canonicalize_name(locked_name) != canonicalize_name(name)
                or not isinstance(source, dict)
            ):
                continue
            paths = [
                source[key] for key in ("editable", "path") if key in source
            ]
            if not paths:
                continue
            if len(paths) != 1 or not isinstance(paths[0], str):
                raise InstallationError("Locked directory source is ambiguous.")
            locked_project = _directory_project(
                {"directory": {"path": paths[0]}}, source_root=lock_file.parent
            )
            if locked_project != project:
                continue
            version = locked_package.get("version")
            if not isinstance(version, str):
                raise InstallationError("Locked directory version is missing.")
            try:
                Version(version)
            except InvalidVersion as error:
                raise InstallationError(
                    "Locked directory version is invalid."
                ) from error
            candidates.append(version)
        if len(candidates) != 1:
            raise InstallationError(
                "Directory package has missing or ambiguous locked source/version provenance."
            )
        version = candidates[0]
        exported_version = package.get("version")
        if "version" in package:
            if not isinstance(exported_version, str):
                raise InstallationError(
                    "Exported directory version is invalid."
                )
            try:
                matches = Version(exported_version) == Version(version)
            except InvalidVersion as error:
                raise InstallationError(
                    "Exported directory version is invalid."
                ) from error
            if not matches:
                raise InstallationError(
                    "Exported directory version differs from uv.lock."
                )
        package["version"] = version
        _workspace_directory(
            package,
            source_root=lock_file.parent,
            project_root=lock_file.parent,
            members=members,
            excluded=excluded,
        )
        if canonicalize_name(name) == root_name:
            root_records += 1
            if project != project_root or Version(version) != Version(
                root_version
            ):
                raise InstallationError(
                    "Locked application directory/version differs from its metadata."
                )
    if root_records != 1:
        raise InstallationError(
            "The exported application directory identity is missing or ambiguous."
        )


def _locked_git_for_requirement(
    requirement: Requirement, packages: list[_GitPackage]
) -> _GitPackage:
    if requirement.url is None:
        raise InstallationError(
            "Locked Git requirement is missing its source URL."
        )
    reference = _git_reference(requirement.url)
    candidates = [
        package
        for package in packages
        if canonicalize_name(package.name)
        == canonicalize_name(requirement.name)
        and _marker(package.marker) == requirement.marker
        and (
            package.repository,
            package.commit,
            package.subdirectory,
        )
        == reference
    ]
    if len(candidates) != 1:
        raise InstallationError(
            "uv requirements export does not map uniquely to its locked Git package."
        )
    return candidates[0]


def _wheel(
    path: Path,
    *,
    target_tags: set[Tag],
    expected_name: str,
    expected_version: str,
) -> tuple[str, str, str]:
    try:
        name, version, _, tags = parse_wheel_filename(path.name)
        if name != canonicalize_name(expected_name) or version != Version(
            expected_version
        ):
            raise InstallationError(
                "Built wheel filename differs from its locked package identity."
            )
        _validate_wheel(
            path,
            BundledWheel(
                expected_name, expected_version, path.name, _sha256_file(path)
            ),
        )
        if not tags.intersection(target_tags):
            raise InstallationError(
                "Built wheel does not support the requested native target."
            )
    except (InvalidVersion, ValueError) as error:
        if isinstance(error, InstallationError):
            raise
        raise InstallationError("Built wheel metadata is invalid.") from error
    return name, str(version), path.name


def compile_wheel_bundle(
    spec: DistributionSpec,
    destination: Path,
    *,
    uv: Path,
    application_source: Path,
    extras: tuple[str, ...] = (),
    target: NativeTarget = "x86_64-unknown-linux-gnu",
    python_version: str = "3.14",
    marker_environment: Mapping[str, str] | None = None,
    require_no_git: bool = True,
    environment: Mapping[str, str] | None = None,
) -> CompiledWheelBundle:
    """Build root, selected Git, and locked workspace wheels into a portable bundle.

    uv exports the selected locked package graph; this compiler never resolves
    dependencies itself. Git checkouts and all backends run only on the
    authoring machine. Non-default package indexes and external local path
    sources are refused because the durable runtime graph stores PEP 508
    requirements rather than uv index directives or authoring paths.

    :param spec: Explicit distribution metadata and repository allow-list.
    :param destination: New directory receiving the completed payload.
    :param uv: Absolute uv executable used for locked exports and builds.
    :param application_source: Actual backend project directory or release sdist.
    :param extras: Requested application extras.
    :param target: Supported native target used for wheel compatibility checks.
    :param python_version: Selected interpreter minor for builds and tag checks.
    :param marker_environment: Optional complete PEP 508 environment overrides.
    :param require_no_git: Refuse remaining active or indeterminate Git sources.
    :param environment: Optional subprocess environment.
    :return: Root source identity, portable wheel inventory, and remaining Git URLs.
    """
    if spec.runtime_requirements or spec.runtime_overrides:
        raise InstallationError(
            "Wheel bundle runtime dependencies must come from the locked project "
            "profile; declare dependencies and extras in pyproject.toml instead "
            "of passing runtime_requirements or runtime_overrides."
        )
    if (
        not uv.is_absolute()
        or not application_source.is_absolute()
        or not destination.is_absolute()
    ):
        raise InstallationError(
            "uv, application source, and bundle destination must be absolute paths."
        )
    if destination.exists() or destination.is_symlink():
        raise InstallationError("Bundle destination already exists.")
    if extras != tuple(dict.fromkeys(extras)) or any(
        not isinstance(item, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item)
        for item in extras
    ):
        raise InstallationError(
            "Requested bundle extras must be unique safe names."
        )
    if any(
        not isinstance(value, str)
        for value in spec.metadata.bundle_repositories
    ):
        raise InstallationError("Bundle repository selectors must be strings.")
    repositories = {
        _repository(item) for item in spec.metadata.bundle_repositories
    }
    assert_no_links(application_source)
    if not application_source.exists():
        raise InstallationError("Application build input does not exist.")
    if spec.source_mode == "release":
        if not application_source.is_file():
            raise InstallationError(
                "Release build input must be the verified sdist archive."
            )
        asset = spec.release_asset or ""
        basename = Path(
            urllib.parse.unquote(urllib.parse.urlsplit(asset).path or asset)
        ).name
        try:
            archive_name, archive_version = parse_sdist_filename(basename)
        except (InvalidVersion, ValueError) as error:
            raise InstallationError(
                "Release asset must have a valid sdist filename."
            ) from error
        if (
            basename != application_source.name
            or archive_name
            != canonicalize_name(spec.metadata.identity.distribution)
            or str(archive_version) != spec.release_version
            or _sha256_file(application_source) != spec.release_digest
        ):
            raise InstallationError(
                "Release sdist filename, version, or SHA-256 differs from its declared identity."
            )
    env = dict(os.environ if environment is None else environment)
    with tempfile.TemporaryDirectory(
        prefix="apprc-wheel-authoring-"
    ) as temporary:
        work = Path(temporary)
        lock_file = _project_lock(spec.metadata.project_root)
        lock_root = lock_file.parent
        command = [
            str(uv),
            "export",
            "--locked",
            "--no-dev",
            "--no-default-groups",
            "--package",
            spec.metadata.identity.distribution,
            "--format",
            "pylock.toml",
        ]
        for extra in extras:
            command.extend(("--extra", extra))
        # > Stdout paths are relative to the export cwd. Using the workspace
        # > root also preserves that origin when selecting a member package.
        exported_lock = _run(command, cwd=lock_root, environment=env)
        requirements_export = work / "runtime-requirements.txt"
        requirements_command = [
            str(uv),
            "export",
            "--locked",
            "--no-dev",
            "--no-default-groups",
            "--package",
            spec.metadata.identity.distribution,
            "--no-emit-workspace",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements_export),
        ]
        for extra in extras:
            requirements_command.extend(("--extra", extra))
        _run(
            requirements_command,
            cwd=spec.metadata.project_root,
            environment=env,
        )
        try:
            exported_requirements = tuple(
                Requirement(line)
                for line in requirements_export.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip() and not line.startswith("#")
            )
        except InvalidRequirement as error:
            raise InstallationError(
                "uv requirements export contains an invalid runtime requirement."
            ) from error
        graph = tomllib.loads(exported_lock)
        packages = graph.get("packages")
        if (
            not isinstance(packages, list)
            or not packages
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or (
                    "directory" not in item
                    and not isinstance(item.get("version"), str)
                )
                for item in packages
            )
        ):
            raise InstallationError(
                "uv did not export a complete locked runtime package graph."
            )
        _normalize_directory_versions(
            packages,
            lock_file=lock_file,
            project_root=spec.metadata.project_root,
            root_name=canonicalize_name(spec.metadata.identity.distribution),
            root_version=spec.metadata.version,
        )
        for item in packages:
            if not isinstance(item.get("version"), str):
                raise InstallationError(
                    "uv exported a locked package without a string version."
                )
            try:
                Requirement(f"{item['name']}=={item['version']}")
                if item.get("marker") is not None:
                    if not isinstance(item["marker"], str):
                        raise InvalidRequirement(
                            "Package marker is not a string."
                        )
                    Requirement(f"x; {item['marker']}")
            except InvalidRequirement as error:
                raise InstallationError(
                    "uv exported an invalid locked package identity."
                ) from error
        _validate_locked_origins(packages)
        locked_git = [
            package
            for item in packages
            if (package := _git_source(item)) is not None
        ]
        selected: list[_GitPackage] = []
        remaining: list[str] = []
        unsafe_remaining: list[str] = []
        selected_keys: set[tuple[str, str, str | None, str, str | None]] = set()
        for requirement in exported_requirements:
            if requirement.url is None:
                continue
            if requirement.url.startswith("git+"):
                package = _locked_git_for_requirement(requirement, locked_git)
                key = (
                    package.repository,
                    package.commit,
                    package.subdirectory,
                    package.name,
                    package.marker,
                )
                if package.repository in repositories:
                    if key not in selected_keys:
                        selected.append(package)
                        selected_keys.add(key)
                else:
                    remaining_source = str(requirement)
                    if remaining_source not in remaining:
                        remaining.append(remaining_source)
                    if _active(package.marker, marker_environment) is not False:
                        unsafe_remaining.append(remaining_source)
            elif urllib.parse.urlsplit(requirement.url).scheme == "file":
                raise InstallationError(
                    "External local path requirements are unsupported; declare "
                    "the package as a uv workspace member or publish it to an index."
                )
        unknown = repositories - {item.repository for item in selected}
        if unknown:
            raise InstallationError(
                "Unknown bundle repository selector(s): "
                + ", ".join(sorted(unknown))
            )
        if require_no_git and unsafe_remaining:
            raise InstallationError(
                "Runtime Git sources remain active or indeterminate outside "
                "bundle-repositories: " + ", ".join(unsafe_remaining)
            )
        root_name = canonicalize_name(spec.metadata.identity.distribution)
        workspace_members, workspace_excluded = _workspace_patterns(lock_root)
        workspace_projects: list[tuple[_WorkspacePackage, Path]] = []
        for item in packages:
            if (
                canonicalize_name(item["name"]) == root_name
                or "directory" not in item
            ):
                continue
            project = _workspace_directory(
                item,
                source_root=lock_root,
                project_root=lock_root,
                members=workspace_members,
                excluded=workspace_excluded,
            )
            if project is not None:
                name = item.get("name")
                version = item.get("version")
                marker = item.get("marker")
                requested_extras = item.get("requested-extras", [])
                if not isinstance(name, str) or not isinstance(version, str):
                    raise InstallationError(
                        "Locked workspace package is missing its identity."
                    )
                if (
                    marker is not None
                    and not isinstance(marker, str)
                    or not isinstance(requested_extras, list)
                    or not all(
                        isinstance(extra, str) for extra in requested_extras
                    )
                ):
                    raise InstallationError(
                        "Locked workspace package metadata is invalid."
                    )
                workspace_projects.append(
                    (
                        _WorkspacePackage(
                            name,
                            version,
                            marker,
                            tuple(requested_extras),
                        ),
                        project,
                    )
                )
        # > Validate parsed requirement sources before publishing the bundle.
        for requirement in exported_requirements:
            validate_requirement(str(requirement))
        for package in selected:
            validate_requirement(package.requirement)
        python_requirement = (
            f"{spec.metadata.python_requirement},=={python_version}.*"
        )
        target_tags = _target_tags(target, python_version)
        build_input = application_source
        if spec.source_mode == "release":
            build_input = work / "release-source"
            build_input.mkdir(mode=0o700)
            _archive_inputs(application_source, build_input, extract=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_temporary = tempfile.TemporaryDirectory(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        stage = Path(output_temporary.name) / "payload"
        stage.mkdir(mode=0o700)
        wheels_dir = stage
        built: list[BundledWheel] = []
        # > Build the supplied input after checking its release identity.
        _run(
            [
                str(uv),
                "build",
                "--wheel",
                "--no-sources",
                "--python",
                python_requirement,
                "--out-dir",
                str(wheels_dir),
                str(build_input),
            ],
            cwd=work,
            environment=env,
        )
        root_files = list(wheels_dir.glob("*.whl"))
        if len(root_files) != 1:
            raise InstallationError(
                "Application backend must produce exactly one root wheel."
            )
        root_name, root_version, root_filename = _wheel(
            root_files[0],
            target_tags=target_tags,
            expected_name=spec.metadata.identity.distribution,
            expected_version=spec.metadata.version,
        )
        root_digest = _sha256_file(root_files[0])
        built.append(
            BundledWheel(root_name, root_version, root_filename, root_digest)
        )
        checkouts: dict[tuple[str, str], Path] = {}
        built_git_packages: set[tuple[str, str, str | None]] = set()
        for package in selected:
            key = (package.repository, package.commit)
            checkout = checkouts.get(key)
            if checkout is None:
                checkout = (
                    work
                    / "checkouts"
                    / hashlib.sha256(
                        (package.repository + package.commit).encode()
                    ).hexdigest()
                )
                checkout.parent.mkdir(exist_ok=True)
                _run(
                    [
                        "git",
                        "clone",
                        "--no-checkout",
                        package.repository,
                        str(checkout),
                    ],
                    cwd=work,
                    environment=env,
                )
                _run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "checkout",
                        "--detach",
                        package.commit,
                    ],
                    cwd=work,
                    environment=env,
                )
                observed = subprocess.run(
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                if observed != package.commit:
                    raise InstallationError(
                        "Git checkout did not match the locked commit."
                    )
                checkouts[key] = checkout
            build_key = (
                package.repository,
                package.commit,
                package.subdirectory,
            )
            if build_key in built_git_packages:
                continue
            project = _selected_project(checkout, package.subdirectory)
            output = (
                work
                / "built"
                / hashlib.sha256(repr(build_key).encode()).hexdigest()
            )
            output.mkdir(parents=True)
            _run(
                [
                    str(uv),
                    "build",
                    "--wheel",
                    "--no-sources",
                    "--python",
                    python_requirement,
                    "--out-dir",
                    str(output),
                    str(project),
                ],
                cwd=work,
                environment=env,
            )
            candidates = list(output.glob("*.whl"))
            if len(candidates) != 1:
                raise InstallationError(
                    "Selected Git project must produce exactly one wheel."
                )
            wheel = candidates[0]
            name, version, filename = _wheel(
                wheel,
                target_tags=target_tags,
                expected_name=package.name,
                expected_version=package.version,
            )
            destination_wheel = wheels_dir / filename
            shutil.copyfile(wheel, destination_wheel)
            built.append(
                BundledWheel(
                    name,
                    version,
                    filename,
                    _sha256_file(destination_wheel),
                    marker=package.marker,
                    repository=package.repository,
                    commit=package.commit,
                    subdirectory=package.subdirectory,
                    original_requirement=package.requirement,
                )
            )
            built_git_packages.add(build_key)
        built_workspace_packages: set[tuple[str, str, str]] = set()
        for package, project in workspace_projects:
            build_key = (str(project), package.name, package.version)
            if build_key in built_workspace_packages:
                raise InstallationError(
                    "Duplicate locked workspace project identity is ambiguous."
                )
            output = (
                work
                / "built-workspace"
                / hashlib.sha256(repr(build_key).encode()).hexdigest()
            )
            output.mkdir(parents=True)
            _run(
                [
                    str(uv),
                    "build",
                    "--wheel",
                    "--no-sources",
                    "--python",
                    python_requirement,
                    "--out-dir",
                    str(output),
                    str(project),
                ],
                cwd=work,
                environment=env,
            )
            candidates = list(output.glob("*.whl"))
            if len(candidates) != 1:
                raise InstallationError(
                    "Locked workspace project must produce exactly one wheel."
                )
            wheel = candidates[0]
            wheel_name, wheel_version, filename = _wheel(
                wheel,
                target_tags=target_tags,
                expected_name=package.name,
                expected_version=package.version,
            )
            destination_wheel = wheels_dir / filename
            shutil.copyfile(wheel, destination_wheel)
            built.append(
                BundledWheel(
                    wheel_name,
                    wheel_version,
                    filename,
                    _sha256_file(destination_wheel),
                    marker=package.marker,
                )
            )
            built_workspace_packages.add(build_key)
        requirements: list[str] = []
        for requirement in exported_requirements:
            if requirement.url is not None and requirement.url.startswith(
                "git+"
            ):
                package = _locked_git_for_requirement(requirement, locked_git)
                if package.repository in repositories:
                    pin = f"{requirement.name}"
                    if requirement.extras:
                        pin += f"[{','.join(sorted(requirement.extras))}]"
                    pin += f"=={package.version}"
                    if requirement.marker is not None:
                        pin += f"; {requirement.marker}"
                    requirements.append(str(Requirement(pin)))
                    continue
            requirements.append(str(requirement))
        for package, _ in workspace_projects:
            pin = package.name
            if package.requested_extras:
                pin += f"[{','.join(sorted(package.requested_extras))}]"
            pin += f"=={package.version}"
            if package.marker:
                pin += f"; {package.marker}"
            requirements.append(str(Requirement(pin)))
        root_pins = [
            Requirement(row)
            for row in requirements
            if canonicalize_name(Requirement(row).name) == root_name
            and Requirement(row).url is None
        ]
        if root_pins and any(
            str(pin.specifier) != f"=={root_version}" for pin in root_pins
        ):
            raise InstallationError(
                "Locked root wheel version differs from the application metadata."
            )
        if not root_pins:
            root_requirement = (
                f"{spec.metadata.identity.distribution}[{','.join(extras)}]"
                if extras
                else spec.metadata.identity.distribution
            )
            requirements.append(
                str(Requirement(f"{root_requirement}=={root_version}"))
            )
        if not requirements:
            raise InstallationError(
                "uv runtime export contains no pinned packages."
            )
        wheel_inventory = tuple(built)
        for requirement in requirements:
            validate_requirement(requirement)
        _validate_entries(wheel_inventory)
        source = InstallationSource(
            "wheel",
            root_filename,
            version=root_version,
            digest=root_digest,
            runtime_requirements=tuple(requirements),
        )
        _validate_graph(source, wheel_inventory)
        (stage / "runtime-requirements.txt").write_text(
            "".join(row + "\n" for row in requirements), encoding="utf-8"
        )
        (stage / "inventory.json").write_text(
            json.dumps(
                [
                    {
                        field: getattr(entry, field)
                        for field in entry.__dataclass_fields__
                    }
                    for entry in wheel_inventory
                ],
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(stage, destination)
        output_temporary.cleanup()
        return CompiledWheelBundle(
            destination, source, wheel_inventory, tuple(remaining)
        )


def _target_tags(target: NativeTarget, python_version: str) -> set[Tag]:
    try:
        major, minor = (int(part) for part in python_version.split(".", 1))
    except (ValueError, TypeError) as error:
        raise InstallationError(
            "python_version must be major.minor."
        ) from error
    platforms = (
        ["win_amd64"]
        if target == "x86_64-pc-windows-msvc"
        else list(platform_tags())
    )
    version = (major, minor)
    tags = set(cpython_tags(version, platforms=platforms))
    tags.update(
        compatible_tags(
            version, interpreter=f"cp{major}{minor}", platforms=platforms
        )
    )
    return tags
