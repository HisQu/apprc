"""Composable lifecycle primitives; application repositories choose their order."""

# ruff: noqa: F401
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
    PreparedSource,
    SourceSelection,
    installation_source,
    parse_source_arguments,
    prepare_source,
)
from apprc.distribution.runtime.controllers import (
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
    bind_install_support,
    install_application,
    install_prepared_application,
)
from apprc.distribution.runtime.legacy import (
    LegacyReceiptInspection,
    inspect_legacy_receipt,
    migrate_legacy_receipt,
    stage_legacy_support,
)
from apprc.user_files.installation.migration import (
    execute_migration,
    resume_migration,
)
from apprc.user_files.installation.operations import (
    begin_operation,
    commit_installation,
    commit_uninstall,
    fail_operation,
    plan_install,
    plan_migration,
    plan_repair,
    record_step,
)
