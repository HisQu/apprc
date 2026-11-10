# ruff: noqa: F401
"""Composable lifecycle primitives; application repositories choose their order."""

from apprc.definition.installation import (
    CleanupInventory as CleanupInventory,
)
from apprc.definition.installation import (
    InstallationIdentity as InstallationIdentity,
)
from apprc.definition.installation import (
    InstallationPlacement as InstallationPlacement,
)
from apprc.definition.installation import (
    InstallationSource as InstallationSource,
)
from apprc.definition.installation import (
    InstalledSnapshot as InstalledSnapshot,
)
from apprc.definition.installation import (
    InstallPlan as InstallPlan,
)
from apprc.definition.installation import (
    MigrationInventory as MigrationInventory,
)
from apprc.definition.installation import (
    MigrationPlan as MigrationPlan,
)
from apprc.definition.installation import (
    OperationContext as OperationContext,
)
from apprc.definition.installation import (
    OperationPlan as OperationPlan,
)
from apprc.definition.installation import (
    OperationStep as OperationStep,
)
from apprc.definition.installation import (
    UninstallCommit as UninstallCommit,
)
from apprc.definition.installation import (
    UninstallPlan as UninstallPlan,
)
from apprc.definition.installation import (
    UvToolTarget as UvToolTarget,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource as PreparedSource,
)
from apprc.distribution.runtime.acquisition import (
    SourceSelection as SourceSelection,
)
from apprc.distribution.runtime.acquisition import (
    installation_source as installation_source,
)
from apprc.distribution.runtime.acquisition import (
    parse_source_arguments as parse_source_arguments,
)
from apprc.distribution.runtime.acquisition import (
    prepare_source as prepare_source,
)
from apprc.distribution.runtime.controllers import (
    UninstallHandoff as UninstallHandoff,
)
from apprc.distribution.runtime.controllers import (
    UninstallPreparation as UninstallPreparation,
)
from apprc.distribution.runtime.controllers import (
    default_cleanup_inventory as default_cleanup_inventory,
)
from apprc.distribution.runtime.controllers import (
    inspect_saved as inspect_saved,
)
from apprc.distribution.runtime.controllers import (
    parse_uninstall_handoff_args as parse_uninstall_handoff_args,
)
from apprc.distribution.runtime.controllers import (
    prepare_uninstall as prepare_uninstall,
)
from apprc.distribution.runtime.controllers import (
    repair_saved as repair_saved,
)
from apprc.distribution.runtime.controllers import (
    stage_uninstall as stage_uninstall,
)
from apprc.distribution.runtime.controllers import (
    start_uninstall_handoff as start_uninstall_handoff,
)
from apprc.distribution.runtime.controllers import (
    uninstall_saved as uninstall_saved,
)
from apprc.distribution.runtime.installation import (
    bind_install_support as bind_install_support,
)
from apprc.distribution.runtime.installation import (
    install_application as install_application,
)
from apprc.distribution.runtime.installation import (
    install_prepared_application as install_prepared_application,
)
from apprc.user_files.installation.migration import (
    execute_migration as execute_migration,
)
from apprc.user_files.installation.migration import (
    resume_migration as resume_migration,
)
from apprc.user_files.installation.operations import (
    begin_operation as begin_operation,
)
from apprc.user_files.installation.operations import (
    commit_installation as commit_installation,
)
from apprc.user_files.installation.operations import (
    commit_uninstall as commit_uninstall,
)
from apprc.user_files.installation.operations import (
    fail_operation as fail_operation,
)
from apprc.user_files.installation.operations import (
    plan_install as plan_install,
)
from apprc.user_files.installation.operations import (
    plan_migration as plan_migration,
)
from apprc.user_files.installation.operations import (
    plan_repair as plan_repair,
)
from apprc.user_files.installation.operations import (
    record_step as record_step,
)
