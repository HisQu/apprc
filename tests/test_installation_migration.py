"""Explicit Linux parent-to-child migration never invents an empty store."""

from pathlib import Path

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import (
    InstallationError,
    InstallationPlacement,
    InstallationRecord,
    InventoryEntry,
    MigrationInventory,
)
from apprc.definition.paths import Layout
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.migration import (
    execute_migration,
    resume_migration,
)
from apprc.user_files.installation.operations import begin_operation


def _fixture(
    tmp_path: Path,
) -> tuple[AppRC, dict[str, str], MigrationInventory, InstallationPlacement]:
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    app = AppRC(app_id="migration-fixture", paths=Paths(appdata=True))
    root = tmp_path / "data" / app.schema.app_id
    root.mkdir(parents=True)
    marker = root / ".apprc-owner.json"
    marker.write_text(
        '{"schema_version":1,"app_id":"migration-fixture","category":"appdata"}\n'
    )
    payload = root / "database.sqlite"
    payload.write_bytes(b"persistent user work")
    destination = root / "appdata"
    inventory = MigrationInventory(
        root,
        destination,
        tuple(
            InventoryEntry(path, "file", file_revision(path), "appdata")
            for path in (payload, marker)
        ),
        (destination / payload.name, destination / marker.name),
    )
    placement = InstallationPlacement(
        Layout.native(),
        appdata_dir=destination,
        capabilities=frozenset({"appdata"}),
    )
    return app, environment, inventory, placement


def test_legacy_parent_needs_explicit_inventory_and_quiescence(
    tmp_path: Path,
) -> None:
    app, environment, inventory, placement = _fixture(tmp_path)
    with pytest.raises(
        InstallationError, match="explicit installation migrate"
    ):
        app.paths(environment=environment)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(placement, inventory=inventory)
    assert not manager.directory.exists()
    with pytest.raises(InstallationError, match="Stop legacy consumers"):
        execute_migration(plan)
    assert (
        inventory.source_root / "database.sqlite"
    ).read_bytes() == b"persistent user work"
    approved = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )
    result = execute_migration(approved)
    assert result.status == "removed-retained"
    assert (
        app.paths(environment=environment).appdata_dir
        == inventory.destination_root
    )
    assert (
        inventory.destination_root / "database.sqlite"
    ).read_bytes() == b"persistent user work"
    assert not (inventory.source_root / ".apprc-owner.json").exists()


def test_resume_matches_moved_file_and_preserves_unknown_content(
    tmp_path: Path,
) -> None:
    app, environment, inventory, placement = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )
    pending = begin_operation(plan)
    inventory.destination_root.mkdir()
    inventory.entries[0].path.rename(inventory.destinations[0])
    unknown = inventory.source_root / "user-owned.txt"
    unknown.write_text("leave this alone")
    assert pending.revision is not None
    resumed = resume_migration(
        manager.directory,
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
    )
    assert resumed.status == "removed-retained"
    assert unknown.read_text() == "leave this alone"
    assert inventory.destinations[0].read_bytes() == b"persistent user work"


def test_destination_conflict_keeps_incomplete_authority_and_source(
    tmp_path: Path,
) -> None:
    app, environment, inventory, placement = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )
    inventory.destination_root.mkdir()
    inventory.destinations[0].write_bytes(b"newer user work")
    with pytest.raises(InstallationError, match="occupied"):
        execute_migration(plan)
    inspection = manager.inspect()
    assert inspection.status == "incomplete"
    assert inspection.record is not None
    assert inspection.record.operation is not None
    assert inspection.record.operation.diagnostic is not None
    assert inventory.entries[0].path.read_bytes() == b"persistent user work"
    assert inventory.destinations[0].read_bytes() == b"newer user work"


def test_migration_plan_rejects_resource_roots_overlapping_authority(
    tmp_path: Path,
) -> None:
    app, environment, inventory, _ = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    placement = InstallationPlacement(
        Layout.single_root(manager.directory),
        appdata_dir=manager.directory / "appdata",
        capabilities=frozenset({"appdata"}),
    )

    with pytest.raises(InstallationError, match="overlaps"):
        manager.plan_migration(placement, inventory=inventory, quiescent=True)

    assert not manager.directory.exists()


@pytest.mark.parametrize(
    ("source_name", "timing"),
    [
        ("database.sqlite", "before"),
        ("database.sqlite", "after"),
        (".apprc-owner.json", "before"),
        (".apprc-owner.json", "after"),
    ],
)
def test_linux_migration_resumes_at_each_payload_and_marker_move_boundary(
    source_name: str,
    timing: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, environment, inventory, placement = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )
    source = inventory.source_root / source_name
    original_rename = Path.rename
    interrupted = False

    def interrupt_move(path: Path, destination: Path) -> Path:
        nonlocal interrupted
        if path == source and timing == "before" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated interruption before resource move")
        result = original_rename(path, destination)
        if path == source and timing == "after" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated interruption after resource move")
        return result

    monkeypatch.setattr(Path, "rename", interrupt_move)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        manager.migrate(plan, quiescent=True)
    monkeypatch.setattr(Path, "rename", original_rename)
    pending = manager.inspect()
    assert pending.status == "incomplete"
    assert pending.record is not None and pending.record.operation is not None
    assert pending.revision is not None
    unknown = inventory.source_root / "newer-user-file.txt"
    unknown.write_text("preserve this newer file", encoding="utf-8")

    resumed = manager.resume_migration(
        operation_id=pending.record.operation.operation_id,
        expected_revision=pending.revision,
    )

    assert resumed.status == "removed-retained"
    assert inventory.destination_root.joinpath(
        "database.sqlite"
    ).read_bytes() == (b"persistent user work")
    assert inventory.destination_root.joinpath(".apprc-owner.json").is_file()
    assert unknown.read_text(encoding="utf-8") == "preserve this newer file"


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
@pytest.mark.parametrize(
    "interruption",
    [
        "controller-before",
        "controller-after",
        "controller2-before",
        "controller2-after",
        "support-before",
        "support-after",
        "receipt-before",
        "receipt-after",
        "activation-before",
        "activation-after",
        "cleanup-before",
        "cleanup-after",
        "cleanup2-before",
        "cleanup2-after",
    ],
)
def test_legacy_receipt_cutover_resumes_at_every_authority_boundary(
    platform: str,
    interruption: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from apprc.definition.installation import (
        InstallationIdentity,
        InstallationSource,
        InstalledSnapshot,
        LegacyMigrationEvidence,
        LegacyRunnable,
        OwnedOutput,
        StagedSupportOutput,
        UvToolTarget,
    )
    from apprc.user_files.installation import migration as migration_module

    import sys

    monkeypatch.setattr(sys, "platform", platform)
    if platform == "win32":
        local = tmp_path / "local"
        environment = {
            "USERPROFILE": str(tmp_path),
            "LOCALAPPDATA": str(local),
            "APPDATA": str(tmp_path / "roaming"),
        }
        legacy_root = local / "legacy-project" / "installation"
    else:
        environment = {
            "HOME": str(tmp_path),
            "XDG_STATE_HOME": str(tmp_path / "state"),
        }
        if platform == "linux":
            environment["XDG_DATA_HOME"] = str(tmp_path / "data")
        legacy_root = tmp_path / "state" / "legacy-project" / "installation"
    app = AppRC(app_id="legacy-project")
    manager = app.installation(environment=environment)
    create_private_directory_if_missing(legacy_root)
    receipt = legacy_root / "receipt.json"
    receipt.write_bytes(b"validated legacy receipt")
    controller = legacy_root / "lifecycle.py"
    controller.write_bytes(b"saved legacy controller")
    inert_controller = legacy_root / ".retired-lifecycle.py"
    second_controller = legacy_root / "uninstall.sh"
    second_controller.write_bytes(b"second saved legacy controller")
    inert_second_controller = legacy_root / ".retired-uninstall.sh"
    backend = UvToolTarget(
        tmp_path / "uv", tmp_path / "tools", tmp_path / "tool-bin"
    )
    placement = InstallationPlacement(Layout.native())
    evidence = LegacyMigrationEvidence(
        InventoryEntry(receipt, "file", file_revision(receipt)),
        "legacy-project",
        "legacy-project",
        "1.0.0",
        "source-ref",
        backend,
        tmp_path / "base-python",
        (
            LegacyRunnable(
                controller, inert_controller, file_revision(controller) or ""
            ),
            LegacyRunnable(
                second_controller,
                inert_second_controller,
                file_revision(second_controller) or "",
            ),
        ),
    )
    generation_id = uuid4()
    support = manager.directory / "uninstall.sh"
    staged_support_path = (
        manager.directory
        / "migration-staged"
        / str(generation_id)
        / "uninstall.sh"
    )
    create_private_directory_if_missing(manager.directory)
    create_private_directory_if_missing(staged_support_path.parent)
    staged_support_path.write_bytes(b"validated replacement support")
    support_output = OwnedOutput(
        "support", support.name, file_revision(staged_support_path)
    )
    observed = InstalledSnapshot(
        InstallationIdentity(
            "legacy-project",
            "legacy-project",
            "legacy_project",
            None,
            ("legacy-project",),
        ),
        "1.0.0",
        InstallationSource("editable", str(tmp_path / "project")),
        placement,
        backend,
        tmp_path / "prefix",
        tmp_path / "target-python",
        (tmp_path / "tool-bin" / "legacy-project",),
        (support_output,),
    )
    inventory = MigrationInventory(legacy_root, manager.directory)
    original_rename = Path.rename
    original_unlink = Path.unlink
    original_write_record = migration_module.write_record
    interrupted = False

    def raise_interruption() -> None:
        nonlocal interrupted
        interrupted = True
        raise RuntimeError(f"simulated interruption at {interruption}")

    def interrupt_rename(path: Path, target: Path) -> Path:
        kind = (
            "controller"
            if path == controller
            else "controller2"
            if path == second_controller
            else "support"
            if path == staged_support_path
            else None
        )
        if kind is not None and interruption == f"{kind}-before":
            raise_interruption()
        result = original_rename(path, target)
        if kind is not None and interruption == f"{kind}-after":
            raise_interruption()
        return result

    def interrupt_unlink(path: Path, missing_ok: bool = False) -> None:
        kind = (
            "receipt"
            if path == receipt
            else "cleanup"
            if path == inert_controller
            else "cleanup2"
            if path == inert_second_controller
            else None
        )
        if kind is not None and interruption == f"{kind}-before":
            raise_interruption()
        original_unlink(path, missing_ok=missing_ok)
        if kind is not None and interruption == f"{kind}-after":
            raise_interruption()

    def interrupt_activation_write(
        directory: Path,
        record: InstallationRecord,
        *,
        expected_revision: str | None,
    ) -> str:
        activated = (
            record.operation is None
            and record.migration is not None
            and record.migration.phase == "activated"
            and not record.migration.cleanup_complete
        )
        when = interruption.removeprefix("activation-")
        if (
            activated
            and interruption.startswith("activation-")
            and when == "before"
        ):
            raise_interruption()
        revision = original_write_record(
            directory, record, expected_revision=expected_revision
        )
        if activated and interruption == "activation-after":
            raise_interruption()
        return revision

    monkeypatch.setattr(Path, "rename", interrupt_rename)
    monkeypatch.setattr(Path, "unlink", interrupt_unlink)
    monkeypatch.setattr(
        migration_module, "write_record", interrupt_activation_write
    )
    with pytest.raises(RuntimeError, match="simulated interruption"):
        manager.migrate_legacy(
            evidence,
            placement,
            inventory=inventory,
            observed=observed,
            quiescent=True,
            staged_support=(
                StagedSupportOutput(
                    staged_support_path, support, support_output.digest or ""
                ),
            ),
            generation_id=generation_id,
        )
    pending = manager.inspect()
    assert pending.revision is not None and pending.record is not None
    assert pending.record.migration is not None
    assert pending.record.migration.operation_id is not None
    postactivation = interruption in {
        "activation-after",
        "cleanup-before",
        "cleanup-after",
        "cleanup2-before",
        "cleanup2-after",
    }
    assert pending.status == ("ready" if postactivation else "incomplete")
    assert pending.record.migration is not None
    if postactivation:
        assert pending.record.operation is None
        assert not pending.record.migration.cleanup_complete
    else:
        assert pending.record.operation is not None
    if interruption == "controller-before":
        assert controller.exists() and not inert_controller.exists()
    elif interruption == "controller-after":
        assert not controller.exists() and inert_controller.exists()
    if interruption == "controller2-before":
        assert (
            second_controller.exists() and not inert_second_controller.exists()
        )
    elif interruption == "controller2-after":
        assert (
            not second_controller.exists() and inert_second_controller.exists()
        )
    if interruption == "support-before":
        assert staged_support_path.exists() and not support.exists()
    elif interruption == "support-after":
        assert not staged_support_path.exists()
        assert support.read_bytes() == b"validated replacement support"
    if interruption == "receipt-before":
        assert receipt.exists()
    elif interruption in {
        "receipt-after",
        "activation-before",
        "activation-after",
        "cleanup-before",
        "cleanup-after",
        "cleanup2-before",
        "cleanup2-after",
    }:
        assert not receipt.exists()
    if interruption == "cleanup-after":
        assert not inert_controller.exists()
    if interruption == "cleanup2-after":
        assert not inert_second_controller.exists()

    monkeypatch.setattr(Path, "rename", original_rename)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    monkeypatch.setattr(migration_module, "write_record", original_write_record)
    unknown = legacy_root / "newer-user-file.txt"
    unknown.write_bytes(b"preserve newer content")
    assert pending.record is not None and pending.record.migration is not None
    assert pending.record.migration.operation_id is not None
    assert pending.revision is not None
    with pytest.raises(InstallationError, match="Unknown"):
        manager.resume_migration(
            operation_id=pending.record.migration.operation_id,
            expected_revision=pending.revision,
        )
    assert unknown.read_bytes() == b"preserve newer content"
    unknown.unlink()
    pending = manager.inspect()
    assert pending.record is not None and pending.record.migration is not None
    assert pending.revision is not None
    operation_id = pending.record.migration.operation_id
    assert operation_id is not None
    result = manager.resume_migration(
        operation_id=operation_id, expected_revision=pending.revision
    )

    assert result.record is not None and result.record.migration is not None
    assert result.record.migration.cleanup_complete
    assert result.record.migration.retired_files == ()
    assert result.status == "ready"
    assert not receipt.exists()
    assert not controller.exists()
    assert not inert_controller.exists()
    # > In-place cutover keeps new support at the old canonical filename.
    if second_controller != support:
        assert not second_controller.exists()
    assert not inert_second_controller.exists()
    assert support.read_bytes() == b"validated replacement support"
    assert not staged_support_path.parent.exists()


def test_appdata_preview_migration_is_read_only_until_explicit_execution(
    tmp_path: Path,
) -> None:
    app, environment, inventory, _ = _fixture(tmp_path)
    inventory.entries[0].path.unlink()
    manager = app.installation(environment=environment)

    plan = manager.preview_migration()
    assert not manager.directory.exists()
    assert not inventory.destination_root.exists()
    result = manager.migrate(plan, quiescent=True)
    assert result.status == "removed-retained"
    assert inventory.destination_root.joinpath(".apprc-owner.json").is_file()
    assert not (inventory.source_root / ".apprc-owner.json").exists()


def test_appdata_preview_allows_only_a_valid_known_sibling_installation(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from apprc.definition.installation import InstallationRecord
    from apprc.user_files.installation.coordination import (
        installation_lock,
        write_record,
    )

    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "data"),
    }
    app = AppRC(app_id="migration-fixture", paths=Paths(appdata=True))
    manager = app.installation(environment=environment)
    parent = tmp_path / "data" / app.schema.app_id
    parent.mkdir(parents=True)
    marker = parent / ".apprc-owner.json"
    marker.write_text(
        '{"schema_version":1,"app_id":"migration-fixture","category":"appdata"}\n',
        encoding="utf-8",
    )
    record = InstallationRecord(
        1,
        app.schema.app_id,
        uuid4(),
        "0.31.0",
        InstallationPlacement(
            Layout.native(),
            appdata_dir=parent / "appdata",
            capabilities=frozenset({"appdata"}),
        ),
        "removed-retained",
    )
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)

    before = manager.inspect()
    plan = manager.preview_migration()

    assert plan.inventory.unknown == ()
    assert manager.inspect() == before
    assert not (parent / "appdata").exists()


def test_appdata_preview_does_not_ignore_an_invalid_sibling_installation(
    tmp_path: Path,
) -> None:
    app, environment, inventory, _ = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    inventory.entries[0].path.unlink()
    (inventory.source_root / "installation").mkdir()

    with pytest.raises(
        InstallationError, match="Unknown native appdata payload"
    ):
        manager.preview_migration()
    assert not (manager.directory / "installation.json").exists()
    assert not (manager.directory / "locks").exists()
    assert not inventory.destination_root.exists()
