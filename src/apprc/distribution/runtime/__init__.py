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
    UninstallHandoff,
    UninstallPreparation,
    default_cleanup_inventory,
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
