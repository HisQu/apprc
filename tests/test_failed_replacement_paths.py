"""Active configuration remains available while a replacement is recoverable."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import apprc as rc
from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    begin_operation,
    fail_operation,
    plan_install,
)


def test_config_read_and_write_use_active_runtime_after_failed_replacement(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    resource_root = tmp_path / "resources"
    environment = {"HOME": str(home), "XDG_DATA_HOME": str(home / "data")}
    app = rc.AppRC(
        app_id="replacement-fixture",
        paths=rc.Paths(config=True),
        user_dotenv=rc.UserDotenv(),
        layout=Layout.single_root(resource_root),
    )

    @app.config("settings", prefix="REPLACEMENT_")
    class Settings(rc.Config):
        value: str = rc.field("REPLACEMENT_VALUE", default="fallback")

    identity = InstallationIdentity(
        "replacement-fixture",
        "replacement-fixture",
        "replacement_fixture",
        None,
        ("replacement-fixture",),
    )
    placement = InstallationPlacement(
        layout=Layout.single_root(resource_root),
        config_dir=resource_root / "config",
        capabilities=frozenset({"config"}),
    )
    source = ProjectSnapshot("a" * 64, "b" * 64, "c" * 40)
    active = RuntimeSlot(
        uuid4(),
        source,
        RuntimeSelection("3.14"),
        version="1.0",
        python_version="3.14.1",
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="replacement-fixture",
        generation_id=uuid4(),
        support_version="0.31.0",
        status="ready",
        placement=placement,
        active_runtime=active,
    )
    directory = app.installation(environment=environment).directory
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    initial_manager = app.manage(environment=environment)
    initial_manager.setup()
    initial_manager.apply_edit(
        initial_manager.plan_update("value", "old-runtime", scope="user")
    )
    stale_manager = app.manage(environment=environment)
    stale_write = stale_manager.plan_update(
        "value", "stale-writer", scope="user"
    )

    replacement = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("d" * 64, "e" * 64, "f" * 40),
        RuntimeSelection("3.14"),
    )
    plan = plan_install(
        identity,
        replacement,
        placement,
        inspection=inspect_installation(directory, app_id=identity.app_id),
        command_name="replacement-fixture",
    )
    pending = begin_operation(plan)
    assert pending.revision is not None
    failed = fail_operation(
        directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        diagnostic=InstallationDiagnostic(
            "sync-failed",
            "Replacement sync failed.",
            "Repair the saved candidate.",
        ),
    )
    assert failed.record is not None
    assert failed.record.active_runtime == active
    assert failed.record.operation is not None
    assert failed.record.operation.intended is not None

    current_manager = app.manage(environment=environment)
    assert current_manager.resolve().build(Settings).value == "old-runtime"
    current_manager.apply_edit(
        current_manager.plan_update(
            "value", "saved-after-failure", scope="user"
        )
    )
    assert (
        current_manager.resolve().build(Settings).value == "saved-after-failure"
    )
    with pytest.raises(InstallationError):
        stale_manager.apply_edit(stale_write)
    assert (
        current_manager.resolve().build(Settings).value == "saved-after-failure"
    )
    inspection = inspect_installation(directory, app_id=identity.app_id)
    assert inspection.record is not None
    assert inspection.record.active_runtime == active
