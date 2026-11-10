"""Explicit Linux parent-to-child migration never invents an empty store."""

from dataclasses import replace
from pathlib import Path

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import (
    InstallationError,
    InstallationPlacement,
    InventoryEntry,
    MigrationInventory,
)
from apprc.definition.paths import Layout
from apprc.user_files.app_home.writes import file_revision, managed_lock_path
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
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
    with pytest.raises(InstallationError):
        app.paths(environment=environment)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(placement, inventory=inventory)
    assert not manager.directory.exists()
    with pytest.raises(InstallationError):
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
    # > Payload and marker moves retain locks on their actual resource roots.
    assert managed_lock_path(inventory.source_root).is_file()
    assert managed_lock_path(inventory.destination_root).is_file()


def test_resume_rejects_persisted_out_of_root_inventory_before_any_move(
    tmp_path: Path,
) -> None:
    app, environment, inventory, placement = _fixture(tmp_path)
    manager = app.installation(environment=environment)
    plan = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )
    pending = begin_operation(plan)
    assert pending.record is not None
    assert pending.record.migration is not None
    assert pending.revision is not None

    protected = tmp_path / "protected-user-file.txt"
    protected.write_bytes(b"unrelated user work")
    unsafe_inventory = replace(
        inventory,
        entries=inventory.entries
        + (
            InventoryEntry(
                protected,
                "file",
                file_revision(protected),
                "appdata",
            ),
        ),
        destinations=inventory.destinations
        + (inventory.destination_root / protected.name,),
    )
    unsafe_record = replace(
        pending.record,
        migration=replace(
            pending.record.migration,
            inventory=unsafe_inventory,
        ),
    )
    with installation_lock(manager.directory):
        revision = write_record(
            manager.directory,
            unsafe_record,
            expected_revision=pending.revision,
        )
    persisted = manager.inspect()
    assert persisted.record == unsafe_record
    assert persisted.revision == revision

    with pytest.raises(InstallationError):
        resume_migration(
            manager.directory,
            operation_id=plan.operation_id,
            expected_revision=revision,
        )

    assert inventory.entries[0].path.read_bytes() == b"persistent user work"
    assert protected.read_bytes() == b"unrelated user work"
    assert (
        file_revision(inventory.entries[1].path)
        == inventory.entries[1].revision
    )
    assert not inventory.destinations[0].exists()
    assert not unsafe_inventory.destinations[-1].exists()


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
        2,
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
