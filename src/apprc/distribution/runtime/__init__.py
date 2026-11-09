# ruff: noqa: F401
"""Composable lifecycle primitives; application repositories choose their order."""

from apprc.definition.installation import (
    CleanupInventory,
    InstallationIdentity,
    InstallationPlacement,
    InstallationSource,
    InstalledSnapshot,
    InstallPlan,
    MigrationInventory,
    MigrationPlan,
    OperationContext,
    OperationPlan,
    OperationStep,
    UninstallCommit,
    UninstallPlan,
    UvToolTarget,
    StagedSupportOutput,
    LegacyMigrationEvidence,
    LegacyRunnable,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource as PreparedSource,
    SourceSelection as SourceSelection,
    installation_source as installation_source,
    parse_source_arguments as parse_source_arguments,
    prepare_source as prepare_source,
)
from apprc.distribution.runtime.controllers import (
    default_cleanup_inventory,
    UninstallHandoff,
    UninstallPreparation,
    inspect_saved,
    parse_uninstall_handoff_args,
    prepare_uninstall,
    repair_saved,
    stage_uninstall,
    start_uninstall_handoff,
    uninstall_saved,
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
from apprc.distribution.runtime.legacy_replacement import (
    LegacyReplacementPlan as LegacyReplacementPlan,
    execute_legacy_replacement as execute_legacy_replacement,
    is_pending_legacy_replacement as is_pending_legacy_replacement,
    plan_legacy_replacement as plan_legacy_replacement,
    resume_legacy_replacement as resume_legacy_replacement,
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
