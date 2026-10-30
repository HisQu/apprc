from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.installation import (
    CleanupInventory,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    InstallationSource,
    InstalledSnapshot,
    InventoryEntry,
    UninstallPlan,
    UvToolTarget,
)
from apprc.definition.paths import Layout, ResourceKind
from apprc.distribution.runtime import controllers
from apprc.distribution.runtime.controllers import UninstallPreparation
from apprc.user_files.installation.discovery import installation_directory


def _app(apprc: rc.AppRC | None = None) -> typer.Typer:
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        apprc or rc.AppRC(app_id="installation-cli", paths=rc.Paths()),
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
        config_dir=directory / "config",
        cache_dir=directory / "cache",
        capabilities=frozenset({"config", "cache"}),
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


def test_installation_uninstall_preview_preserves_categories_and_requires_consent(
    monkeypatch,
) -> None:
    calls: list[tuple[frozenset[ResourceKind], bool, bool]] = []

    def prepare(
        directory: Path,
        *,
        categories: frozenset[ResourceKind],
        complete: bool,
        forget_retained: bool,
    ) -> UninstallPreparation:
        calls.append((categories, complete, forget_retained))
        return _ready_uninstall_preparation(
            directory,
            categories=categories,
            complete=complete,
            forget_retained=forget_retained,
        )

    monkeypatch.setattr(controllers, "prepare_uninstall", prepare)
    runner = CliRunner()
    preview = runner.invoke(
        _app(),
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
        _app(),
        [
            "installation",
            "uninstall",
            "--complete",
            "--category",
            "config",
        ],
    )
    assert preview.exit_code == 0, preview.output
    assert calls[0] == (frozenset({"config", "cache"}), True, False)
    assert {
        entry["resource"] for entry in json.loads(preview.stdout)["entries"]
    } == {"config", "cache"}
    assert no_consent.exit_code != 0
