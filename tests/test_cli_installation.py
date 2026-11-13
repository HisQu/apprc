from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
import pytest

import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.user_files.installation.discovery import installation_directory


def _app(
    apprc: rc.AppRC | None = None,
    *,
    args: Sequence[str],
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
) -> typer.Typer:
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        apprc or rc.AppRC(app_id="installation-cli", paths=rc.Paths()),
        installation_management=True,
        installer_entrypoint=installer_entrypoint,
        args_provider=lambda: args,
    )
    return app


def test_explicit_installer_forwards_arguments_and_status() -> None:
    calls: list[tuple[str, ...]] = []

    def installer(arguments: Sequence[str]) -> int:
        calls.append(tuple(arguments))
        return 23

    args = ["app", "install", "--help"]
    app = _app(args=args, installer_entrypoint=installer)
    runner = CliRunner()

    help_result = runner.invoke(app, args)
    assert help_result.exit_code == 0, help_result.output
    assert calls == []

    args[:] = ["app", "install", "--feature", "value", "--", "package.whl"]
    result = runner.invoke(app, args)
    assert result.exit_code == 23
    assert calls == [("--feature", "value", "package.whl")]


def test_editable_workspace_resolves_member_project_to_root_environment(
    tmp_path: Path,
) -> None:
    from apprc.definition.resolution import resolve_editable_environment

    root = tmp_path / "workspace"
    member = root / "apps" / "application"
    excluded = root / "apps" / "excluded"
    member.mkdir(parents=True)
    excluded.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["apps/*"]\n'
        'exclude = ["apps/excluded"]\n',
        encoding="utf-8",
    )
    for project in (member, excluded):
        (project / "pyproject.toml").write_text(
            '[project]\nname = "application"\nversion = "1.0"\n',
            encoding="utf-8",
        )

    assert resolve_editable_environment(member) == root / ".venv"
    with pytest.raises(ValueError, match="excluded"):
        resolve_editable_environment(excluded)


def test_installer_preserves_click_consumed_options_in_order(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []
    args = [
        "app",
        "install",
        "--yes",
        "--feature",
        "before",
        "--skip-setup",
        "--command-directory",
        str(tmp_path),
        "--feature",
        "after",
    ]
    app = _app(
        args=args,
        installer_entrypoint=lambda values: calls.append(tuple(values)) or 0,
    )

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "--yes",
            "--feature",
            "before",
            "--skip-setup",
            "--command-directory",
            str(tmp_path),
            "--feature",
            "after",
        )
    ]


def test_noneditable_install_without_delegate_requires_native_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    directory = installation_directory(
        "installation-cli", environment=environment
    )
    args = ["app", "install"]
    result = CliRunner().invoke(_app(args=args), args)

    assert result.exit_code != 0
    assert not directory.exists()


def test_root_doctor_reports_invalid_authority_without_paths(
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
    args = ["app", "doctor", "--json"]
    app = _app(args=args)
    runner = CliRunner()

    root_doctor = runner.invoke(app, args)

    assert root_doctor.exit_code == 1, root_doctor.output
    report = json.loads(root_doctor.stdout)
    assert report["status"] == "invalid"
    assert report["installation"]["status"] == "invalid"
    args[:] = ["app", "paths", "--json"]
    strict_paths = runner.invoke(app, args)
    assert strict_paths.exit_code != 0
    assert tuple(directory.iterdir()) == (directory / "installation.json",)


def test_root_doctor_reports_missing_installation_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    args = ["app", "doctor", "--json"]
    result = CliRunner().invoke(_app(args=args), args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["installation"]["status"] == "missing"
    assert not (tmp_path / "xdg-data").exists()


def test_initial_migration_without_bound_identity_is_read_only(
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
    args = ["app", "migrate", "--dry-run", "--json"]
    app = _app(rc.AppRC(app_id=app_id, paths=rc.Paths(appdata=True)), args=args)

    preview = CliRunner().invoke(app, args)

    assert preview.exit_code != 0
    assert marker.is_file()
    assert not (source / "appdata").exists()
    assert not installation_directory(
        app_id,
        environment={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
        },
    ).exists()


def test_native_cli_migrate_resumes_exact_pending_inventory_and_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from apprc.definition.installation import (
        EditableCheckout,
        InstallationHooks,
        InstallationIdentity,
        InstallationPlacement,
        InstallationRecord,
        InventoryEntry,
        MigrationInventory,
        MigrationPlan,
        ProjectSnapshot,
        RuntimeSelection,
    )
    from apprc.definition.paths import Layout, Paths
    from apprc.distribution.models import AppCapabilities, NativeBinding
    from apprc.distribution.runtime import probe
    from apprc.interfaces.cli.context import _authenticated_native_manager_scope
    from apprc.user_files.app_home.writes import file_revision
    from apprc.user_files.installation.coordination import (
        installation_lock,
        write_record,
    )

    app_id = "native-migration-cli"
    command = "native-migration-cli"
    environment = {
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    declaration = rc.AppRC(
        app_id=app_id, paths=Paths(appdata=True), command_name=command
    )
    manager = declaration.installation(environment=environment)
    identity = InstallationIdentity(
        app_id, app_id, "migration_cli", None, (command,)
    )
    hooks = InstallationHooks(migrate="migration_cli:migrate")
    project = tmp_path / "developer-project"
    venv = project / ".venv"
    venv.mkdir(parents=True)
    runtime = EditableCheckout(project, venv, hooks)
    destination_root = tmp_path / "current"
    placement = InstallationPlacement(
        Layout.native(),
        appdata_dir=destination_root,
        capabilities=frozenset({"appdata"}),
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=command,
        generation_id=uuid4(),
        support_version="0.34.0",
        placement=placement,
        status="ready",
        active_runtime=runtime,
    )
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)

    source_root = tmp_path / "legacy"
    source_root.mkdir()
    source = source_root / "database.sqlite"
    source.write_bytes(b"preserved application data")
    inventory = MigrationInventory(
        source_root,
        destination_root,
        (InventoryEntry(source, "file", file_revision(source), "appdata"),),
        (destination_root / source.name,),
    )
    plan = manager.plan_migration(
        placement, inventory=inventory, quiescent=True
    )

    def fail_provider(*_args: object) -> None:
        raise RuntimeError("interrupted migration provider")

    with pytest.raises(RuntimeError, match="interrupted migration provider"):
        manager.migrate(plan, quiescent=True, migration_hook=fail_provider)
    pending = manager.inspect()
    assert pending.record is not None and pending.record.operation is not None
    operation_id = pending.record.operation.operation_id
    calls: list[object] = []

    def application_bridge(
        _directory: Path,
        _identity: InstallationIdentity,
        _runtime: EditableCheckout,
        **request: object,
    ) -> dict[str, bool]:
        current = manager.inspect()
        assert current.revision == request["expected_revision"]
        migration_plan = request["migration_plan"]
        assert isinstance(migration_plan, MigrationPlan)
        assert migration_plan.quiescent
        assert migration_plan.inventory == inventory
        assert request["operation_context"] is not None
        calls.append(migration_plan)
        return {"completed": True}

    monkeypatch.setattr(probe, "application_bridge", application_bridge)
    binding = NativeBinding(
        identity=identity,
        command_name=command,
        display_name="Native migration fixture",
        version="1.0",
        source=ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        selection=RuntimeSelection("3.14"),
        capabilities=AppCapabilities(paths=Paths(appdata=True)),
        layout=Layout.native(),
        bootstrap_env_prefix="APPRC",
        hooks=hooks,
    )
    arguments = ["app", "migrate", "--yes", "--json"]
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        installation_management=True,
        native_binding=binding,
        args_provider=lambda: arguments,
    )
    monkeypatch.setattr(
        type(manager),
        "preview_migration",
        lambda *_args, **_kwargs: pytest.fail(
            "pending migration must not replan or rescan"
        ),
    )
    manager_executable = tmp_path / "native-manager"
    manager_executable.write_bytes(b"fixture manager")
    with _authenticated_native_manager_scope(manager_executable):
        result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code == 0, result.output
    decoder = json.JSONDecoder()
    preview, _offset = decoder.raw_decode(result.stdout)
    assert preview["entries"] == [str(source)]
    assert preview["source_root"] == str(source_root)
    assert len(calls) == 1
    resumed_plan = calls[0]
    assert isinstance(resumed_plan, MigrationPlan)
    assert resumed_plan.operation_id == operation_id
    assert resumed_plan.expected_revision == pending.revision
    completed = manager.inspect()
    assert completed.record is not None
    assert completed.record.operation is None
    assert completed.record.migration is not None
    assert completed.record.migration.phase == "activated"
    assert (destination_root / source.name).read_bytes() == (
        b"preserved application data"
    )
