"""Immutable installation authority shared by runtime and standalone support.

Records contain identities and owned locations, never configuration values or
credentials. Inspection is deliberately separate from ordinary path resolution
so recovery remains available when the authority cannot be used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from apprc.definition.paths import Layout, ResourceKind


class InstallationError(ValueError):
    """Installation authority is unsafe, stale, incomplete or incompatible."""


class OperationStep(StrEnum):
    """Durable checkpoints; repository-specific actions remain ordinary calls."""

    SOURCE_VERIFIED = "source_verified"
    PROVIDER_CLEANUP = "provider_cleanup"
    RUNTIME_PREPARED = "runtime_prepared"
    RUNTIME_VALIDATED = "runtime_validated"
    RESOURCES_READY = "resources_ready"
    SUPPORT_READY = "support_ready"
    REGISTRATION_READY = "registration_ready"
    MIGRATION_HOOK_COMPLETED = "migration_hook_completed"
    RUNTIME_REMOVED = "runtime_removed"
    DATA_REMOVED = "data_removed"


@dataclass(frozen=True, slots=True)
class InstallationDiagnostic:
    """A machine-readable problem and actionable recovery guidance."""

    code: str
    message: str
    recovery: str


@dataclass(frozen=True, slots=True)
class InstallationIdentity:
    """Keep application, packaging, import and entry-point identities distinct."""

    app_id: str
    distribution: str
    import_package: str
    apprc_reference: str | None
    commands: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject invalid package, import and console-script identities."""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.app_id) is None:
            raise InstallationError("Application ID is invalid.")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.distribution) is None:
            raise InstallationError("Distribution identity is invalid.")
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", self.import_package, flags=re.ASCII) is None:
            raise InstallationError("Import package identity is invalid.")
        if (
            not self.commands
            or len(set(self.commands)) != len(self.commands)
            or any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", command) is None for command in self.commands)
        ):
            raise InstallationError("Console command identities must be valid and unique.")
        if self.apprc_reference is not None:
            module, separator, attribute = self.apprc_reference.partition(":")
            if (
                not separator
                or not attribute
                or not all(part.isidentifier() for part in module.split("."))
                or not attribute.isidentifier()
            ):
                raise InstallationError("AppRC reference must be a module:attribute.")


@dataclass(frozen=True, slots=True)
class OwnedOutput:
    """One expressly owned support file, shortcut or HKCU registration."""

    kind: Literal["support", "shortcut", "hkcu", "command"]
    path: str
    digest: str | None

    def __post_init__(self) -> None:
        if self.kind == "support":
            from pathlib import PurePosixPath, PureWindowsPath

            path = PurePosixPath(self.path)
            if (
                not path.parts
                or path.is_absolute()
                or PureWindowsPath(self.path).drive
                or ".." in path.parts
                or any(character in self.path for character in '\\\x00<>:"|?*')
                or str(path) != self.path
            ):
                raise InstallationError("Owned support path must be portable and relative.")
        if (
            not path.is_absolute()
            or ".." in path.parts
            or str(path) != self.path
            or "\x00" in self.path
        ):
            raise InstallationError(
                "Owned command path must be normalized and absolute."
            )


@dataclass(frozen=True, slots=True)
class RetiredResource:
    """An earlier location retained until explicitly migrated or removed."""

    kind: ResourceKind
    path: Path


@dataclass(frozen=True, slots=True)
class InstallationPlacement:
    """Committed absolute locations, including native paths captured at install."""

    layout: Layout
    config_dir: Path | None = None
    appdata_dir: Path | None = None
    cache_dir: Path | None = None
    state_dir: Path | None = None
    logs_dir: Path | None = None
    capabilities: frozenset[ResourceKind] = frozenset()
    retired: tuple[RetiredResource, ...] = ()

    def __post_init__(self) -> None:
        """Reject incomplete or contradictory resource declarations."""
        for kind in ("config", "appdata", "cache", "state"):
            path = {
                "config": self.config_dir,
                "appdata": self.appdata_dir,
                "cache": self.cache_dir,
                "state": self.state_dir,
            }[kind]
            if (path is not None) != (kind in self.capabilities):
                raise InstallationError(
                    f"Placement capability mismatch: {kind}."
                )
            if path is not None and not path.is_absolute():
                raise InstallationError(
                    f"Placement path must be absolute: {kind}."
                )
        if self.logs_dir is not None and (
            self.state_dir is None or not self.logs_dir.is_absolute()
        ):
            raise InstallationError(
                "Logs require an enabled state and an absolute path."
            )
        for resource in self.retired:
            if not resource.path.is_absolute():
                raise InstallationError(
                    "Retired resource path must be absolute."
                )


@dataclass(frozen=True, slots=True)
class InstallationHooks:
    """Importable application callbacks captured with one runtime."""

    initialize: str | None = None
    inventory: str | None = None
    cleanup: str | None = None
    migrate: str | None = None

    def __post_init__(self) -> None:
        for reference in (
            self.initialize, self.inventory, self.cleanup, self.migrate
        ):
            if reference is not None and re.fullmatch(
                r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*",
                reference,
                flags=re.ASCII,
            ) is None:
                raise InstallationError("Hooks must be module:function references.")


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    """Immutable project archive and lock identity."""

    digest: str
    lock_digest: str
    commit: str
    project_path: str = "."

    def __post_init__(self) -> None:
        from pathlib import PurePosixPath

        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None
               for value in (self.digest, self.lock_digest)):
            raise InstallationError("Project and lock digests must be lowercase SHA-256.")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.commit) is None:
            raise InstallationError("Project commit must be a full lowercase Git commit ID.")
        path = PurePosixPath(self.project_path)
        if (
            not self.project_path or path.is_absolute()
            or ".." in path.parts
            or any(character in self.project_path for character in '\\\x00<>:"|?*')
            or str(path) != self.project_path
        ):
            raise InstallationError("Project path must be normalized and relative.")


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    """Locked project interpreter and explicitly selected extras."""

    python: str
    extras: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.python.strip() or "\x00" in self.python:
            raise InstallationError("Runtime Python selection is empty or invalid.")
        if len(set(self.extras)) != len(self.extras) or any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", extra) is None
            for extra in self.extras
        ):
            raise InstallationError("Runtime extras must be valid and unique.")


@dataclass(frozen=True, slots=True)
class RuntimeSlot:
    """One immutable managed candidate or observed active runtime."""

    slot_id: UUID
    source: ProjectSnapshot
    selection: RuntimeSelection
    version: str | None = None
    python_version: str | None = None
    hooks: InstallationHooks = InstallationHooks()

    def __post_init__(self) -> None:
        if any(value is not None and not value.strip()
               for value in (self.version, self.python_version)):
            raise InstallationError("Runtime observations cannot be empty.")


@dataclass(frozen=True, slots=True)
class EditableCheckout:
    """Developer-owned checkout and existing environment, never deletion roots."""

    project: Path
    environment: Path
    hooks: InstallationHooks = InstallationHooks()

    def __post_init__(self) -> None:
        paths = (self.project, self.environment)
        if any(not path.is_absolute() for path in paths):
            raise InstallationError("Editable checkout paths must be absolute.")
        if any(
            ".." in path.parts or "\x00" in str(path)
            for path in paths
        ):
            raise InstallationError(
                "Editable checkout paths must be normalized and valid."
            )


@dataclass(frozen=True, slots=True)
class InstallationTarget:
    """Exact pending identity, placement and runtime candidate."""

    identity: InstallationIdentity
    placement: InstallationPlacement
    runtime: RuntimeSlot | EditableCheckout


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """A revision-checked owned target; unknown descendants are not implied."""

    path: Path
    kind: Literal["file", "directory"]
    revision: str | None
    resource: ResourceKind | None = None


@dataclass(frozen=True, slots=True)
class CleanupInventory:
    """Exact removable entries and known targets that cannot yet be removed."""

    entries: tuple[InventoryEntry, ...] = ()
    retained: tuple[InventoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationInventory:
    """Explicit source/destination mapping supplied by the owning repository."""

    source_root: Path
    destination_root: Path
    entries: tuple[InventoryEntry, ...] = ()
    destinations: tuple[Path, ...] = ()
    unknown: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        """Each enumerated source needs exactly one destination."""
        if len(self.entries) != len(self.destinations):
            raise InstallationError(
                "Migration source/destination counts differ."
            )
        if (
            not self.source_root.is_absolute()
            or not self.destination_root.is_absolute()
        ):
            raise InstallationError("Migration roots must be absolute.")


@dataclass(frozen=True, slots=True)
class InstallationMigration:
    """Durable progress for an explicit resource placement migration."""

    source: Path
    destination: Path
    phase: Literal["staged", "activated"]
    inventory: MigrationInventory


@dataclass(frozen=True, slots=True)
class InstallationOperation:
    """Validated pending work, recorded before destructive mutation."""

    operation_id: UUID
    kind: Literal["install", "replace", "repair", "migrate", "uninstall"]
    phase: Literal["pending", "running", "failed"]
    intended: InstallationTarget | None
    placement: InstallationPlacement
    steps: tuple[OperationStep, ...] = ()
    diagnostic: InstallationDiagnostic | None = None
    categories: frozenset[ResourceKind] = frozenset()
    complete: bool = False
    forget_retained: bool = False
    inventory: CleanupInventory = CleanupInventory()


@dataclass(frozen=True, slots=True)
class InstallationRecord:
    """The single durable schema-3 authority for one application generation."""

    schema_version: Literal[3]
    identity: InstallationIdentity
    command_name: str
    generation_id: UUID
    support_version: str
    placement: InstallationPlacement
    status: Literal["provisional", "ready", "incomplete", "removed-retained"]
    active_runtime: RuntimeSlot | EditableCheckout | None = None
    retiring_runtime_ids: tuple[UUID, ...] = ()
    operation: InstallationOperation | None = None
    owned_outputs: tuple[OwnedOutput, ...] = ()
    migration: InstallationMigration | None = None
    def __post_init__(self) -> None:
        """Keep active authority distinct from unfinished replacement work."""
        if not self.identity.app_id or self.command_name not in self.identity.commands:
            raise InstallationError("Installation identity or primary command is invalid.")
        if self.status == "ready" and (
            self.active_runtime is None or self.operation is not None
        ):
            raise InstallationError("Ready installation requires an active runtime and no operation.")
        if self.status == "removed-retained" and (
            self.active_runtime is not None or self.operation is not None
            or self.retiring_runtime_ids
        ):
            raise InstallationError("Removed installation cannot retain live runtime work.")
        if isinstance(self.active_runtime, RuntimeSlot) and (
            self.active_runtime.version is None
            or self.active_runtime.python_version is None
        ):
            raise InstallationError("Active managed runtime requires both observed versions.")
        ids = list(self.retiring_runtime_ids)
        if isinstance(self.active_runtime, RuntimeSlot):
            ids.append(self.active_runtime.slot_id)
        if self.operation is not None and self.operation.intended is not None:
            target = self.operation.intended
            if target.identity != self.identity or target.placement != self.operation.placement:
                raise InstallationError("Pending target differs from its authority.")
            if isinstance(target.runtime, RuntimeSlot):
                if (target.runtime.version is None) != (target.runtime.python_version is None):
                    raise InstallationError("Pending runtime observations must be both absent or both present.")
                ids.append(target.runtime.slot_id)
        if len(ids) != len(set(ids)):
            raise InstallationError("Runtime slot IDs must be unique.")



@dataclass(frozen=True, slots=True)
class InstallationSnapshot:
    """Captured discovery address/revision, not a purgeable data capability."""

    directory: Path
    revision: str | None
    generation_id: UUID | None
    diagnostics: tuple[InstallationDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class InstallationInspection:
    """Read-only discriminated result, including malformed on-disk records."""

    status: Literal[
        "missing",
        "invalid",
        "provisional",
        "ready",
        "incomplete",
        "removed-retained",
    ]
    directory: Path
    revision: str | None
    app_id: str
    record: InstallationRecord | None = None
    diagnostics: tuple[InstallationDiagnostic, ...] = ()

    @property
    def snapshot(self) -> InstallationSnapshot:
        """Capture the namespace identity for subsequent resource operations."""
        return InstallationSnapshot(
            self.directory,
            self.revision,
            self.record.generation_id if self.record is not None else None,
            self.diagnostics,
        )

    def require_usable(self) -> InstallationRecord | None:
        """Return usable placement or fail without silently choosing a store."""
        if self.status == "incomplete" and (
            self.record is not None
            and self.record.active_runtime is not None
            and self.record.operation is not None
            and self.record.operation.kind in {"replace", "repair"}
        ):
            return self.record
        if self.status not in {"missing", "ready", "removed-retained"}:
            detail = "; ".join(item.message for item in self.diagnostics)
            raise InstallationError(
                detail
                or f"Installation is {self.status}; inspect and repair it."
            )
        return self.record


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Explicit authority for a provider running inside one pending operation."""

    directory: Path
    operation_id: UUID
    generation_id: UUID
    placement: InstallationPlacement


@dataclass(frozen=True, slots=True)
class InitializationReport:
    """Resources initialized by an authorized installed declaration probe."""

    paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Read-only acquisition decision with compare-and-replace preconditions."""

    directory: Path
    expected_revision: str | None
    expected_generation: UUID | None
    target: InstallationTarget
    operation_id: UUID
    generation_id: UUID
    kind: Literal["install", "replace", "repair"] = "install"
    command_name: str = ""


@dataclass(frozen=True, slots=True)
class UninstallPlan:
    """Exact retained/removed targets confirmed before program removal."""

    directory: Path
    expected_revision: str
    expected_generation: UUID
    app_id: str
    operation_id: UUID
    placement: InstallationPlacement
    inventory: CleanupInventory
    categories: frozenset[ResourceKind] = frozenset()
    complete: bool = False
    forget_retained: bool = False


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Explicit revision-checked ownership-preserving placement cutover."""

    directory: Path
    expected_revision: str | None
    expected_generation: UUID | None
    app_id: str
    operation_id: UUID
    generation_id: UUID
    placement: InstallationPlacement
    inventory: MigrationInventory
    quiescent: bool
    identity: InstallationIdentity | None = None
    command_name: str | None = None


OperationPlan = InstallPlan | UninstallPlan | MigrationPlan


@dataclass(frozen=True, slots=True)
class UninstallCommit:
    """Irreversible retirement or reconnectable retained authority."""

    kind: Literal["retained", "retired"]
    directory: Path
    generation_id: UUID
    inspection: InstallationInspection | None = None


@dataclass(frozen=True, slots=True)
class InstallationWriteAuthority:
    """Host identity and captured generation attached to a managed edit."""

    app_id: str
    snapshot: InstallationSnapshot
    context: OperationContext | None = None


@dataclass(frozen=True, slots=True)
class InstallationRetirement:
    """Old authority is gone; container cleanup can safely leave residue."""

    generation_id: UUID
    directory: Path
    container: Literal["removed", "occupied", "residue"]
    diagnostic: str | None = None
