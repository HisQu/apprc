"""Compile the shared AppRC manager and publish authenticated native assets."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from apprc.definition.installation import RuntimeSelection
from apprc.distribution._archives import _deterministic_zip
from apprc.distribution.metadata import _validate_project_declaration
from apprc.distribution.models import (
    Artifact,
    DistributionSpec,
    NativeBinding,
    decode_native_binding,
    encode_native_binding,
)
from apprc.distribution.native import (
    UV_MIN_VERSION,
    UV_REQUIREMENT,
    NativeArtifact,
    NativeFrontendBuilder,
    NativeTarget,
    _artifact_info,
)
from apprc.distribution.project import PreparedProject
from apprc.distribution.runtime.acquisition import materialize_project_snapshot
from apprc.user_files.app_home.locations import assert_no_links


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NativeDistribution:
    """Compiled native setups and their checksummed publication manifest."""

    artifacts: tuple[NativeArtifact, ...]
    checksums: Artifact


def _without_extra_marker(
    value: str, *, selected_extras: set[str]
) -> tuple[bool, str | None]:
    """Select SDK extra requirements without discarding platform markers."""
    from packaging.markers import Marker

    if ";" not in value:
        return True, None
    _, expression = value.split(";", 1)
    expression = str(Marker(expression.strip()))
    extra_tests = re.findall(
        r"extra\s*(==|!=)\s*(['\"])([^'\"]+)\2",
        expression,
    )
    if not extra_tests:
        if "extra" in expression:
            raise ValueError(
                f"Unsupported extra selector in SDK metadata: {value}"
            )
        return True, expression
    if " or " in expression:
        raise ValueError(
            f"Unsupported OR extra selector in SDK metadata: {value}"
        )
    if not any(
        all(
            (operator == "==" and extra == expected)
            or (operator == "!=" and extra != expected)
            for operator, _, expected in extra_tests
        )
        for extra in selected_extras
    ):
        return False, None
    fragment = r"\(?\s*extra\s*(?:==|!=)\s*(['\"])[^'\"]+\1\s*\)?"
    expression = re.sub(rf"^{fragment}$", "", expression).strip()
    expression = re.sub(rf"{fragment}\s+and\s+", "", expression).strip()
    expression = re.sub(rf"\s+and\s+{fragment}", "", expression).strip()
    expression = expression.strip("() ")
    if not expression:
        return True, None
    return True, str(Marker(expression))


def _bootstrap_requirements() -> tuple[str, ...]:
    """Select manager dependencies from the matching SDK distribution metadata."""
    from packaging.markers import Marker
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    selected: list[str] = []
    try:
        core = importlib.metadata.distribution("apprc-core")
        terminal = importlib.metadata.distribution("apprc")
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError(
            "Native authoring requires both apprc-core and apprc distributions "
            "from the maintained SDK workspace."
        ) from error
    if core.version != terminal.version:
        raise ValueError(
            "apprc-core and apprc authoring metadata versions do not match."
        )
    for distribution, extras in (
        (core, {"", "distribution"}),
        (terminal, {""}),
    ):
        for raw in distribution.metadata.get_all("Requires-Dist") or ():
            requirement = Requirement(raw)
            if canonicalize_name(requirement.name) in {"apprc", "apprc-core"}:
                continue
            include, marker = _without_extra_marker(raw, selected_extras=extras)
            if include:
                requirement.marker = Marker(marker) if marker else None
                selected.append(str(requirement))
    return tuple(sorted(set(selected)))


def _validate_prepared_project(
    spec: DistributionSpec, project: PreparedProject, workspace: Path
) -> None:
    """Verify archive bytes, selected metadata, and lock before native compilation."""
    declared_root = spec.metadata.project_root.expanduser().resolve()
    result = subprocess.run(
        ("git", "-C", str(declared_root), "rev-parse", "--show-toplevel"),
        check=True,
        capture_output=True,
        text=True,
    )
    repository = Path(result.stdout.strip()).resolve()
    root_relative = declared_root.relative_to(repository)
    explicit_path = spec.metadata.project_path
    extra_parts = (
        () if explicit_path == PurePosixPath(".") else explicit_path.parts
    )
    expected_parts = (*root_relative.parts, *extra_parts)
    expected_project_path = (
        str(PurePosixPath(*expected_parts)) if expected_parts else "."
    )
    if project.source.project_path != expected_project_path:
        raise ValueError(
            "Prepared snapshot selects a different committed project path."
        )
    staging = Path(
        tempfile.mkdtemp(prefix="apprc-author-check-", dir=workspace)
    )
    try:
        materialize_project_snapshot(project.archive, staging, project.source)
        project_path = PurePosixPath(project.source.project_path)
        selected = (
            staging
            if project_path == PurePosixPath(".")
            else (staging.joinpath(*project_path.parts))
        )
        _validate_project_declaration(spec, selected)
    finally:
        shutil.rmtree(staging)


def _sdk_archive(
    spec: DistributionSpec,
    project: PreparedProject,
    extras: Sequence[str],
) -> bytes:
    """Package exact SDK source and binding without an application dependency graph."""
    requirements = _bootstrap_requirements()
    core = importlib.metadata.distribution("apprc-core")
    terminal = importlib.metadata.distribution("apprc")
    package = files("apprc")
    entries: dict[str, bytes] = {}

    def add_tree(directory: Traversable, prefix: str) -> None:
        for item in sorted(directory.iterdir(), key=lambda entry: entry.name):
            name = f"{prefix}/{item.name}"
            if item.is_dir():
                if item.name == "__pycache__":
                    continue
                add_tree(item, name)
            elif item.is_file() and not item.name.endswith((".pyc", ".pyo")):
                entries[name] = item.read_bytes()

    add_tree(package, "apprc")
    for distribution in (core, terminal):
        metadata_files = [
            item
            for item in distribution.files or ()
            if item.name == "METADATA"
            and item.parent.name.endswith(".dist-info")
        ]
        if len(metadata_files) != 1:
            raise ValueError(
                f"Native authoring requires exact {distribution.metadata['Name']} distribution metadata."
            )
        item = metadata_files[0]
        entries[str(item)] = item.read_binary()
    if not entries.get("apprc/distribution/runtime/_manager.py"):
        raise ValueError(
            "SDK manager source is unavailable from the authoring package."
        )
    python = spec.metadata.runtime_python or "3.14"
    binding = NativeBinding(
        spec.metadata.identity,
        spec.metadata.command_name or spec.metadata.identity.commands[0],
        spec.display_name or spec.metadata.identity.app_id,
        spec.metadata.version,
        project.source,
        RuntimeSelection(python, tuple(extras)),
        spec.capabilities,
        spec.layout,
        spec.bootstrap_env_prefix,
        spec.maintenance_group_name,
        spec.hooks,
        spec.launch_enabled,
    )
    project_bytes = project.archive.read_bytes()
    if hashlib.sha256(project_bytes).hexdigest() != project.source.digest:
        raise ValueError(
            "Prepared project archive digest changed before SDK packaging."
        )
    entries["binding.json"] = encode_native_binding(binding)
    entries["project.zip"] = project_bytes
    entries["bootstrap-requirements.txt"] = (
        "\n".join((*requirements, UV_REQUIREMENT)) + "\n"
    ).encode()
    return _deterministic_zip(entries.items())


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


def _parse_previous_checksums(
    path: Path, dist: Path, *, app_id: str
) -> dict[str, str]:
    result = _read_native_checksums(path, app_id=app_id)
    for name, digest in result.items():
        output = dist / name
        assert_no_links(output)
        if (
            not output.is_file()
            or hashlib.sha256(output.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(f"Existing checksum does not authenticate {name}.")
    allowed = {
        f"{app_id}-setup-linux-x86_64",
        f"{app_id}-setup-windows-x86_64.exe",
    }
    for name in allowed - result.keys():
        output = dist / name
        assert_no_links(output)
        if output.exists():
            raise FileExistsError(
                "Refusing to replace unauthenticated native output "
                f"(no checksum manifest entry): {output}"
            )
    return result


class MissingNativeArtifact(ValueError):
    """A requested setup has never been published in this output set."""


class StaleNativeArtifact(ValueError):
    """An authenticated requested setup contains another source revision."""


def _inspect_native_setup(
    path: Path, *, app_id: str, target: NativeTarget
) -> NativeBinding:
    """Inspect a setup's executable and embedded project without executing it.

    :param path: Native setup executable, including its appended SDK archive.
    :param app_id: Expected application identity.
    :param target: Expected executable format and architecture.
    :return: Decoded binding after embedded project integrity checks.
    """
    assert_no_links(path)
    _artifact_info(path, target)
    try:
        with ZipFile(path) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("Native archive has duplicate entries.")
            binding = decode_native_binding(archive.read("binding.json"))
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
            if binding.command_name not in declaration.get("scripts", {}):
                raise ValueError("Native command is absent from the project.")
        return binding
    except (BadZipFile, KeyError, UnicodeError) as error:
        raise ValueError(f"Invalid native artifact {path}: {error}") from error


def _check_old_setup(
    path: Path, *, app_id: str, target: NativeTarget
) -> NativeBinding:
    """Authenticate one downloaded old setup while allowing other targets absent.

    :param path: Canonically named old setup beside its release SHA256SUMS.
    :param app_id: Expected application identity.
    :param target: Expected native target for this machine.
    :return: Checked binding used to compare old and current source versions.
    """
    if target not in ("x86_64-unknown-linux-gnu", "x86_64-pc-windows-msvc"):
        raise ValueError("Unsupported native setup target.")
    expected = (
        f"{app_id}-setup-windows-x86_64.exe"
        if target == "x86_64-pc-windows-msvc"
        else f"{app_id}-setup-linux-x86_64"
    )
    if path.name != expected:
        raise ValueError(f"Expected canonical old setup filename {expected}.")
    assert_no_links(path)
    entries = _read_native_checksums(path.parent / "SHA256SUMS", app_id=app_id)
    if (
        expected not in entries
        or hashlib.sha256(path.read_bytes()).hexdigest() != entries[expected]
    ):
        raise ValueError(f"Existing checksum does not authenticate {path}.")
    return _inspect_native_setup(path, app_id=app_id, target=target)


def check_native_distribution(
    root: Path,
    *,
    app_id: str,
    targets: Sequence[NativeTarget],
    revision: str,
) -> tuple[Path, ...]:
    """Inspect published native assets without executing or changing them.

    :param root: Authored project root containing the canonical dist directory.
    :param app_id: Expected application identity.
    :param targets: Targets required to be complete and fresh.
    :param revision: Full committed source revision expected in requested assets.
    :return: Checked requested setup paths, in requested target order.
    """
    names: dict[NativeTarget, str] = {
        "x86_64-unknown-linux-gnu": f"{app_id}-setup-linux-x86_64",
        "x86_64-pc-windows-msvc": f"{app_id}-setup-windows-x86_64.exe",
    }
    if (
        not targets
        or len(set(targets)) != len(targets)
        or any(target not in names for target in targets)
    ):
        raise ValueError("Native checks require unique supported targets.")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None:
        raise ValueError("Invalid native application identity.")
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision) is None:
        raise ValueError("Native freshness requires a full source commit ID.")
    dist = root / "dist"
    assert_no_links(dist)
    entries = _parse_previous_checksums(
        dist / "SHA256SUMS", dist, app_id=app_id
    )
    bindings: dict[str, NativeBinding] = {}
    for target, name in names.items():
        if name not in entries:
            continue
        path = dist / name
        bindings[name] = _inspect_native_setup(
            path, app_id=app_id, target=target
        )
    # > Validate every existing asset before allowing a missing/stale rebuild.
    missing = [
        names[target] for target in targets if names[target] not in entries
    ]
    if missing:
        raise MissingNativeArtifact(
            "Missing native setup: " + ", ".join(missing)
        )
    stale = [
        names[target]
        for target in targets
        if bindings[names[target]].source.commit != revision
    ]
    if stale:
        raise StaleNativeArtifact("Stale native setup: " + ", ".join(stale))
    return tuple(dist / names[target] for target in targets)


def _write_atomic(
    path: Path, content: bytes, *, executable: bool = False
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".apprc-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(0o755 if executable else 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _publish(
    spec: DistributionSpec,
    outputs: Mapping[str, tuple[bytes, bool]],
) -> Artifact:
    app_id = spec.metadata.identity.app_id
    allowed = {
        f"{app_id}-setup-linux-x86_64",
        f"{app_id}-setup-windows-x86_64.exe",
    }
    if not outputs or set(outputs) - allowed:
        raise ValueError(
            "Native publication contains an unsupported setup output."
        )
    assert_no_links(spec.metadata.project_root)
    root = spec.metadata.project_root.resolve()
    dist = root / "dist"
    assert_no_links(dist)
    previous_path = dist / "SHA256SUMS"
    assert_no_links(previous_path)
    previous = _parse_previous_checksums(
        previous_path, dist, app_id=spec.metadata.identity.app_id
    )
    existing_contents: dict[str, bytes | None] = {
        "SHA256SUMS": previous_path.read_bytes()
        if previous_path.exists()
        else None
    }
    for name, (content, _) in outputs.items():
        path = dist / name
        assert_no_links(path)
        try:
            old = path.read_bytes()
        except FileNotFoundError:
            old = None
        existing_contents[name] = old
        if old is not None and old != content:
            old_digest = hashlib.sha256(old).hexdigest()
            if previous.get(name) != old_digest:
                raise FileExistsError(
                    f"Refusing to replace unauthenticated native output: {path}"
                )
    retained = {
        name: digest
        for name, digest in previous.items()
        if name not in outputs and (dist / name).is_file()
    }
    all_digests = {
        **retained,
        **{
            name: hashlib.sha256(content).hexdigest()
            for name, (content, _) in outputs.items()
        },
    }
    checksums = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(all_digests.items())
    ).encode("ascii")
    try:
        dist.mkdir(parents=True, exist_ok=True)
        assert_no_links(dist)
    except OSError:
        raise
    staged: dict[str, Path] = {}
    backup = {
        name: existing_contents[name] for name in (*outputs, "SHA256SUMS")
    }
    try:
        for name, (content, executable) in (
            *outputs.items(),
            ("SHA256SUMS", (checksums, False)),
        ):
            fd, temp_name = tempfile.mkstemp(prefix=".apprc-stage-", dir=dist)
            temp = Path(temp_name)
            staged[name] = temp
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                temp.chmod(0o755 if executable else 0o644)
        published: list[str] = []
        for name in outputs:
            os.replace(staged[name], dist / name)
            published.append(name)
            del staged[name]
        os.replace(staged["SHA256SUMS"], previous_path)
        published.append("SHA256SUMS")
        del staged["SHA256SUMS"]
    except BaseException:
        for name in reversed(locals().get("published", [])):
            original = backup[name]
            path = dist / name
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _write_atomic(path, original, executable=name != "SHA256SUMS")
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    return Artifact(PurePosixPath("dist/SHA256SUMS"), checksums, False, root)


def _write_olis(
    dist: Path, app_id: str, environment: Mapping[str, str]
) -> None:
    """Render the two one-line install scripts for a successful native build.

    :param dist: Output directory already created by native publication.
    :param app_id: Validated application ID used in native setup filenames.
    :param environment: Authoring settings used only to select and render OLIS.
    """
    repository = environment.get("RELEASE_REPO_OLIS", "")
    variants = (("sh", "linux-x86_64"), ("ps1", "windows-x86_64.exe"))
    existing = False
    try:
        existing = any(
            path.exists() or path.is_symlink()
            for path in (
                dist / f"install_from_github.{ext}" for ext, _ in variants
            )
        )
        if not repository:
            if existing:
                logger.warning(
                    "Existing OLIS files may be stale. Set RELEASE_REPO_OLIS or pass "
                    "--olis-repo OWNER/REPO to refresh them."
                )
            return
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository
        ) or repository.rsplit("/", 1)[1] in {".", ".."}:
            raise ValueError("RELEASE_REPO_OLIS must be a GitHub OWNER/REPO.")
        visibility = environment.get("RELEASE_PUBLIC", "") or "false"
        if visibility not in {"true", "false"}:
            raise ValueError("RELEASE_PUBLIC must be true or false.")
        mode = "public" if visibility == "true" else "private"
        templates = files("apprc.distribution").joinpath("_templates")
        outputs = []
        for extension, setup_suffix in variants:
            content = templates.joinpath(
                f"github_{mode}.{extension}"
            ).read_text(encoding="utf-8")
            content = content.replace("@@REPOSITORY@@", repository).replace(
                "@@SETUP@@", f"{app_id}-setup-{setup_suffix}"
            )
            output = dist / f"install_from_github.{extension}"
            assert_no_links(output)
            outputs.append((output, content.encode("utf-8")))
        for output, content in outputs:
            _write_atomic(output, content, executable=output.suffix == ".sh")
    except (OSError, ValueError) as error:
        logger.warning(
            "Native build succeeded. OLIS generation failed: %s", error
        )
        if existing:
            logger.warning("Existing OLIS files may be stale.")


def build_native_distribution(
    spec: DistributionSpec,
    project: PreparedProject,
    *,
    uv: Path,
    workspace: Path,
    targets: Sequence[NativeTarget] = (
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    ),
    extras: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
) -> NativeDistribution:
    """Publish native setups and optionally generate one-line install scripts."""
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("Native builds require unique requested targets.")
    if any(
        target not in ("x86_64-unknown-linux-gnu", "x86_64-pc-windows-msvc")
        for target in targets
    ):
        raise ValueError("Native build requested an unsupported target.")
    assert_no_links(uv)
    if not uv.is_absolute() or not uv.is_file():
        raise ValueError("Native authoring requires an absolute uv executable.")
    uv_version = subprocess.run(
        (str(uv), "--version"), check=False, capture_output=True, text=True
    )
    match = re.match(
        r"^uv (\d+)\.(\d+)\.(\d+)(?:\s|$)", uv_version.stdout.strip()
    )
    minimum = tuple(int(part) for part in UV_MIN_VERSION.split("."))
    if (
        uv_version.returncode != 0
        or match is None
        or tuple(int(part) for part in match.groups()) < minimum
    ):
        raise ValueError(
            f"Native authoring requires {UV_REQUIREMENT}; "
            f"found {uv_version.stdout.strip()!r}."
        )
    if (
        not project.archive.is_file()
        or hashlib.sha256(project.archive.read_bytes()).hexdigest()
        != project.source.digest
    ):
        raise ValueError("Prepared project archive is missing or has changed.")
    workspace = workspace.expanduser().absolute()
    assert_no_links(workspace)
    workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
    if os.name == "nt":
        from apprc.user_files.app_home.permissions import (
            set_windows_private_acl,
        )

        set_windows_private_acl(workspace)
    _validate_prepared_project(spec, project, workspace)
    runtime_archive = workspace / "runtime.zip"
    archive_bytes = _sdk_archive(spec, project, extras)
    with runtime_archive.open("xb") as stream:
        stream.write(archive_bytes)
    builder = NativeFrontendBuilder(
        workspace / "compiler",
        environment=environment,
    )
    artifacts: list[NativeArtifact] = []
    artifact_names: list[str] = []
    output_bytes: dict[str, tuple[bytes, bool]] = {}
    for target in targets:
        windows = target == "x86_64-pc-windows-msvc"
        name = (
            f"{spec.metadata.identity.app_id}-setup-windows-x86_64.exe"
            if windows
            else f"{spec.metadata.identity.app_id}-setup-linux-x86_64"
        )
        compiled = workspace / "compiled" / name
        artifact = builder.build(
            target=target,
            destination=compiled,
            runtime_archive=runtime_archive,
            entrypoint="apprc.distribution.runtime._manager",
        )
        artifacts.append(artifact)
        artifact_names.append(name)
        output_bytes[name] = (compiled.read_bytes(), not windows)
    checksums = _publish(spec, output_bytes)
    dist = spec.metadata.project_root.resolve() / "dist"
    published_artifacts = tuple(
        NativeArtifact(
            dist / name,
            artifact.target,
            artifact.size,
            artifact.sha256,
            artifact.report,
        )
        for name, artifact in zip(artifact_names, artifacts, strict=True)
    )
    _write_olis(
        dist,
        spec.metadata.identity.app_id,
        os.environ if environment is None else environment,
    )
    return NativeDistribution(published_artifacts, checksums)
