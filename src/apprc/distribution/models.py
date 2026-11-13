"""Portable author declarations and immutable native product bindings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from apprc.definition.installation import (
    InstallationHooks,
    InstallationIdentity,
    ProjectSnapshot,
    RuntimeSelection,
)
from apprc.definition.paths import Layout, Paths
from apprc.user_files.installation.codec import _decode, _encode, _pairs


def relative_destination(value: str | PurePosixPath) -> PurePosixPath:
    """Validate a portable normalized relative file address."""
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or any(character in str(value) for character in '\\\x00<>:"|?*')
        or str(path) != str(value)
    ):
        raise ValueError(f"Unsafe relative artifact path: {value!s}.")
    return path


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    """Packaging identity and explicit repository-relative project routing."""

    project_root: Path
    identity: InstallationIdentity
    version: str
    project_path: PurePosixPath = PurePosixPath(".")
    distribution_path: PurePosixPath = PurePosixPath("src/app_distr")
    command_name: str | None = None
    python_requirement: str = ">=3.12"
    runtime_python: str | None = None

    @property
    def runtime_python_requirement(self) -> str:
        """Return the declared package compatibility and runtime selection."""
        if self.runtime_python is None:
            return self.python_requirement
        return f"{self.python_requirement},=={self.runtime_python}.*"


@dataclass(frozen=True, slots=True)
class AppCapabilities:
    """Registered capabilities, without resolving application settings."""

    paths: Paths = Paths()
    user_dotenv: bool = False
    workspaces: bool = False
    workspace_registry: bool = False


@dataclass(frozen=True, slots=True)
class DistributionSpec:
    """Author composition used to build a committed native product."""

    metadata: ProjectMetadata
    capabilities: AppCapabilities = AppCapabilities()
    display_name: str | None = None
    layout: Layout = Layout()
    bootstrap_env_prefix: str = "APPRC"
    maintenance_group_name: str = "app"
    hooks: InstallationHooks = InstallationHooks()
    launch_enabled: bool = False

    def __post_init__(self) -> None:
        """Reject ambiguous commands and invalid portable declaration values."""
        if self.metadata.command_name not in {
            None,
            *self.metadata.identity.commands,
        }:
            raise ValueError(
                "command-name must name one declared console command."
            )
        if (
            self.metadata.command_name is None
            and len(self.metadata.identity.commands) != 1
        ):
            raise ValueError("Multiple console commands require command-name.")
        if not self.metadata.version:
            raise ValueError("A native product requires an explicit version.")
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.bootstrap_env_prefix)
            is None
        ):
            raise ValueError(
                "bootstrap_env_prefix must be an environment variable prefix."
            )
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]*", self.maintenance_group_name
            )
            is None
        ):
            raise ValueError(
                "maintenance_group_name must be one CLI command name."
            )
        if self.layout.root is not None:
            raise ValueError(
                "Native products cannot embed an author's absolute layout root."
            )


@dataclass(frozen=True, slots=True)
class NativeBinding:
    """Immutable portable product declaration, never installation authority."""

    identity: InstallationIdentity
    command_name: str
    display_name: str
    version: str
    source: ProjectSnapshot
    selection: RuntimeSelection
    capabilities: AppCapabilities
    layout: Layout
    bootstrap_env_prefix: str
    maintenance_group_name: str = "app"
    hooks: InstallationHooks = InstallationHooks()
    launch_enabled: bool = False

    def __post_init__(self) -> None:
        """Reject inconsistent product identity and author-specific locations."""
        if self.command_name not in self.identity.commands:
            raise ValueError("Native command must belong to its distribution.")
        if not self.display_name or not self.version:
            raise ValueError(
                "Native display name and version must be nonempty."
            )
        if self.layout.root is not None:
            raise ValueError(
                "Native bindings cannot contain author filesystem locations."
            )
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.bootstrap_env_prefix)
            is None
        ):
            raise ValueError("Invalid native bootstrap environment prefix.")
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]*", self.maintenance_group_name
            )
            is None
        ):
            raise ValueError("Invalid native maintenance command.")


def encode_native_binding(binding: NativeBinding) -> bytes:
    """Encode a binding using the SDK's deterministic dataclass codec."""
    return (
        json.dumps(_encode(binding), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def decode_native_binding(data: bytes) -> NativeBinding:
    """Decode only the exact SDK binding schema, rejecting unknown fields."""
    return cast(
        NativeBinding,
        _decode(
            json.loads(data, object_pairs_hook=_pairs), NativeBinding, "binding"
        ),
    )


@dataclass(frozen=True, slots=True)
class Artifact:
    """Exact output bytes at a repository-relative destination."""

    destination: PurePosixPath
    content: bytes
    executable: bool
    project_root: Path

    def __post_init__(self) -> None:
        """Keep publication inside the selected author repository."""
        relative_destination(self.destination)
        if not self.project_root.is_absolute():
            raise ValueError("Artifact project root must be absolute.")
