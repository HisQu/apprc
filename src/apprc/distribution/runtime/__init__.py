"""Composable lifecycle primitives; application repositories choose their order."""

from apprc.definition.installation import (
    CleanupInventory as CleanupInventory,
    InstallationIdentity as InstallationIdentity,
    InstallationPlacement as InstallationPlacement,
    InstallationSource as InstallationSource,
    InstalledSnapshot as InstalledSnapshot,
    InstallPlan as InstallPlan,
    MigrationInventory as MigrationInventory,
    MigrationPlan as MigrationPlan,
    OperationContext as OperationContext,
    OperationPlan as OperationPlan,
    OperationStep as OperationStep,
    UninstallCommit as UninstallCommit,
    UninstallPlan as UninstallPlan,
    UvToolTarget as UvToolTarget,
    StagedSupportOutput as StagedSupportOutput,
    LegacyMigrationEvidence as LegacyMigrationEvidence,
    LegacyRunnable as LegacyRunnable,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource as PreparedSource,
    SourceSelection as SourceSelection,
    installation_source as installation_source,
    parse_source_arguments as parse_source_arguments,
    prepare_source as prepare_source,
)
from apprc.distribution.runtime.controllers import (
    UninstallHandoff as UninstallHandoff,
    UninstallPreparation as UninstallPreparation,
    inspect_saved as inspect_saved,
    parse_uninstall_handoff_args as parse_uninstall_handoff_args,
    prepare_uninstall as prepare_uninstall,
    repair_saved as repair_saved,
    stage_uninstall as stage_uninstall,
    start_uninstall_handoff as start_uninstall_handoff,
    uninstall_saved as uninstall_saved,
)
from apprc.distribution.runtime.installation import (
    bind_install_support as bind_install_support,
    install_application as install_application,
    install_prepared_application as install_prepared_application,
)
from apprc.distribution.runtime.legacy import (
    LegacyReceiptInspection as LegacyReceiptInspection,
    inspect_legacy_receipt as inspect_legacy_receipt,
    migrate_legacy_receipt as migrate_legacy_receipt,
    stage_legacy_support as stage_legacy_support,
)
from apprc.user_files.installation.migration import (
    execute_migration as execute_migration,
    resume_migration as resume_migration,
)
from apprc.user_files.installation.operations import (
    begin_operation as begin_operation,
    commit_installation as commit_installation,
    commit_uninstall as commit_uninstall,
    fail_operation as fail_operation,
    plan_install as plan_install,
    plan_migration as plan_migration,
    plan_repair as plan_repair,
    record_step as record_step,
)
