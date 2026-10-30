"""Application-bound installation inspection and explicit pending setup."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.installation import (
    CleanupInventory,
    InitializationReport,
    InstalledSnapshot,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationSource,
    InventoryEntry,
    LegacyMigrationEvidence,
    MigrationInventory,
    MigrationPlan,
    OperationContext,
    OperationPlan,
    OperationStep,
    UvToolTarget,
    StagedSupportOutput,
    InstallPlan,
    UninstallCommit,
    UninstallPlan,
)
from apprc.definition.paths import AppPaths, Layout, PathKind, ResourceKind
from apprc.user_files.installation.discovery import (
    inspect_installation,
    installation_directory,
    native_user_directories,
)


def _legacy_state_root(
    evidence: LegacyMigrationEvidence,
    environment: Mapping[str, str],
    *,
    platform: str,
) -> Path:
    """Resolve only the documented native Buildben receipt address.

    :param evidence: Strict receipt identities and known helper paths.
    :param environment: Detached native address inputs.
    :param platform: Host platform name used for the legacy address rule.
    :return: The one recognized legacy installation directory.
    """
    distribution = re.sub(r"[-_.]+", "-", evidence.distribution).lower()
    if not distribution or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in distribution
    ):
        raise InstallationError("Legacy distribution identity is invalid.")
    if platform == "win32":
        base_value = environment.get("LOCALAPPDATA")
        if not base_value:
            raise InstallationError(
                "Captured LOCALAPPDATA is required for legacy migration."
            )
        base = Path(base_value)
    else:
        base_value = environment.get("XDG_STATE_HOME")
        if base_value:
            base = Path(base_value)
        else:
            home = environment.get("HOME")
            if not home:
                raise InstallationError(
                    "Captured HOME is required for legacy migration."
                )
            base = Path(home) / ".local" / "state"
    root = base / distribution / "installation"
    if evidence.receipt.path != root / "receipt.json":
        raise InstallationError(
            "Legacy receipt is outside its fixed distribution state address."
        )
    known = {
        "lifecycle.py",
        "uninstall.sh",
        "uninstall.cmd",
        "uninstall.ps1",
        "prepare-powershell-windows.cmd",
    }
    if any(
        item.path.parent != root
        or item.path.name not in known
        or item.inert_path.parent != root
        or item.inert_path.name != f".retired-{item.path.name}"
        for item in evidence.runnables
    ):
        raise InstallationError(
            "Legacy controller inventory contains an unknown path."
        )
    return root


class InstallationManager:
    """Capture discovery without resolving business settings or writing files."""

    def __init__(
        self,
        spec: AppConfigSpec,
        *,
        environment: Mapping[str, str] | None = None,
        directory: Path | None = None,
    ) -> None:
        """Detach host discovery from later process environment changes.

        :param spec: Host declaration, never imported dependency identity.
        :param environment: Explicit discovery inputs or current process snapshot.
        :param directory: Explicit adjacent address for a saved recovery helper;
            ordinary applications use native discovery through AppRC.installation.
        """
        self.spec = spec
        self.environment = MappingProxyType(
            dict(os.environ if environment is None else environment)
        )
        if directory is not None and not directory.is_absolute():
            raise InstallationError(
                "Explicit installation address must be absolute."
            )
        self.directory = (
            directory
            if directory is not None
            else installation_directory(
                spec.app_id, environment=self.environment
            )
        )

    def inspect(self) -> InstallationInspection:
        """Inspect captured authority without settings resolution or mutation.

        :return: Structured state, including invalid or pending authority.
        """
        return inspect_installation(self.directory, app_id=self.spec.app_id)

    def plan_install(
        self,
        identity: InstallationIdentity,
        source: InstallationSource,
        placement: InstallationPlacement,
        backend: UvToolTarget,
    ) -> InstallPlan:
        """Bind an install/replace plan to this captured installation address."""
        from apprc.user_files.installation.operations import plan_install

        return plan_install(
            identity, source, placement, backend, inspection=self.inspect()
        )

    def plan_uninstall(
        self,
        *,
        inventory: CleanupInventory,
        categories: frozenset[ResourceKind] = frozenset(),
        complete: bool = False,
        forget_retained: bool = False,
    ) -> UninstallPlan:
        """Bind exact cleanup inventory to the current saved generation."""
        inspection = self.inspect()
        record = inspection.require_usable()
        if record is None or inspection.revision is None:
            raise InstallationError(
                "Uninstall requires a saved installation record."
            )
        from apprc.user_files.installation.operations import plan_uninstall

        return plan_uninstall(
            record,
            directory=self.directory,
            revision=inspection.revision,
            categories=categories,
            complete=complete,
            forget_retained=forget_retained,
            inventory=inventory,
        )

    def begin_operation(self, plan: OperationPlan) -> InstallationInspection:
        """Publish one validated plan under this manager's captured namespace."""
        if isinstance(plan, InstallPlan):
            app_id = plan.target.identity.app_id
        else:
            app_id = plan.app_id
        if plan.directory != self.directory or app_id != self.spec.app_id:
            raise InstallationError(
                "Operation plan belongs to another application address."
            )
        from apprc.user_files.installation.operations import begin_operation

        return begin_operation(plan)

    def record_step(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
        step: OperationStep,
        observed: InstalledSnapshot | None = None,
    ) -> InstallationInspection:
        """Persist a truthful lifecycle checkpoint at the captured address."""
        from apprc.user_files.installation.operations import record_step

        return record_step(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
            step=step,
            observed=observed,
        )

    def commit_install(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
        observed: InstalledSnapshot,
    ) -> InstallationInspection:
        """Activate verified package state under this manager's address."""
        from apprc.user_files.installation.operations import commit_installation

        return commit_installation(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
            observed=observed,
        )

    def fail_operation(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
        diagnostic: InstallationDiagnostic,
    ) -> InstallationInspection:
        """Retain durable recovery state for a failed lifecycle action."""
        from apprc.user_files.installation.operations import fail_operation

        return fail_operation(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
            diagnostic=diagnostic,
        )

    def commit_uninstall(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
    ) -> UninstallCommit:
        """Commit retained state or irreversible authority retirement."""
        from apprc.user_files.installation.operations import commit_uninstall

        return commit_uninstall(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
        )

    def plan_repair(
        self,
        identity: InstallationIdentity,
        source: InstallationSource,
        placement: InstallationPlacement,
        backend: UvToolTarget,
    ) -> InstallPlan:
        """Plan repair against saved identity and preserve its generation.

        :param identity: Exact saved application/package/import/command identities.
        :param source: Exact source facts from the saved installation.
        :param placement: Exact recorded placement; repair cannot relocate resources.
        :param backend: Recorded uv executable and tool/bin addresses.
        :return: Repair plan bound to this manager's inspected authority.
        """
        from apprc.user_files.installation.operations import plan_repair

        return plan_repair(
            identity, source, placement, backend, inspection=self.inspect()
        )

    def plan_migration(
        self,
        placement: InstallationPlacement,
        *,
        inventory: MigrationInventory,
        quiescent: bool = False,
    ) -> MigrationPlan:
        """Plan an explicit migration without changing files.

        :param placement: Intended absolute resource locations.
        :param inventory: Exact revision-checked source/destination mapping.
        :param quiescent: Whether legacy consumers have stopped.
        :return: A plan bound to this manager's captured installation address.
        """
        from apprc.user_files.installation.migration import (
            validate_migration_inventory,
        )
        from apprc.user_files.installation.operations import plan_migration

        validate_migration_inventory(inventory, directory=self.directory)
        return plan_migration(
            self.inspect(), placement, inventory=inventory, quiescent=quiescent
        )

    def preview_migration(self) -> MigrationPlan:
        """Plan Linux native appdata marker migration without scanning ownership.

        Only the known AppRC ownership marker is recognized by the generic
        manager. Other children require an explicit project/provider inventory.

        :return: Read-only exact migration plan for a marker-only legacy root.
        """
        from apprc.user_files.app_home.ownership import inspect_ownership
        from apprc.user_files.app_home.writes import file_revision

        if not self.spec.paths.appdata:
            raise InstallationError(
                "This application has no appdata migration capability."
            )
        if sys.platform in {"win32", "darwin"}:
            raise InstallationError(
                "Native parent appdata migration applies only on Linux."
            )
        _, parent, _, _, _ = native_user_directories(
            self.spec.app_id, environment=self.environment
        )
        destination = parent / "appdata"
        marker = parent / ".apprc-owner.json"
        if inspect_ownership(parent, self.spec.app_id, "appdata") != "owned":
            raise InstallationError(
                "No valid legacy AppRC appdata marker requires migration."
            )
        installation_container = parent / "installation"
        installation_inspection = inspect_installation(
            installation_container, app_id=self.spec.app_id
        )
        known_installation = (
            installation_inspection.status in {"ready", "removed-retained"}
            and installation_inspection.record is not None
        )
        unknown = tuple(
            path
            for path in parent.iterdir()
            if path not in {marker, destination}
            and not (known_installation and path == installation_container)
        )
        if destination.exists():
            raise InstallationError(
                "Native appdata destination already exists; inspect the conflict."
            )
        entry = InventoryEntry(marker, "file", file_revision(marker), "appdata")
        inventory = MigrationInventory(
            parent, destination, (entry,), (destination / marker.name,), unknown
        )
        if unknown:
            raise InstallationError(
                "Unknown native appdata payload requires a project-owned MigrationInventory."
            )
        inspection = self.inspect()
        record = inspection.require_usable()
        if record is not None:
            placement = replace(record.placement, appdata_dir=destination)
        else:
            config, _, cache, state, logs = native_user_directories(
                self.spec.app_id, environment=self.environment
            )
            capabilities: tuple[tuple[ResourceKind, bool], ...] = (
                ("config", self.spec.paths.config),
                ("appdata", True),
                ("cache", self.spec.paths.cache),
                ("state", self.spec.paths.state),
            )
            placement = InstallationPlacement(
                Layout.native(),
                config_dir=config if self.spec.paths.config else None,
                appdata_dir=destination,
                cache_dir=cache if self.spec.paths.cache else None,
                state_dir=state if self.spec.paths.state else None,
                logs_dir=logs if self.spec.paths.state else None,
                capabilities=frozenset(
                    kind for kind, enabled in capabilities if enabled
                ),
            )
        return self.plan_migration(placement, inventory=inventory)

    def migrate(
        self,
        plan: MigrationPlan,
        *,
        quiescent: bool,
    ) -> InstallationInspection:
        """Execute a preview only after explicit old-consumer quiescence.

        :param plan: Previously inspected exact inventory and revision.
        :param quiescent: Explicit confirmation that old consumers are stopped.
        :return: Updated installation authority.
        """
        from apprc.user_files.installation.migration import execute_migration

        if not quiescent:
            raise InstallationError(
                "Stop legacy consumers before executing migration."
            )
        if plan.directory != self.directory or plan.app_id != self.spec.app_id:
            raise InstallationError(
                "Migration plan belongs to another installation."
            )
        return execute_migration(replace(plan, quiescent=True))

    def resume_migration(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
    ) -> InstallationInspection:
        """Resume the matching migration at this captured host address.

        :param operation_id: Pending migration identifier.
        :param expected_revision: Exact current authority revision.
        :return: Updated installation authority.
        """
        from apprc.user_files.installation.migration import (
            _validate_legacy_namespace,
            resume_migration,
        )

        inspection = self.inspect()
        record = inspection.record
        if (
            record is not None
            and record.migration is not None
            and record.migration.operation_id == operation_id
            and record.migration.legacy is not None
        ):
            evidence = record.migration.legacy
            _legacy_state_root(
                evidence, self.environment, platform=sys.platform
            )
            _validate_legacy_namespace(
                evidence,
                record.owned_outputs,
                staged_support=record.migration.staged_support,
                directory=self.directory,
            )
        return resume_migration(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
        )

    def migrate_legacy(
        self,
        evidence: LegacyMigrationEvidence,
        placement: InstallationPlacement,
        *,
        inventory: MigrationInventory,
        observed: InstalledSnapshot,
        quiescent: bool,
        staged_support: tuple[StagedSupportOutput, ...],
        generation_id: UUID,
    ) -> InstallationInspection:
        """Cut over validated Buildben authority after replacement support is ready.

        :param evidence: Distribution-validated receipt and known controller files.
        :param placement: Explicit chosen resource placement, never inferred from receipt flags.
        :param inventory: Exact app/provider-owned resource movement, if any.
        :param observed: Live verified package identity and backend state.
        :param quiescent: Explicit confirmation that legacy consumers are stopped.
        :param staged_support: Exact replacement support staged in the generation namespace.
        :param generation_id: Generation UUID used by the staged support directory.
        :return: Activated authority or an incomplete record that can be resumed.
        """
        from apprc.user_files.installation.migration import (
            _validate_legacy_namespace,
            execute_migration,
        )
        from apprc.user_files.installation.operations import plan_migration

        if not quiescent:
            raise InstallationError(
                "Stop legacy consumers before executing migration."
            )
        _validate_legacy_namespace(
            evidence,
            observed.owned_outputs,
            staged_support=staged_support,
            directory=self.directory,
        )
        plan = plan_migration(
            self.inspect(),
            placement,
            inventory=inventory,
            quiescent=True,
            observed=observed,
            legacy=evidence,
            staged_support=staged_support,
            generation_id=generation_id,
        )
        return execute_migration(plan)

    def initialize(self, *, context: OperationContext) -> InitializationReport:
        """Initialize declared resources under explicit pending authorization.

        The controller retains its operation lock while this target-environment
        probe takes resource locks. Reacquiring that lock here would deadlock
        the controller and probe across processes.

        :param context: Pending operation and intended placement from controller.
        :return: Actual initialized locations, never inferred fallback paths.
        """
        from apprc.user_files.app_home.ownership import ensure_owned_path
        from apprc.user_files.installation.validation import validate_snapshot

        if context.directory != self.directory:
            raise InstallationError(
                "Operation context addresses a different installation."
            )
        inspection = self.inspect()
        validate_snapshot(
            inspection.snapshot, app_id=self.spec.app_id, context=context
        )
        placement = context.placement
        declared_capabilities: tuple[tuple[ResourceKind, bool], ...] = (
            ("config", self.spec.paths.config),
            ("appdata", self.spec.paths.appdata),
            ("cache", self.spec.paths.cache),
            ("state", self.spec.paths.state),
        )
        declared = {
            kind for kind, enabled in declared_capabilities if enabled
        }
        if declared != placement.capabilities:
            raise InstallationError(
                "Installed declaration differs from intended capabilities."
            )
        paths = AppPaths(
            layout=placement.layout,
            source="installation",
            config_dir=placement.config_dir if self.spec.paths.config else None,
            appdata_dir=placement.appdata_dir
            if self.spec.paths.appdata
            else None,
            cache_dir=placement.cache_dir if self.spec.paths.cache else None,
            state_dir=placement.state_dir if self.spec.paths.state else None,
            logs_dir=placement.logs_dir if self.spec.paths.state else None,
            installation=inspection.snapshot,
        )
        initialized_resources: tuple[tuple[PathKind, bool], ...] = (
            ("config", self.spec.paths.config),
            ("appdata", self.spec.paths.appdata),
            ("cache", self.spec.paths.cache),
            ("state", self.spec.paths.state),
            ("logs", self.spec.paths.state),
        )
        initialized = tuple(
            ensure_owned_path(self.spec, paths, kind, context=context)
            for kind, enabled in initialized_resources
            if enabled
        )
        return InitializationReport(initialized)
