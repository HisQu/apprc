from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.installation import (
    CleanupInventory,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationSource,
    InstalledSnapshot,
    InventoryEntry,
    OperationStep,
    OwnedOutput,
    UninstallPlan,
    UvToolTarget,
)
from apprc.definition.paths import Layout, ResourceKind
from apprc.distribution.runtime import controllers
from apprc.distribution.runtime.controllers import UninstallPreparation
from apprc.interfaces.cli.runtime import InstallationInventoryProvider
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import installation_directory


def _app(
    apprc: rc.AppRC | None = None,
    *,
    installation_inventory: InstallationInventoryProvider | None = None,
) -> typer.Typer:
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        apprc or rc.AppRC(app_id="installation-cli", paths=rc.Paths()),
        installation_inventory=installation_inventory,
    )
    return app


def test_installation_show_and_doctor_inspect_invalid_authority_without_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    directory = installation_directory(
        "installation-cli",
        environment={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        },
    )
    directory.mkdir(parents=True)
    (directory / "installation.json").write_text("{not json", encoding="utf-8")
    app = _app()
    runner = CliRunner()

    shown = runner.invoke(app, ["installation", "show", "--json"])
    diagnosed = runner.invoke(app, ["installation", "doctor", "--json"])
    root_doctor = runner.invoke(app, ["doctor", "--json"])

    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["status"] == "invalid"
    assert diagnosed.exit_code == 1, diagnosed.output
    assert root_doctor.exit_code == 1, root_doctor.output
    assert json.loads(root_doctor.stdout)["status"] == "invalid"
    strict_paths = runner.invoke(app, ["paths", "--json"])
    assert strict_paths.exit_code != 0
    assert tuple(directory.iterdir()) == (directory / "installation.json",)


def test_installation_show_missing_is_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    result = CliRunner().invoke(_app(), ["installation", "show", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "missing"
    assert not (tmp_path / "xdg-data").exists()


def test_installation_migration_dry_run_is_read_only_and_execution_needs_consent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app_id = "installation-cli-migrate"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    source = tmp_path / "data" / app_id
    source.mkdir(parents=True)
    marker = source / ".apprc-owner.json"
    marker.write_text(
        '{"schema_version":1,"app_id":"installation-cli-migrate",'
        '"category":"appdata"}\n',
        encoding="utf-8",
    )
    app = _app(rc.AppRC(app_id=app_id, paths=rc.Paths(appdata=True)))
    runner = CliRunner()

    preview = runner.invoke(
        app, ["installation", "migrate", "--dry-run", "--json"]
    )
    refused = runner.invoke(app, ["installation", "migrate"])

    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.stdout)["entries"] == [str(marker)]
    assert refused.exit_code != 0
    assert marker.is_file()
    assert not (source / "appdata").exists()
    assert not installation_directory(
        app_id,
        environment={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
        },
    ).exists()

    accepted = runner.invoke(app, ["installation", "migrate", "--yes"])
    assert accepted.exit_code == 0, accepted.output
    assert (source / "appdata" / ".apprc-owner.json").is_file()
    assert not marker.exists()


def test_installation_repair_uses_exact_saved_argv_and_propagates_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    argv = (sys.executable, "-c", "raise SystemExit(23)")
    installer = tmp_path / "installer.py"
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    monkeypatch.setenv("HOME", environment["HOME"])
    monkeypatch.setenv("XDG_DATA_HOME", environment["XDG_DATA_HOME"])
    observed: list[tuple[tuple[str, ...], bool]] = []
    saved_calls: list[tuple[Path, Path | None]] = []

    def repair_saved(
        directory: Path, *, installer: Path | None = None
    ) -> tuple[str, ...]:
        saved_calls.append((directory, installer))
        return argv

    monkeypatch.setattr(controllers, "repair_saved", repair_saved)

    def run(
        arguments: tuple[str, ...], *, check: bool
    ) -> subprocess.CompletedProcess[str]:
        observed.append((arguments, check))
        return subprocess.CompletedProcess(arguments, 23)

    monkeypatch.setattr(
        "apprc.interfaces.cli.installation_command.subprocess.run", run
    )
    result = CliRunner().invoke(
        _app(),
        ["installation", "repair", "--installer", str(installer)],
    )

    assert result.exit_code == 23
    assert saved_calls == [
        (
            installation_directory("installation-cli", environment=environment),
            installer,
        )
    ]
    assert observed == [(argv, False)]


def _ready_uninstall_preparation(
    directory: Path,
    *,
    categories: frozenset[ResourceKind],
    complete: bool,
    forget_retained: bool,
) -> UninstallPreparation:
    placement = InstallationPlacement(
        layout=Layout.native(),
        config_dir=(
            directory.parent / "config" if "config" in categories else None
        ),
        appdata_dir=(
            directory.parent / "appdata" if "appdata" in categories else None
        ),
        cache_dir=(
            directory.parent / "cache" if "cache" in categories else None
        ),
        capabilities=categories,
    )
    identity = InstallationIdentity(
        app_id="installation-cli",
        distribution="installation-cli",
        import_package="installation_cli",
        apprc_reference=None,
        commands=("installation-cli",),
    )
    source = InstallationSource(kind="editable", requirement=str(directory))
    backend = UvToolTarget(
        executable=Path(sys.executable),
        tool_dir=directory / "tools",
        bin_dir=directory / "bin",
    )
    snapshot = InstalledSnapshot(
        identity=identity,
        version="1.0",
        source=source,
        placement=placement,
        backend=backend,
        prefix=directory / "environment",
        interpreter=Path(sys.executable),
        commands=(directory / "bin" / "installation-cli",),
    )
    record = InstallationRecord(
        schema_version=1,
        app_id="installation-cli",
        generation_id=uuid4(),
        support_version="1",
        placement=placement,
        status="ready",
        current=snapshot,
    )
    inspection = InstallationInspection(
        status="ready",
        directory=directory,
        revision="a" * 64,
        app_id="installation-cli",
        record=record,
    )
    entries = tuple(
        InventoryEntry(
            path=directory / category / "settings.toml",
            kind="file",
            revision="b" * 64,
            resource=category,
        )
        for category in sorted(categories)
    )
    plan = UninstallPlan(
        directory=directory,
        expected_revision="a" * 64,
        expected_generation=record.generation_id,
        app_id="installation-cli",
        operation_id=uuid4(),
        placement=placement,
        inventory=CleanupInventory(entries=entries),
        categories=categories,
        complete=complete,
        forget_retained=forget_retained,
    )
    return UninstallPreparation(
        plan=plan,
        inspection=inspection,
        entries=entries,
        diagnostics=(),
        can_execute=True,
    )


def test_installation_uninstall_preview_uses_real_owned_inventory_and_requires_consent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config", "cache"}),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None
    for root, category in (
        (record.placement.config_dir, "config"),
        (record.placement.cache_dir, "cache"),
    ):
        assert root is not None
        root.mkdir(parents=True)
        (root / ".apprc-owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": record.app_id,
                    "category": category,
                }
            ),
            encoding="utf-8",
        )
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    observed: list[tuple[frozenset[ResourceKind], bool]] = []

    def inventory_provider(
        selected_inspection: InstallationInspection,
        categories: frozenset[ResourceKind],
        forget_retained: bool,
    ) -> CleanupInventory:
        observed.append((categories, forget_retained))
        return default_cleanup_inventory(
            selected_inspection,
            categories=categories,
            forget_retained=forget_retained,
        )

    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=inspection),
    )
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )
    runner = CliRunner()
    app = _app(installation_inventory=inventory_provider)
    preview = runner.invoke(
        app,
        [
            "installation",
            "uninstall",
            "--dry-run",
            "--complete",
            "--category",
            "config",
            "--category",
            "cache",
            "--json",
        ],
    )
    no_consent = runner.invoke(
        app,
        [
            "installation",
            "uninstall",
            "--complete",
            "--json",
        ],
    )
    assert preview.exit_code == 0, preview.output
    assert observed == [
        (frozenset({"config", "cache"}), False),
        (frozenset({"config", "cache"}), False),
    ]
    assert {
        entry["resource"] for entry in json.loads(preview.stdout)["entries"]
    } == {"config", "cache"}
    assert no_consent.exit_code != 0
    assert (record.placement.config_dir / ".apprc-owner.json").is_file()
    assert (record.placement.cache_dir / ".apprc-owner.json").is_file()


def test_cache_only_complete_preview_uses_provider_without_host_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"cache"}),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None
    cache = record.placement.cache_dir
    assert cache is not None
    cache.mkdir(parents=True)
    marker = cache / ".apprc-owner.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_id": record.app_id,
                "category": "cache",
            }
        ),
        encoding="utf-8",
    )
    sentinel = cache / "user-data.bin"
    sentinel.write_bytes(b"keep")
    observed: list[frozenset[ResourceKind]] = []

    def inventory_provider(
        selected_inspection: InstallationInspection,
        categories: frozenset[ResourceKind],
        forget_retained: bool,
    ) -> CleanupInventory:
        observed.append(categories)
        assert not forget_retained
        return default_cleanup_inventory(
            selected_inspection,
            categories=categories,
            forget_retained=forget_retained,
        )

    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=inspection),
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )
    result = CliRunner().invoke(
        _app(installation_inventory=inventory_provider),
        [
            "installation",
            "uninstall",
            "--dry-run",
            "--complete",
            "--category",
            "cache",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed == [frozenset({"cache"})]
    assert str(marker) in {
        entry["path"] for entry in json.loads(result.stdout)["entries"]
    }
    assert sentinel.read_bytes() == b"keep"
    assert marker.is_file()
    assert not (tmp_path / "installation" / "installation.json").exists()
    assert not tuple(tmp_path.glob("apprc-cleanup-*"))


def test_zero_resource_complete_preview_skips_host_inventory_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset(),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=inspection),
    )
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )
    calls: list[object] = []

    def inventory_provider(*args):
        calls.append(args)
        return CleanupInventory()

    result = CliRunner().invoke(
        _app(installation_inventory=inventory_provider),
        ["installation", "uninstall", "--dry-run", "--complete", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert calls == []
    assert not (tmp_path / "installation" / "installation.json").exists()


def test_default_cleanup_inventory_tracks_only_selected_owned_roots(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config", "cache"}),
        complete=True,
        forget_retained=True,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None
    config = record.placement.config_dir
    cache = record.placement.cache_dir
    assert config is not None and cache is not None
    for root, category in ((config, "config"), (cache, "cache")):
        root.mkdir(parents=True)
        (root / ".apprc-owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": record.app_id,
                    "category": category,
                }
            ),
            encoding="utf-8",
        )
    (config / "apprc.user.env").write_text("VALUE=1\n", encoding="utf-8")

    inventory = default_cleanup_inventory(
        inspection,
        categories=frozenset({"config"}),
        forget_retained=True,
    )

    assert {entry.path for entry in inventory.entries} == {
        config / ".apprc-owner.json",
        config / "apprc.user.env",
        config,
    }
    assert inventory.retained == (
        InventoryEntry(cache, "directory", None, "cache"),
    )


def test_saved_config_inventory_includes_secret_file_and_retains_unknown(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None and record.placement.config_dir is not None
    root = record.placement.config_dir
    root.mkdir(parents=True)
    (root / ".apprc-owner.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_id": record.app_id,
                "category": "config",
            }
        ),
        encoding="utf-8",
    )
    secret = root / "apprc.user.secret.env"
    secret.write_text("TOKEN=private\n", encoding="utf-8")
    unknown = root / "custom.ini"
    unknown.write_text("retain me\n", encoding="utf-8")

    inventory = default_cleanup_inventory(
        inspection,
        categories=frozenset({"config"}),
        forget_retained=False,
    )

    assert {entry.path for entry in inventory.entries} == {
        root / ".apprc-owner.json",
        secret,
    }
    assert inventory.retained == (
        InventoryEntry(root, "directory", None, "config"),
    )
    assert unknown.read_text(encoding="utf-8") == "retain me\n"


def test_default_config_inventory_retains_unknown_files_when_forgotten(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=True,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None and record.placement.config_dir is not None
    root = record.placement.config_dir
    root.mkdir(parents=True)
    (root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"installation-cli","category":"config"}\n',
        encoding="utf-8",
    )
    unknown = root / "unknown.db"
    unknown.write_text("application payload\n", encoding="utf-8")

    inventory = default_cleanup_inventory(
        inspection,
        categories=frozenset({"config"}),
        forget_retained=True,
    )

    assert inventory.retained == (
        InventoryEntry(root, "directory", None, "config"),
    )
    assert unknown not in {entry.path for entry in inventory.entries}


def test_default_cleanup_inventory_rejects_mismatched_root_marker(
    tmp_path: Path,
) -> None:
    from apprc.distribution.runtime.controllers import default_cleanup_inventory

    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None and record.placement.config_dir is not None
    root = record.placement.config_dir
    root.mkdir(parents=True)
    (root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"other","category":"config"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Mismatched AppRC ownership marker"):
        default_cleanup_inventory(
            inspection,
            categories=frozenset({"config"}),
            forget_retained=False,
        )


def test_pending_uninstall_resumes_saved_identity_and_options(
    tmp_path: Path,
) -> None:
    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset(),
        complete=False,
        forget_retained=False,
    )
    saved = preparation.inspection
    assert saved.record is not None
    original_plan = preparation.plan
    assert original_plan is not None
    operation = InstallationOperation(
        operation_id=original_plan.operation_id,
        kind="uninstall",
        phase="failed",
        intended=None,
        placement=saved.record.placement,
        steps=(OperationStep.PROVIDER_CLEANUP,),
        inventory=original_plan.inventory,
        categories=original_plan.categories,
        complete=original_plan.complete,
        forget_retained=original_plan.forget_retained,
    )
    pending_record = replace(
        saved.record, status="incomplete", operation=operation
    )
    pending = replace(
        saved,
        status="incomplete",
        revision="c" * 64,
        record=pending_record,
    )

    resumed = controllers._resume_uninstall(
        pending,
        categories=frozenset(),
        complete=False,
        forget_retained=False,
        inventory=None,
    )

    assert resumed is not None
    assert resumed.operation_id == original_plan.operation_id
    assert resumed.inventory == original_plan.inventory
    assert resumed.expected_revision == "c" * 64
    with pytest.raises(InstallationError):
        controllers._resume_uninstall(
            pending,
            categories=frozenset({"config"}),
            complete=False,
            forget_retained=False,
            inventory=None,
        )


def test_pending_complete_cli_retry_reuses_persisted_inventory_without_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command

    first = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    )
    record = first.inspection.record
    assert record is not None and first.plan is not None
    operation = InstallationOperation(
        operation_id=first.plan.operation_id,
        kind="uninstall",
        phase="failed",
        intended=None,
        placement=record.placement,
        steps=(OperationStep.PROVIDER_CLEANUP,),
        inventory=first.plan.inventory,
        categories=first.plan.categories,
        complete=True,
        forget_retained=False,
    )
    pending = replace(
        first.inspection,
        status="incomplete",
        revision="c" * 64,
        record=replace(record, status="incomplete", operation=operation),
    )
    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=pending),
    )
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: pending
    )
    calls: list[object] = []

    def fresh_provider(*args):
        calls.append(args)
        return CleanupInventory()

    result = CliRunner().invoke(
        _app(installation_inventory=fresh_provider),
        [
            "installation",
            "uninstall",
            "--dry-run",
            "--complete",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == []
    assert tuple(
        entry["path"] for entry in json.loads(result.stdout)["entries"]
    ) == tuple(str(entry.path) for entry in operation.inventory.entries)


def test_cli_complete_preview_uses_fresh_saved_owned_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command

    stub = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config", "appdata"}),
        complete=True,
        forget_retained=False,
    )
    assert stub.plan is not None
    base_record = stub.inspection.record
    assert base_record is not None
    placement = replace(
        base_record.placement,
        appdata_dir=tmp_path / "appdata",
        cache_dir=None,
        capabilities=frozenset({"config", "appdata"}),
    )
    record = replace(base_record, placement=placement)
    inspection = replace(stub.inspection, record=record)
    for root, category in (
        (placement.config_dir, "config"),
        (placement.appdata_dir, "appdata"),
    ):
        assert root is not None
        root.mkdir(parents=True)
        (root / ".apprc-owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": record.app_id,
                    "category": category,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=inspection),
    )
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )

    result = CliRunner().invoke(
        _app(),
        [
            "installation",
            "uninstall",
            "--dry-run",
            "--complete",
            "--category",
            "config",
            "--category",
            "appdata",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert {entry["resource"] for entry in payload["entries"]} == {
        "config",
        "appdata",
    }


def test_complete_preview_rejects_stale_host_file_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    preparation = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    )
    inspection = preparation.inspection
    record = inspection.record
    assert record is not None
    config = record.placement.config_dir
    config.mkdir(parents=True)
    target = config / "settings.toml"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )

    with pytest.raises(
        InstallationError, match="changed after inventory preview"
    ):
        controllers.prepare_uninstall(
            inspection.directory,
            categories=frozenset({"config"}),
            complete=True,
            inventory=CleanupInventory(
                entries=(
                    InventoryEntry(
                        target,
                        "file",
                        "0" * 64,
                        "config",
                    ),
                )
            ),
        )


def test_complete_preview_rejects_inventory_outside_saved_ownership(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inspection = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    ).inspection
    external = tmp_path / "external-input.txt"
    external.write_bytes(b"keep")
    monkeypatch.setattr(
        controllers, "inspect_saved", lambda _directory: inspection
    )

    preparation = controllers.prepare_uninstall(
        inspection.directory,
        categories=frozenset({"config"}),
        complete=True,
        inventory=CleanupInventory(
            entries=(
                InventoryEntry(
                    external, "file", file_revision(external), "config"
                ),
            )
        ),
    )

    assert preparation.plan is None
    assert not preparation.can_execute
    assert external.read_bytes() == b"keep"


def test_cli_transports_exact_inventory_to_real_saved_controller_subprocess(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from apprc.interfaces.cli import installation_command

    base = _ready_uninstall_preparation(
        tmp_path / "installation",
        categories=frozenset({"config"}),
        complete=True,
        forget_retained=False,
    )
    record = base.inspection.record
    assert record is not None and record.current is not None
    directory = base.inspection.directory
    create_private_directory_if_missing(directory)
    config = record.placement.config_dir
    assert config is not None
    config.mkdir(parents=True)
    (config / ".apprc-owner.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_id": record.app_id,
                "category": "config",
            }
        ),
        encoding="utf-8",
    )
    target = config / "provider-selected.db"
    target.write_bytes(b"remove")
    sentinel = config / "provider-unknown.db"
    sentinel.write_bytes(b"retain")
    support = directory / "saved-support.txt"
    support.write_text("saved support\n", encoding="utf-8")
    controller = directory / "app-uninstall.py"
    controller.write_text(
        """
import argparse
import os
import stat
from pathlib import Path
from apprc.distribution.runtime.controllers import (
    parse_uninstall_handoff_args, prepare_uninstall, stage_uninstall,
)
from apprc.user_files.installation.codec import decode_cleanup_inventory

original_pid, expected_revision, forwarded = parse_uninstall_handoff_args()
parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--complete", action="store_true")
parser.add_argument("--category", action="append")
parser.add_argument("--forget-retained", action="store_true")
parser.add_argument("--inventory", type=Path, required=True)
args = parser.parse_args(forwarded)
if os.name != "nt" and stat.S_IMODE(args.inventory.stat().st_mode) != 0o600:
    raise RuntimeError("Accepted cleanup inventory is not private.")
accepted = decode_cleanup_inventory(args.inventory.read_bytes())
preparation = prepare_uninstall(
    args.directory,
    categories=frozenset(args.category or ()),
    complete=args.complete,
    forget_retained=args.forget_retained,
    inventory=accepted,
)
if preparation.plan is None or not preparation.can_execute:
    raise RuntimeError("Saved controller rejected accepted inventory.")
if preparation.plan.expected_revision != expected_revision:
    raise RuntimeError("Saved controller observed a stale record revision.")
stage_uninstall(preparation.plan, provider_cleanup=lambda _context: None)
""",
        encoding="utf-8",
    )
    record = replace(
        record,
        current=replace(
            record.current,
            owned_outputs=(
                OwnedOutput(
                    "support", controller.name, file_revision(controller)
                ),
                OwnedOutput("support", support.name, file_revision(support)),
            ),
        ),
    )
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    inspection = controllers.inspect_saved(directory)
    monkeypatch.setattr(
        installation_command,
        "installation_context",
        lambda _ctx: SimpleNamespace(inspection=inspection),
    )
    monkeypatch.setattr(
        controllers,
        "_saved_management_argv",
        lambda _directory, _target, selected, arguments: (
            sys.executable,
            str(selected),
            *arguments,
            "--directory",
            str(_directory),
        ),
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    observed: list[CleanupInventory] = []

    def inventory_provider(
        _inspection: InstallationInspection,
        categories: frozenset[ResourceKind],
        forget_retained: bool,
    ) -> CleanupInventory:
        assert categories == frozenset({"config"})
        assert forget_retained
        inventory = CleanupInventory(
            entries=(
                InventoryEntry(target, "file", file_revision(target), "config"),
            ),
            retained=(InventoryEntry(config, "directory", None, "config"),),
        )
        observed.append(inventory)
        return inventory

    result = CliRunner().invoke(
        _app(installation_inventory=inventory_provider),
        [
            "installation",
            "uninstall",
            "--complete",
            "--category",
            "config",
            "--forget-retained",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    staged = controllers.inspect_saved(directory).record
    assert staged is not None and staged.operation is not None
    accepted = staged.operation.inventory
    assert accepted == CleanupInventory(
        entries=(
            *observed[0].entries,
            InventoryEntry(controller, "file", file_revision(controller)),
            InventoryEntry(support, "file", file_revision(support)),
        ),
        retained=observed[0].retained,
    )
    assert target.is_file()
    assert sentinel.read_bytes() == b"retain"
    assert not tuple(tmp_path.glob("apprc-cleanup-*"))
