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
    PACKAGE_CHANGED = "package_changed"
    RESOURCES_READY = "resources_ready"
    SUPPORT_READY = "support_ready"
    REGISTRATION_READY = "registration_ready"
    PACKAGE_REMOVED = "package_removed"
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


@dataclass(frozen=True, slots=True)
class OwnedOutput:
    """One expressly owned support file, shortcut or HKCU registration."""

    kind: Literal["support", "shortcut", "hkcu"]
    path: str
    digest: str | None


@dataclass(frozen=True, slots=True)
class StagedSupportOutput:
    """Verified new support bytes awaiting promotion over a legacy controller."""

    source: Path
    destination: Path
    digest: str

    def __post_init__(self) -> None:
        """Require exact absolute addresses and a SHA-256 staged revision."""
        import re

        if (
            not self.source.is_absolute()
            or not self.destination.is_absolute()
            or re.fullmatch(r"[0-9a-f]{64}", self.digest) is None
        ):
            raise InstallationError(
                "Staged support requires absolute paths and a SHA-256 digest."
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
class InstallationSource:
    """Exact package acquisition inputs; credentials must not be persisted."""

    kind: Literal["editable", "release-sdist", "wheel", "index"]
    requirement: str
    version: str | None = None
    digest: str | None = None
    runtime_requirements: tuple[str, ...] = ()
    runtime_overrides: tuple[str, ...] = ()

    def matches_observation(self, observed: InstallationSource) -> bool:
        """Match durable inputs while allowing only verified archive digest proof.

        :param observed: Source identity captured from an installed package.
        :return: Whether it retains these inputs and adds no unsupported proof.
        """
        if any(
            digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in (self.digest, observed.digest)
        ):
            return False
        if (
            self.kind != observed.kind
            or self.requirement != observed.requirement
            or self.version != observed.version
            or self.runtime_requirements != observed.runtime_requirements
            or self.runtime_overrides != observed.runtime_overrides
        ):
            return False
        if self.digest is not None:
            return self.digest == observed.digest
        if observed.digest is None:
            return True
        return (
            self.kind == "index"
            and re.fullmatch(
                r"git\+https://github\.com/[^/@]+/[^/@]+@"
                r"[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
                self.requirement,
            )
            is not None
            and re.fullmatch(r"[0-9a-f]{64}", observed.digest) is not None
        )


@dataclass(frozen=True, slots=True)
class UvToolTarget:
    """Selected absolute uv backend address, independent of ambient PATH."""

    executable: Path
    tool_dir: Path
    bin_dir: Path

    def __post_init__(self) -> None:
        """Do not let a later CWD change reinterpret a backend target."""
        if not all(
            path.is_absolute()
            for path in (self.executable, self.tool_dir, self.bin_dir)
        ):
            raise InstallationError("uv backend paths must be absolute.")


@dataclass(frozen=True, slots=True)
class InstallationTarget:
    """Intended acquisition inputs, deliberately distinct from live observation."""

    identity: InstallationIdentity
    source: InstallationSource
    placement: InstallationPlacement
    backend: UvToolTarget


@dataclass(frozen=True, slots=True)
class InstalledSnapshot:
    """Observed live package state, not a prediction of backend success."""

    identity: InstallationIdentity
    version: str
    source: InstallationSource
    placement: InstallationPlacement
    backend: UvToolTarget
    prefix: Path
    interpreter: Path
    commands: tuple[Path, ...]
    owned_outputs: tuple[OwnedOutput, ...] = ()
    distribution_record_digest: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed observed RECORD fingerprints at construction."""
        if (
            self.distribution_record_digest is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.distribution_record_digest)
            is None
        ):
            raise InstallationError(
                "Installed distribution RECORD digest must be SHA-256."
            )


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """A revision-checked owned target; unknown descendants are not implied."""

    path: Path
    kind: Literal["file", "directory"]
    revision: str | None
    resource: ResourceKind | None = None


@dataclass(frozen=True, slots=True)
class LegacyRunnable:
    """One verified legacy launcher/helper and its inert retirement address."""

    path: Path
    inert_path: Path
    revision: str


@dataclass(frozen=True, slots=True)
class LegacyMigrationEvidence:
    """Distribution-validated receipt facts needed for a resumable cutover."""

    receipt: InventoryEntry
    distribution: str
    command: str
    version: str
    source_ref: str
    backend: UvToolTarget
    python: Path
    runnables: tuple[LegacyRunnable, ...]

    def __post_init__(self) -> None:
        """Reject incomplete or overlapping legacy evidence before persistence."""
        import re

        if (
            self.receipt.kind != "file"
            or self.receipt.revision is None
            or not self.receipt.path.is_absolute()
            or not self.python.is_absolute()
        ):
            raise InstallationError(
                "Legacy receipt evidence must use exact absolute file identities."
            )
        if not all(
            (self.distribution, self.command, self.version, self.source_ref)
        ):
            raise InstallationError(
                "Legacy receipt identity fields must be nonempty."
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.receipt.revision) is None or any(
            not item.path.is_absolute()
            or not item.inert_path.is_absolute()
            or re.fullmatch(r"[0-9a-f]{64}", item.revision) is None
            for item in self.runnables
        ):
            raise InstallationError(
                "Legacy file evidence requires exact SHA-256 revisions."
            )
        sources = [self.receipt.path, *(item.path for item in self.runnables)]
        inert = [item.inert_path for item in self.runnables]
        if (
            len(set(sources)) != len(sources)
            or len(set(inert)) != len(inert)
            or set(sources) & set(inert)
            or any(item.path == item.inert_path for item in self.runnables)
        ):
            raise InstallationError(
                "Legacy runnable evidence has unsafe or duplicate paths."
            )


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
    """Durable cutover progress; old receipts are never an alternate authority."""

    source: Path
    destination: Path
    phase: Literal["staged", "retired", "moved", "activated"]
    inventory: MigrationInventory
    retired_files: tuple[Path, ...] = ()
    legacy: LegacyMigrationEvidence | None = None
    staged_support: tuple[StagedSupportOutput, ...] = ()
    operation_id: UUID | None = None
    cleanup_complete: bool = False

    def __post_init__(self) -> None:
        """Keep the durable phase consistent with cleanup authority."""
        if self.legacy is None:
            if self.staged_support or self.retired_files:
                raise InstallationError(
                    "Legacy-only migration fields lack receipt evidence."
                )
            if self.phase == "activated" and not self.cleanup_complete:
                raise InstallationError(
                    "Non-legacy migration activation is already complete."
                )
        else:
            if not self.staged_support:
                raise InstallationError(
                    "Legacy migration requires staged replacement support."
                )
            expected = tuple(item.inert_path for item in self.legacy.runnables)
            if self.phase != "activated":
                if self.retired_files or self.cleanup_complete:
                    raise InstallationError(
                        "Retired-file cleanup requires activated migration."
                    )
            elif self.cleanup_complete:
                if self.retired_files:
                    raise InstallationError(
                        "Completed migration cleanup cannot retain retired paths."
                    )
            elif self.retired_files != expected:
                raise InstallationError(
                    "Activated migration must retain its exact cleanup inventory."
                )


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
    """The single durable authority for one managed application generation."""

    schema_version: Literal[1]
    app_id: str
    generation_id: UUID
    support_version: str
    placement: InstallationPlacement
    status: Literal["provisional", "ready", "incomplete", "removed-retained"]
    last_successful: InstalledSnapshot | None = None
    current: InstalledSnapshot | None = None
    operation: InstallationOperation | None = None
    owned_outputs: tuple[OwnedOutput, ...] = ()
    migration: InstallationMigration | None = None

    def __post_init__(self) -> None:
        """Reject authority that contradicts its declared lifecycle status."""
        if self.status == "ready" and (
            self.current is None or self.operation is not None
        ):
            raise InstallationError(
                "Ready installation requires current state and no operation."
            )
        if self.status == "removed-retained" and (
            self.current is not None or self.operation is not None
        ):
            raise InstallationError(
                "Removed installation cannot claim a live package or operation."
            )
        for snapshot in (self.current, self.last_successful):
            if snapshot is not None and snapshot.identity.app_id != self.app_id:
                raise InstallationError(
                    "Installed snapshot belongs to another application."
                )


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
    observed: InstalledSnapshot | None = None
    legacy: LegacyMigrationEvidence | None = None
    staged_support: tuple[StagedSupportOutput, ...] = ()


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
