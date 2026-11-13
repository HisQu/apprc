"""Create verified private snapshots from committed Git trees."""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from apprc.definition.installation import ProjectSnapshot
from apprc.distribution.metadata import read_project_metadata
from apprc.distribution.models import DistributionSpec, relative_destination
from apprc.distribution.runtime.acquisition import (
    _archive_inputs,
    _assert_private_staging,
    _sha256_file,
)
from apprc.user_files.app_home.locations import assert_no_links


@dataclass(frozen=True, slots=True)
class PreparedProject:
    """Verified immutable project ZIP and its authority metadata."""

    archive: Path
    source: ProjectSnapshot


def _git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("Unable to resolve or export the requested committed project.")
    return result.stdout


def _validate_workspace(tree: Path) -> None:
    """Validate every workspace member and local source against the full tree."""
    tree_root = tree.resolve()
    project_files = sorted(tree.rglob("pyproject.toml"))
    if not project_files:
        raise ValueError("Committed project snapshot contains no pyproject.toml.")
    for pyproject in project_files:
        assert_no_links(pyproject)
        with pyproject.open("rb") as stream:
            document = tomllib.load(stream)
        tool = document.get("tool", {})
        uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
        if not isinstance(uv, dict):
            raise ValueError("tool.uv must be a table.")
        workspace = uv.get("workspace", {})
        if not isinstance(workspace, dict):
            raise ValueError("tool.uv.workspace must be a table.")
        members = workspace.get("members", [])
        excludes = workspace.get("exclude", [])
        if not isinstance(members, list) or not all(isinstance(item, str) for item in members):
            raise ValueError("Workspace members must be relative path patterns.")
        if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
            raise ValueError("Workspace excludes must be relative path patterns.")
        for pattern in (*members, *excludes):
            pattern_path = PurePosixPath(pattern)
            if (
                not pattern
                or pattern_path.is_absolute()
                or ".." in pattern_path.parts
                or "\\" in pattern
                or PureWindowsPath(pattern).drive
            ):
                raise ValueError(f"Workspace pattern is not a safe relative path: {pattern}.")
            matches = [
                Path(match)
                for match in glob.glob(str(pyproject.parent / pattern), recursive=True)
            ]
            if pattern in members and not matches:
                raise ValueError(f"Workspace member pattern has no committed match: {pattern}.")
            for match in matches:
                assert_no_links(match)
                if not match.resolve().is_relative_to(tree_root):
                    raise ValueError(f"Workspace pattern escapes the exported tree: {pattern}.")
                if pattern in members and (
                    not match.is_dir() or not (match / "pyproject.toml").is_file()
                ):
                    raise ValueError(f"Workspace member has no pyproject.toml: {pattern}.")
        sources = uv.get("sources", {})
        if not isinstance(sources, dict):
            raise ValueError("tool.uv.sources must be a table.")
        for declaration in sources.values():
            alternatives = declaration if isinstance(declaration, list) else [declaration]
            for source in alternatives:
                if not isinstance(source, dict) or "path" not in source:
                    continue
                path = source["path"]
                if (
                    not isinstance(path, str)
                    or not path
                    or PurePosixPath(path).is_absolute()
                    or PureWindowsPath(path).drive
                    or "\\" in path
                ):
                    raise ValueError("Local uv source paths must be safe relative paths.")
                resolved = (pyproject.parent / path).resolve()
                if not resolved.is_relative_to(tree_root) or not resolved.exists():
                    raise ValueError(
                        f"Local uv source escapes or is missing from committed tree: {path}."
                    )

def _remove_generated(
    tree: Path,
    baseline_directories: set[PurePosixPath],
    baseline_files: dict[PurePosixPath, str],
) -> None:
    """Remove generated environments and caches without deleting source assets."""
    always_remove = {
        "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".cache", ".bun", ".vite", ".turbo",
        ".tox", "target",
    }
    for current, directories, _ in os.walk(tree, topdown=True, followlinks=False):
        parent = Path(current)
        for name in tuple(directories):
            path = parent / name
            relative = PurePosixPath(path.relative_to(tree).as_posix())
            if name in always_remove or name.endswith(".egg-info"):
                shutil.rmtree(path)
                directories.remove(name)
                continue
            if name not in {"build", "dist"}:
                if path.is_symlink():
                    raise ValueError(f"Project snapshot contains a directory link: {relative}.")
                continue
            if relative not in baseline_directories or relative.parent == PurePosixPath("."):
                shutil.rmtree(path)
                directories.remove(name)
                continue
            frontend_config = (parent / "package.json").is_file() and any(
                (parent / config).is_file()
                for config in ("vite.config.js", "vite.config.ts", "vite.config.mjs")
            )
            if name == "dist" and frontend_config:
                shutil.rmtree(path)
                directories.remove(name)
                continue
            for output in sorted(path.rglob("*"), reverse=True):
                if output.is_symlink():
                    raise ValueError("Generated project output contains a link.")
                if output.is_dir():
                    continue
                assert_no_links(output)
                address = PurePosixPath(output.relative_to(tree).as_posix())
                if baseline_files.get(address) != _sha256_file(output):
                    output.unlink()
            for output in sorted(path.rglob("*"), reverse=True):
                if output.is_symlink():
                    raise ValueError("Generated project output contains a link.")
                if output.is_dir() and not any(output.iterdir()):
                    output.rmdir()


def _nearest_lockfile(tree: Path, selected: Path) -> Path:
    for directory in (selected, *selected.parents):
        if not directory.is_relative_to(tree) or directory == tree.parent:
            break
        lockfile = directory / "uv.lock"
        if lockfile.is_file():
            assert_no_links(lockfile)
            return lockfile
    raise ValueError("Committed workspace has no uv.lock at the selected project or an ancestor.")


def _project_configuration(tree: Path) -> dict[PurePosixPath, bytes]:
    ignored = {
        "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".cache", ".bun", ".vite", ".turbo",
        ".tox", "target", "build", "dist",
    }
    result: dict[PurePosixPath, bytes] = {}
    for path in sorted(tree.rglob("pyproject.toml")):
        relative = path.relative_to(tree)
        if any(part in ignored or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.is_file():
            result[PurePosixPath(relative.as_posix())] = path.read_bytes()
    return result

def _project_lockfiles(tree: Path) -> dict[PurePosixPath, bytes]:
    ignored = {
        "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".cache", ".bun", ".vite", ".turbo",
        ".tox", "target", "build", "dist",
    }
    return {
        PurePosixPath(path.relative_to(tree).as_posix()): path.read_bytes()
        for path in sorted(tree.rglob("uv.lock"))
        if path.is_file()
        and not any(part in ignored or part.endswith(".egg-info") for part in path.relative_to(tree).parts)
    }

def _baseline_output_files(tree: Path) -> dict[PurePosixPath, str]:
    result: dict[PurePosixPath, str] = {}
    for current, _, filenames in os.walk(tree, topdown=True, followlinks=False):
        parent = Path(current)
        if not any(part in {"build", "dist"} for part in parent.relative_to(tree).parts):
            continue
        for name in filenames:
            path = parent / name
            if path.is_file() and not path.is_symlink():
                result[PurePosixPath(path.relative_to(tree).as_posix())] = _sha256_file(path)
    return result


def build_project_snapshot(
    spec: DistributionSpec,
    *,
    revision: str,
    destination: Path,
    prepare: Callable[[Path], None] | None = None,
) -> PreparedProject:
    """Export one exact committed project and serialize its private prepared tree.

    :param spec: Author declaration whose identity must match the committed tree.
    :param revision: Git revision resolved to a full commit before export.
    :param destination: New archive destination; existing paths are rejected.
    :param prepare: Optional transformation of the private exported copy only.
    :return: Deterministic archive and immutable source/lock/commit identity.
    """
    declared_root = spec.metadata.project_root.expanduser().absolute()
    assert_no_links(declared_root)
    root = declared_root.resolve()
    repository = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if not root.is_relative_to(repository):
        raise ValueError("Selected project is outside its Git repository.")
    root_relative = root.relative_to(repository)
    explicit_path = spec.metadata.project_path
    extra_parts = (
        ()
        if explicit_path == PurePosixPath(".")
        else relative_destination(explicit_path).parts
    )
    project_parts = (*root_relative.parts, *extra_parts)
    project_path = PurePosixPath(*project_parts) if project_parts else PurePosixPath(".")
    destination = destination.expanduser().absolute()
    assert_no_links(destination)
    if destination.exists():
        raise FileExistsError(destination)
    commit = _git(
        repository, "rev-parse", "--verify", f"{revision}^{{commit}}"
    ).decode().strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("Git did not resolve the revision to a full commit ID.")
    tar_bytes = _git(repository, "archive", "--format=tar", commit)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="apprc-project-", dir=destination.parent))
    stage.chmod(0o700)
    _assert_private_staging(stage)
    created_output = False
    try:
        tarball = stage / "tree.tar"
        tarball.write_bytes(tar_bytes)
        tree = stage / "tree"
        tree.mkdir(mode=0o700)
        _archive_inputs(tarball, tree, extract=True, strip_wrapper=False)
        selected = tree.joinpath(*project_parts) if project_parts else tree
        if not selected.is_dir():
            raise ValueError("Committed selected project path is missing from the exported tree.")
        committed_metadata = read_project_metadata(selected)
        if (
            committed_metadata.identity != spec.metadata.identity
            or committed_metadata.version != spec.metadata.version
            or committed_metadata.command_name != spec.metadata.command_name
            or committed_metadata.project_path != spec.metadata.project_path
            or committed_metadata.distribution_path != spec.metadata.distribution_path
            or committed_metadata.python_requirement != spec.metadata.python_requirement
            or committed_metadata.runtime_python != spec.metadata.runtime_python
        ):
            raise ValueError("Committed project metadata does not match the author declaration.")
        lock_path = _nearest_lockfile(tree, selected)
        committed_lock_digest = _sha256_file(lock_path)
        _validate_workspace(tree)
        original_configuration = _project_configuration(tree)
        original_lockfiles = _project_lockfiles(tree)
        baseline_directories = {
            PurePosixPath(path.relative_to(tree).as_posix())
            for path in tree.rglob("*")
            if path.is_dir() and not path.is_symlink()
        }
        baseline_files = _baseline_output_files(tree)
        if prepare is not None:
            prepare(tree)
        _remove_generated(tree, baseline_directories, baseline_files)
        if _project_configuration(tree) != original_configuration:
            raise ValueError("Preparation modified committed project/workspace configuration.")
        if _project_lockfiles(tree) != original_lockfiles:
            raise ValueError("Preparation modified a committed uv.lock.")
        _validate_workspace(tree)
        entries: list[tuple[str, bytes]] = []
        for current, directories, filenames in os.walk(tree, topdown=True, followlinks=False):
            parent = Path(current)
            for name in tuple(directories):
                if (parent / name).is_symlink():
                    raise ValueError("Project snapshot contains a generated directory link.")
            directories.sort()
            filenames.sort()
            for name in filenames:
                path = parent / name
                assert_no_links(path)
                if not path.is_file():
                    raise ValueError("Project snapshot contains a non-regular file.")
                entries.append((path.relative_to(tree).as_posix(), path.read_bytes()))
        archive_bytes = _deterministic_zip(entries)
        with destination.open("xb") as output:
            created_output = True
            output.write(archive_bytes)
        source = ProjectSnapshot(
            hashlib.sha256(archive_bytes).hexdigest(),
            committed_lock_digest,
            commit,
            str(project_path),
        )
        return PreparedProject(destination, source)
    except BaseException:
        if created_output:
            destination.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage)
