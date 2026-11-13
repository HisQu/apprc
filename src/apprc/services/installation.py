"""Application-bound installation inspection and explicit pending setup."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.installation import (
    CleanupInventory,
    EditableCheckout,
    InitializationReport,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    InstallPlan,
    InventoryEntry,
    MigrationInventory,
    MigrationPlan,
    OperationContext,
    OperationPlan,
    OperationStep,
    OwnedOutput,
    RuntimeSlot,
    UninstallCommit,
    UninstallPlan,
)
from apprc.definition.paths import AppPaths, Layout, PathKind, ResourceKind
from apprc.user_files.installation.discovery import (
    inspect_installation,
    installation_directory,
    native_user_directories,
)


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
        runtime: RuntimeSlot | EditableCheckout,
        placement: InstallationPlacement,
        *,
        command_name: str | None = None,
    ) -> InstallPlan:
        """Bind install/replace planning to this captured authority address."""
        from apprc.user_files.installation.operations import plan_install

        return plan_install(
            identity,
            runtime,
            placement,
            inspection=self.inspect(),
            command_name=command_name,
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
        observed: RuntimeSlot | EditableCheckout | None = None,
    ) -> InstallationInspection:
        """Persist a truthful runtime lifecycle checkpoint at this address."""
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
        observed: RuntimeSlot | EditableCheckout,
        owned_outputs: tuple[OwnedOutput, ...] | None = None,
    ) -> InstallationInspection:
        """Activate a verified runtime candidate under this manager's address."""
        from apprc.user_files.installation.operations import commit_installation

        return commit_installation(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
            observed=observed,
            owned_outputs=owned_outputs,
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

    def record_runtime_retired(
        self,
        *,
        slot_id: UUID,
        expected_revision: str,
        generation_id: UUID,
    ) -> InstallationInspection:
        """Remove one confirmed-retired managed slot from durable authority."""
        from apprc.user_files.installation.operations import record_runtime_retired

        return record_runtime_retired(
            self.directory,
            slot_id=slot_id,
            expected_revision=expected_revision,
            generation_id=generation_id,
        )

    def plan_repair(
        self,
        identity: InstallationIdentity,
        runtime: RuntimeSlot | EditableCheckout,
        placement: InstallationPlacement,
    ) -> InstallPlan:
        """Plan repair by resuming or reconstructing the exact managed runtime."""
        from apprc.user_files.installation.operations import plan_repair

        return plan_repair(
            identity, runtime, placement, inspection=self.inspect()
        )

    def plan_migration(
        self,
        placement: InstallationPlacement,
        *,
        inventory: MigrationInventory,
        quiescent: bool = False,
        identity: InstallationIdentity | None = None,
        command_name: str | None = None,
    ) -> MigrationPlan:
        """Plan an explicit migration with exact optional initial identity."""
        from apprc.user_files.installation.migration import validate_migration_inventory
        from apprc.user_files.installation.operations import plan_migration

        validate_migration_inventory(inventory, directory=self.directory)
        return plan_migration(
            self.inspect(),
            placement,
            inventory=inventory,
            quiescent=quiescent,
            identity=identity,
            command_name=command_name,
        )

    def preview_migration(
        self,
        *,
        identity: InstallationIdentity | None = None,
        command_name: str | None = None,
    ) -> MigrationPlan:
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
        return self.plan_migration(
            placement,
            inventory=inventory,
            identity=identity,
            command_name=command_name,
        )

    def migrate(
        self,
        plan: MigrationPlan,
        *,
        quiescent: bool,
        migration_hook: (
            Callable[[MigrationPlan, OperationContext], None] | None
        ) = None,
    ) -> InstallationInspection:
        """Execute a preview only after explicit old-consumer quiescence.

        :param plan: Previously inspected exact inventory and revision.
        :param quiescent: Explicit confirmation that old consumers are stopped.
        :param migration_hook: Application-owned migration callback, if required.
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
        return execute_migration(
            replace(plan, quiescent=True),
            migration_hook=migration_hook,
        )

    def resume_migration(
        self,
        *,
        operation_id: UUID,
        expected_revision: str,
        migration_hook: (
            Callable[[MigrationPlan, OperationContext], None] | None
        ) = None,
    ) -> InstallationInspection:
        """Resume the matching migration at this captured host address.

        :param operation_id: Pending migration identifier.
        :param expected_revision: Exact current authority revision.
        :param migration_hook: Application-owned callback for an uncheckpointed hook.
        :return: Updated installation authority.
        """
        from apprc.user_files.installation.migration import resume_migration

        return resume_migration(
            self.directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
            migration_hook=migration_hook,
        )

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
        declared = {kind for kind, enabled in declared_capabilities if enabled}
        if not declared.issubset(placement.capabilities):
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
