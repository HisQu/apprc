"""Explicit author inputs and deterministic generated management artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from apprc.definition.installation import InstallationIdentity
from apprc.definition.paths import Paths


def relative_destination(value: str | PurePosixPath) -> PurePosixPath:
    """Validate an archive/artifact address independently of the author's OS.

    :param value: Repository-relative POSIX spelling.
    :return: Safe normalized relative address.
    """
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or any(character in str(value) for character in '\\\x00<>:"|?*')
    ):
        raise ValueError(
            f"Artifact path must be relative without traversal: {value!s}."
        )
    return path


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    """Packaging and runtime identities plus explicit repository routing."""

    project_root: Path
    identity: InstallationIdentity
    version: str
    project_path: PurePosixPath = PurePosixPath(".")
    distribution_path: PurePosixPath = PurePosixPath("src/app_distr")
    launcher_command: str | None = None
    python_requirement: str = ">=3.12"


@dataclass(frozen=True, slots=True)
class AppCapabilities:
    """Declarations only; generation never resolves business settings."""

    paths: Paths = Paths()
    user_dotenv: bool = False
    workspaces: bool = False
    workspace_registry: bool = False


@dataclass(frozen=True, slots=True)
class DistributionSpec:
    """One explicit composition, source identity and payload format."""

    metadata: ProjectMetadata
    capabilities: AppCapabilities = AppCapabilities()
    source_mode: Literal["checkout", "release", "main", "wheel", "index"] = (
        "checkout"
    )
    payload_format: Literal["script", "zipapp"] = "script"
    repository_url: str | None = None
    release_version: str | None = None
    release_commit: str | None = None
    release_asset: str | None = None
    release_digest: str | None = None
    runtime_requirements: tuple[str, ...] = ()
    runtime_overrides: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject incomplete remote identities before emitting tracked output."""
        requirements = (*self.runtime_requirements, *self.runtime_overrides)
        if any(
            not value.strip()
            or value != value.strip()
            or "\n" in value
            or "\r" in value
            or value.startswith("-")
            for value in requirements
        ):
            raise ValueError(
                "Runtime requirements must be individual PEP 508 values."
            )
        if self.metadata.launcher_command not in {
            None,
            *self.metadata.identity.commands,
        }:
            raise ValueError(
                "launcher-command must name one declared console command."
            )
        if self.source_mode in {"release", "wheel"}:
            if (
                not self.release_version
                or not self.release_asset
                or not self.release_digest
            ):
                raise ValueError(
                    "Release sources require explicit version, asset and SHA-256."
                )
            if re.fullmatch(r"[0-9a-f]{64}", self.release_digest) is None:
                raise ValueError(
                    "Release asset digest must be lowercase SHA-256."
                )
        if self.source_mode == "release" and not self.runtime_requirements:
            raise ValueError(
                "Release sdist sources require exact runtime constraints."
            )
        if self.source_mode == "release" and (
            not self.repository_url
            or not self.release_commit
            or re.fullmatch(r"[0-9a-f]{40}", self.release_commit) is None
        ):
            raise ValueError(
                "Release mode requires repository URL and full source commit identity."
            )
        if self.source_mode == "main" and (
            not self.repository_url
            or not self.release_commit
            or re.fullmatch(r"[0-9a-f]{40}", self.release_commit) is None
        ):
            raise ValueError(
                "Remote-main mode requires one full immutable commit identity."
            )


@dataclass(frozen=True, slots=True)
class PayloadTree:
    """Explicit ordinary modules/resources; no import or source rewriting."""

    root: Path
    modules: tuple[PurePosixPath, ...]
    entry_module: str = "app_lifecycle.install"
    uninstall_entry_module: str = "app_lifecycle.uninstall"
    resources: tuple[PurePosixPath, ...] = ()

    def __post_init__(self) -> None:
        """Reject duplicate or escaping destinations before reading files."""
        seen: set[PurePosixPath] = set()
        for candidate in (*self.modules, *self.resources):
            path = relative_destination(candidate)
            if path in seen:
                raise ValueError(f"Duplicate payload destination: {path}.")
            seen.add(path)
        for entry in (self.entry_module, self.uninstall_entry_module):
            if not entry or not all(
                part.isidentifier() for part in entry.split(".")
            ):
                raise ValueError(
                    "Payload entries must be explicit Python module names."
                )
            if PurePosixPath(*entry.split(".")).with_suffix(".py") not in seen:
                raise ValueError(
                    f"Payload does not include entry module {entry}."
                )


@dataclass(frozen=True, slots=True)
class Artifact:
    """Generated bytes with repository-relative destination and output ownership.

    ``project_root`` is used only by the writer; it is never serialized into
    generated files. This lets author commands work outside the repository CWD.
    """

    destination: PurePosixPath
    content: bytes
    executable: bool
    project_root: Path

    def __post_init__(self) -> None:
        """Keep writes inside the explicitly selected author repository."""
        relative_destination(self.destination)
        if not self.project_root.is_absolute():
            raise ValueError("Artifact project root must be absolute.")
