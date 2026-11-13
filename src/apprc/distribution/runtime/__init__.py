# ruff: noqa: F401
"""Runtime installation, application bridge, and lease primitives."""

from apprc.definition.installation import (
    CleanupInventory as CleanupInventory,
    EditableCheckout as EditableCheckout,
    InstallationHooks as InstallationHooks,
    InstallationIdentity as InstallationIdentity,
    InstallationPlacement as InstallationPlacement,
    InstallPlan as InstallPlan,
    MigrationPlan as MigrationPlan,
    OperationContext as OperationContext,
    OperationStep as OperationStep,
    ProjectSnapshot as ProjectSnapshot,
    RuntimeSelection as RuntimeSelection,
    RuntimeSlot as RuntimeSlot,
    UninstallPlan as UninstallPlan,
)
from apprc.distribution.runtime._leases import (
    RuntimeLease as RuntimeLease,
    acquire_runtime_lease as acquire_runtime_lease,
    acquire_runtime_lease_locked as acquire_runtime_lease_locked,
    inherited_runtime_lease_options as inherited_runtime_lease_options,
    try_acquire_runtime_quiescence as try_acquire_runtime_quiescence,
    try_retire_runtime_slot as try_retire_runtime_slot,
)
from apprc.distribution.runtime.acquisition import (
    materialize_project_snapshot as materialize_project_snapshot,
)
from apprc.distribution.runtime.backend import (
    runtime_command as runtime_command,
    runtime_environment as runtime_environment,
    runtime_interpreter as runtime_interpreter,
    sync_runtime_slot as sync_runtime_slot,
)
from apprc.distribution.runtime.installation import (
    install_application as install_application,
    offer_configuration_setup as offer_configuration_setup,
    register_editable_application as register_editable_application,
)
from apprc.distribution.runtime.probe import (
    application_bridge as application_bridge,
    probe_runtime as probe_runtime,
)
from apprc.user_files.installation.operations import (
    begin_operation as begin_operation,
    commit_installation as commit_installation,
    commit_uninstall as commit_uninstall,
    fail_operation as fail_operation,
    plan_install as plan_install,
    plan_migration as plan_migration,
    plan_repair as plan_repair,
    record_runtime_retired as record_runtime_retired,
    record_step as record_step,
)

from apprc.distribution.runtime.controllers import (
    UninstallHandoff as UninstallHandoff,
    UninstallPreparation as UninstallPreparation,
    prepare_uninstall as prepare_uninstall,
    stage_uninstall as stage_uninstall,
    start_uninstall_handoff as start_uninstall_handoff,
)
