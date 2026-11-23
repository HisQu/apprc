from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
import pytest

import typer
from typer.testing import CliRunner
from rich.text import Text

import apprc as rc
from apprc.interfaces.cli.context import InstallationCommandContext
from apprc.user_files.installation.discovery import installation_directory


def _app(
    apprc: rc.AppRC | None = None,
    *,
    args: Sequence[str],
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
    maintenance_group_name: str = "app",
) -> typer.Typer:
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        apprc or rc.AppRC(app_id="installation-cli", paths=rc.Paths()),
        installation_management=True,
        installer_entrypoint=installer_entrypoint,
        maintenance_group_name=maintenance_group_name,
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


def test_editable_workspace_uses_root_environment_only_for_members(
    tmp_path: Path,
) -> None:
    from apprc.definition.resolution import resolve_editable_environment

    root = tmp_path / "workspace"
    member = root / "apps" / "application"
    excluded = root / "apps" / "excluded"
    unrelated = root / "checkouts" / "independent"
    for project in (member, excluded, unrelated):
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            '[project]\nname = "application"\nversion = "1.0"\n',
            encoding="utf-8",
        )
    (root / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["apps/*"]\n'
        'exclude = ["apps/excluded"]\n',
        encoding="utf-8",
    )

    assert resolve_editable_environment(member) == root / ".venv"
    assert resolve_editable_environment(excluded) == excluded / ".venv"
    assert resolve_editable_environment(unrelated) == unrelated / ".venv"


def test_editable_workspace_rejects_unsafe_patterns_and_linked_environment(
    tmp_path: Path,
) -> None:
    from apprc.definition.resolution import resolve_editable_environment

    root = tmp_path / "workspace"
    member = root / "apps" / "application"
    member.mkdir(parents=True)
    (member / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    workspace_file = root / "pyproject.toml"
    workspace_file.write_text(
        '[tool.uv.workspace]\nmembers = ["../outside"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsafe uv workspace pattern"):
        resolve_editable_environment(member)

    workspace_file.write_text(
        '[tool.uv.workspace]\nmembers = ["apps/*"]\n',
        encoding="utf-8",
    )
    external_environment = tmp_path / "external-venv"
    external_environment.mkdir()
    try:
        (root / ".venv").symlink_to(
            external_environment, target_is_directory=True
        )
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")
    with pytest.raises(ValueError, match="must not be a symlink"):
        resolve_editable_environment(member)


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
    stdout = typer.get_text_stream

    def terminal_stream(name):
        stream = stdout(name)
        if name == "stdout":
            monkeypatch.setattr(stream, "isatty", lambda: True)
        return stream

    monkeypatch.setattr(typer, "get_text_stream", terminal_stream)
    with _authenticated_native_manager_scope(manager_executable):
        preview = CliRunner().invoke(
            app, ["app", "migrate", "--dry-run"], env=environment
        )
        assert preview.exit_code == 0, preview.output
        assert "Migration preview" in preview.stdout
        assert str(source) in preview.stdout
        assert "Applying Migration" not in preview.stdout
        assert manager.inspect().revision == pending.revision
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


def test_editable_file_url_decodes_localhost_and_escaped_path(
    tmp_path: Path,
) -> None:
    from apprc.interfaces.cli._editable_checkout import _editable_source_path

    source = tmp_path / "checkout with spaces"
    assert _editable_source_path(source.as_uri()) == source
    localhost = source.as_uri().replace("file://", "file://localhost", 1)
    assert _editable_source_path(localhost) == source


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.invalid/app",
        "file:relative",
        "file:///checkout?query",
        "file:///checkout#fragment",
    ],
)
def test_editable_source_url_rejects_ambiguous_sources(url: str) -> None:
    from apprc.interfaces.cli._editable_checkout import _editable_source_path

    with pytest.raises(ValueError, match="file URL"):
        _editable_source_path(url)


def test_editable_network_source_is_explicit_about_platform() -> None:
    import os

    from apprc.interfaces.cli._editable_checkout import _editable_source_path

    if os.name == "nt":
        assert _editable_source_path("file://server/share/check%20out") == Path(
            r"\\server\share\check out"
        )
    else:
        with pytest.raises(
            ValueError,
            match="Cannot convert editable source URL.*mounted local path",
        ):
            _editable_source_path("file://server/share/check%20out")


def test_editable_conversion_error_names_source_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apprc.interfaces.cli import _editable_checkout

    def unavailable_conversion(path: str) -> str:
        raise OSError(22, "conversion failed", path)

    monkeypatch.setattr(
        _editable_checkout, "url2pathname", unavailable_conversion
    )
    source = "file:///checkout"
    with pytest.raises(
        ValueError, match="Cannot convert editable source URL"
    ) as failure:
        _editable_checkout._editable_source_path(source)
    assert source in str(failure.value)
    assert isinstance(failure.value.__cause__, OSError)


@pytest.mark.parametrize("color", [False, True])
@pytest.mark.parametrize(
    "failure",
    ["mismatch", "unavailable-source", "stat-denied", "workspace-root"],
)
def test_editable_environment_error_reports_paths_and_guidance_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, color: bool
) -> None:
    import importlib.metadata
    import sys

    workspace = tmp_path / "workspace"
    checkout = (
        workspace if failure == "workspace-root" else tmp_path
    ) / "checkout"
    expected = (
        workspace if failure == "workspace-root" else checkout
    ) / ".venv"
    expected.mkdir(parents=True)
    checkout.mkdir(exist_ok=True)
    if failure == "workspace-root":
        (workspace / "pyproject.toml").write_text(
            '[tool.uv.workspace]\nmembers=["checkout"]\n', encoding="utf-8"
        )
    (checkout / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="1.0"\n'
        '[project.scripts]\nfixture="fixture:main"\n',
        encoding="utf-8",
    )
    metadata = tmp_path / "fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n", encoding="utf-8"
    )
    (metadata / "entry_points.txt").write_text(
        "[console_scripts]\nfixture = fixture:main\n", encoding="utf-8"
    )
    (metadata / "direct_url.json").write_text(
        json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}),
        encoding="utf-8",
    )
    source = (
        checkout / "unavailable-source"
        if failure == "unavailable-source"
        else checkout
    )
    (metadata / "direct_url.json").write_text(
        json.dumps({"url": source.as_uri(), "dir_info": {"editable": True}}),
        encoding="utf-8",
    )
    distribution = importlib.metadata.Distribution.at(metadata)

    def installed_commands(
        *, group: str, name: str
    ) -> importlib.metadata.EntryPoints:
        return distribution.entry_points.select(group=group, name=name)

    args = ["app", "install", "-e"]
    app = _app(
        rc.AppRC(app_id="fixture", command_name="fixture", paths=rc.Paths()),
        args=args,
    )
    running = (
        expected
        if failure == "workspace-root"
        else tmp_path / "other-environment"
    )
    running.mkdir(exist_ok=True)
    monkeypatch.setattr(sys, "prefix", str(running))
    monkeypatch.setattr(importlib.metadata, "entry_points", installed_commands)
    monkeypatch.chdir(workspace if failure == "workspace-root" else checkout)
    if failure == "stat-denied":
        original_samefile = Path.samefile

        def inaccessible_identity(self: Path, other: str | Path) -> bool:
            if self == expected:
                raise PermissionError(13, "identity access denied", str(self))
            return original_samefile(self, other)

        monkeypatch.setattr(Path, "samefile", inaccessible_identity)
    elif failure == "workspace-root":
        original_samefile = Path.samefile

        def workspace_identity(self: Path, other: str | Path) -> bool:
            if not self.is_relative_to(workspace):
                raise AssertionError(
                    "Probed above the valid workspace boundary"
                )
            return original_samefile(self, other)

        monkeypatch.setattr(Path, "samefile", workspace_identity)
    result = CliRunner().invoke(
        app,
        args,
        env={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "COLUMNS": "1000",
        },
        terminal_width=1000,
        color=color,
    )

    assert result.exit_code == 2, result.output
    # > Validate the actual CLI error independently of ANSI styling and wrapping.
    error = (
        result.exception.__context__ if result.exception is not None else None
    )
    assert isinstance(error, typer.BadParameter), result.output
    message = str(error)
    if failure == "mismatch":
        assert "Expected environment:" in message
        assert str(expected) in message
    elif failure == "workspace-root":
        assert "Console command 'fixture' is unavailable at" in message
    else:
        assert "Cannot access editable source" in message
        assert str(source) in message
        if failure == "stat-denied":
            assert "identity access denied" in message
            assert str(expected) in message
        else:
            assert "unavailable-source" in message
    if failure != "workspace-root":
        assert "running environment:" in message
        assert str(running) in message
    assert message.count("install -e` from the checkout.") == 1


def _pending_editable_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[InstallationCommandContext, Path]:
    """Capture a real failed registration for the current fixture checkout."""
    import importlib.metadata
    import os
    import sys

    from apprc.definition.installation import (
        EditableCheckout,
        InstallationDiagnostic,
        InstallationPlacement,
    )
    from apprc.definition.resolution import CliRuntimeOptions
    from apprc.distribution.metadata import read_distribution_spec
    from apprc.interfaces.cli import installation_command
    from apprc.services.installation import InstallationManager

    checkout = tmp_path / "checkout"
    prefix = checkout / ".venv"
    binary = prefix / ("Scripts" if os.name == "nt" else "bin")
    binary.mkdir(parents=True)
    (binary / ("fixture.exe" if os.name == "nt" else "fixture")).touch()
    (checkout / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="1.0"\n'
        '[project.scripts]\nfixture="fixture:main"\n',
        encoding="utf-8",
    )
    metadata = tmp_path / "fixture-1.0.dist-info"
    metadata.mkdir()
    for name, content in {
        "METADATA": "Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n",
        "entry_points.txt": "[console_scripts]\nfixture = fixture:main\n",
        "direct_url.json": json.dumps(
            {"url": checkout.as_uri(), "dir_info": {"editable": True}}
        ),
    }.items():
        (metadata / name).write_text(content, encoding="utf-8")
    distribution = importlib.metadata.Distribution.at(metadata)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda **selection: distribution.entry_points.select(**selection),
    )
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.chdir(checkout)
    commands = tmp_path / "commands"
    commands.mkdir()
    uv = tmp_path / "uv"
    uv.touch()
    monkeypatch.setattr(
        installation_command.shutil, "which", lambda *a, **k: str(uv)
    )
    manager = InstallationManager(
        rc.AppRC(
            app_id="fixture",
            command_name="fixture",
            paths=rc.Paths(config=True),
        ).schema,
        directory=tmp_path / "installation",
        environment={"PATH": str(commands)},
    )
    spec = read_distribution_spec(checkout)
    placement = InstallationPlacement(
        rc.Layout.single_root(tmp_path / "saved-resources"),
        config_dir=tmp_path / "saved-resources" / "config",
        capabilities=frozenset({"config"}),
    )
    plan = manager.plan_install(
        spec.metadata.identity,
        EditableCheckout(checkout, prefix, spec.hooks),
        placement,
        command_name="fixture",
    )
    pending = manager.begin_operation(plan)
    assert pending.revision is not None
    failed = manager.fail_operation(
        operation_id=plan.operation_id,
        expected_revision=pending.revision,
        diagnostic=InstallationDiagnostic(
            "runtime-incomplete",
            "Earlier staging ACL failure.",
            "Retry installation.",
        ),
    )
    context = InstallationCommandContext(
        runtime_options=CliRuntimeOptions(),
        cli_options=None,
        environment=manager.environment,
        inspection=failed,
        manager=manager,
    )
    monkeypatch.setattr(installation_command, "_inspection", lambda _: context)
    return context, commands


@pytest.mark.parametrize("conflict", [None, "layout", "checkout"])
def test_editable_retry_uses_only_exact_pending_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str | None
) -> None:
    from dataclasses import replace

    from apprc.definition.installation import EditableCheckout
    from apprc.definition.resolution import CliRuntimeOptions
    from apprc.distribution.runtime.installation import editable
    from apprc.interfaces.cli import installation_command
    from typer.main import get_command

    context, commands = _pending_editable_context(tmp_path, monkeypatch)
    record = context.inspection.record
    assert record is not None and record.operation is not None
    intended = record.operation.intended
    assert intended is not None and isinstance(
        intended.runtime, EditableCheckout
    )
    if conflict == "layout":
        context = replace(
            context,
            runtime_options=CliRuntimeOptions(layout=rc.Layout.native()),
        )
    elif conflict == "checkout":
        operation = replace(
            record.operation,
            intended=replace(
                intended,
                runtime=replace(
                    intended.runtime, project=tmp_path / "other-checkout"
                ),
            ),
        )
        context = replace(
            context,
            inspection=replace(
                context.inspection, record=replace(record, operation=operation)
            ),
        )
    monkeypatch.setattr(installation_command, "_inspection", lambda _: context)
    observed = []

    def register(manager, identity, runtime, placement, **kwargs):
        observed.append((identity, runtime, placement))
        return manager.inspect()

    monkeypatch.setattr(editable, "register_editable_application", register)
    ctx = typer.Context(get_command(_app(args=[])))
    if conflict is not None:
        with pytest.raises(
            ValueError,
            match="differs from captured|another operation or checkout",
        ):
            installation_command._register_editable(
                ctx, command_directory=commands, assume_yes=False
            )
        assert observed == []
    else:
        result = installation_command._register_editable(
            ctx, command_directory=commands, assume_yes=False
        )
        assert result == context.manager.inspect()
        assert observed == [
            (intended.identity, intended.runtime, record.operation.placement)
        ]
    assert context.manager.inspect().status == "incomplete"


def test_editable_install_reports_rollback_notes_and_guidance_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.distribution.runtime.installation import editable
    from apprc.distribution.runtime._install_progress import report

    _context, commands = _pending_editable_context(tmp_path, monkeypatch)
    outcome = "AppRC installation changes were rolled back."

    def fail_registration(*args, **kwargs):
        report("result", "Global command", "PUBLISHED", commands / "fixture")
        error = ValueError("controlled publication failure")
        error.add_note(outcome)
        raise error

    monkeypatch.setattr(
        editable, "register_editable_application", fail_registration
    )
    args = ["app", "install", "-e", "--command-directory", str(commands)]
    result = CliRunner().invoke(_app(args=args), args, terminal_width=1000)
    assert result.exit_code == 2, result.output
    assert "PUBLISHED" in result.output
    assert "installation complete" not in result.output
    error = (
        result.exception.__context__ if result.exception is not None else None
    )
    assert isinstance(error, typer.BadParameter), result.output
    assert "controlled publication failure" in str(error)
    assert str(error).count(outcome) == 1
    assert str(error).count("install -e` from the checkout.") == 1


@pytest.mark.parametrize(
    ("setup_fails", "shortcut_mode"),
    [
        (True, "fresh"),
        (True, "explicit"),
        (False, "fresh"),
        (False, "existing"),
        (False, "explicit"),
        (False, "unattended"),
    ],
)
def test_editable_install_reports_outcome(
    tmp_path, monkeypatch, setup_fails, shortcut_mode
):
    from dataclasses import replace
    import subprocess

    from apprc.definition.installation import EditableCheckout, OwnedOutput
    from apprc.distribution.runtime.installation import post_install
    from apprc.interfaces.cli import installation_command

    context, commands = _pending_editable_context(tmp_path, monkeypatch)
    record = context.inspection.record
    assert record is not None and record.operation is not None
    intended = record.operation.intended
    assert intended is not None
    assert isinstance(intended.runtime, EditableCheckout)
    command = commands / "fixture"
    ready = replace(
        context.inspection,
        status="ready",
        record=replace(
            record,
            status="ready",
            operation=None,
            active_runtime=intended.runtime,
            owned_outputs=(OwnedOutput("command", str(command), "digest"),),
        ),
    )
    monkeypatch.setattr(
        installation_command, "_register_editable", lambda *a, **k: ready
    )
    if shortcut_mode in {"fresh", "unattended"}:
        context = replace(
            context,
            inspection=replace(
                context.inspection, status="missing", record=None
            ),
        )
        monkeypatch.setattr(
            installation_command, "_inspection", lambda _: context
        )
    prompts = []
    shortcuts = []

    def confirm(identity, *, assume_yes):
        prompts.append(assume_yes)
        return not assume_yes

    def publish(manager, destination, identity, **options):
        assert options["desktop"]
        shortcuts.append(destination)
        return ready

    monkeypatch.setattr(post_install, "confirm_desktop_shortcut", confirm)
    monkeypatch.setattr(post_install, "publish_optional_shortcuts", publish)

    def setup(*args, **kwargs):
        if setup_fails:
            raise subprocess.CalledProcessError(1, "setup")
        return False

    monkeypatch.setattr(post_install, "offer_configuration_setup", setup)
    args = ["app", "install", "-e"]
    if shortcut_mode == "explicit":
        args.extend(("--desktop", "--yes"))
    elif shortcut_mode == "unattended":
        args.append("--yes")
    result = CliRunner().invoke(_app(args=args), args, terminal_width=1000)
    assert result.exit_code == 0, result.output
    assert "1. Reusing Runtime" in result.output
    assert result.output.rstrip().endswith("editable installation complete.")
    if setup_fails:
        assert "config setup failed" in result.output
    assert prompts == (
        [shortcut_mode == "unattended"]
        if shortcut_mode in {"fresh", "unattended"}
        else []
    )
    assert shortcuts == (
        [command] if shortcut_mode in {"fresh", "explicit"} else []
    )


@pytest.mark.parametrize("mode", ["interactive", "yes", "preview", "keep"])
def test_uninstall_config_prompt_and_unattended_policy(
    tmp_path, monkeypatch, mode
):
    from dataclasses import replace
    from types import SimpleNamespace
    from apprc.interfaces.cli import installation_command
    from apprc.distribution.runtime import _uninstall_controller as controller

    context, _commands = _pending_editable_context(tmp_path, monkeypatch)
    record = context.inspection.record
    assert record is not None and record.placement.config_dir is not None
    assert (
        record.operation is not None and record.operation.intended is not None
    )
    record = replace(
        record,
        status="ready",
        operation=None,
        active_runtime=record.operation.intended.runtime,
    )
    context = replace(
        context,
        inspection=replace(context.inspection, status="ready", record=record),
    )
    monkeypatch.setattr(installation_command, "_inspection", lambda _: context)
    assert record.placement.config_dir is not None
    record.placement.config_dir.mkdir(parents=True)
    monkeypatch.setattr(
        installation_command,
        "sys",
        SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)),
    )
    prompts = []

    def confirm(message, **kwargs):
        prompts.append(message)
        return True

    monkeypatch.setattr(typer, "confirm", confirm)

    def prepare(directory, **kwargs):
        assert kwargs["keep_config"] is (
            True if mode in {"interactive", "keep"} else None
        )
        return controller.UninstallPreparation(
            None, context.inspection, (), (), False
        )

    monkeypatch.setattr(controller, "prepare_uninstall", prepare)
    args = ["app", "uninstall"]
    args += {
        "interactive": [],
        "yes": ["--yes", "--wait"],
        "preview": ["--dry-run"],
        "keep": ["--keep-config"],
    }[mode]
    result = CliRunner().invoke(_app(args=args), args)
    assert result.exit_code == (0 if mode == "preview" else 1), result.output
    assert len(prompts) == (1 if mode == "interactive" else 0)


@pytest.mark.parametrize(
    "mode",
    ["busy", "idle", "unknown", "lock-busy", "yes", "unattended", "preview"],
)
def test_uninstall_activity_warning_is_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import Mock

    from filelock import FileLock

    from apprc.definition.installation import InstallationHooks
    from apprc.definition.resolution import CliRuntimeOptions
    from apprc.distribution.runtime import _uninstall_controller as controller
    from apprc.distribution.runtime._leases import acquire_runtime_lease
    from apprc.interfaces.cli import installation_command
    from apprc.services.installation import InstallationManager
    from tests.support_installation import managed_installation

    directory, runtime = managed_installation(
        tmp_path, hooks=InstallationHooks()
    )
    app = rc.AppRC(app_id="handoff-app", paths=rc.Paths())
    manager = InstallationManager(app.schema, directory=directory)
    slot = directory / "runtimes" / str(runtime.slot_id)
    marker = slot / ".apprc-runtime-lease"
    if mode == "unknown":
        marker.unlink()

    context = InstallationCommandContext(
        CliRuntimeOptions(),
        None,
        manager.environment,
        manager.inspect(),
        manager,
    )
    monkeypatch.setattr(installation_command, "_inspection", lambda _: context)
    monkeypatch.setattr(
        installation_command,
        "sys",
        SimpleNamespace(
            stdin=SimpleNamespace(
                isatty=lambda: mode not in {"yes", "unattended"}
            )
        ),
    )
    handoff = Mock()
    start = Mock(return_value=handoff)
    monkeypatch.setattr(controller, "start_uninstall_handoff", start)

    args = ["app", "uninstall"]
    if mode == "yes":
        args.append("--yes")
    elif mode == "preview":
        args.append("--dry-run")
    with ExitStack() as stack:
        if mode in {"busy", "yes", "unattended", "preview"}:
            stack.enter_context(acquire_runtime_lease(slot))
        if mode == "lock-busy":
            stack.enter_context(
                FileLock(
                    directory / "locks" / "operation.lock",
                    preserve_lock_file=True,
                    fallback_to_soft=False,
                )
            )
        result = CliRunner().invoke(
            _app(app, args=args), args, input="y\n", terminal_width=1000
        )

    assert result.exit_code == (2 if mode == "unattended" else 0), result.output
    prompt = 'delete the items marked "Delete"?'
    if mode in {"busy", "idle", "unknown", "lock-busy"}:
        assert result.output.count(prompt) == 1
    else:
        assert prompt not in result.output
    reminder = "Close the application and its background processes"
    if mode == "busy":
        assert result.output.index("A managed runtime is in use.") < (
            result.output.index(prompt)
        )
    elif mode in {"unknown", "lock-busy"}:
        assert reminder in result.stderr
        assert "A managed runtime is in use." not in result.stderr
    else:
        assert reminder not in result.stderr
    if mode == "unknown":
        assert not marker.exists()
    if mode in {"preview", "unattended"}:
        start.assert_not_called()
    else:
        start.assert_called_once()
        handoff.signal_exit.assert_called_once()


@pytest.mark.parametrize("keep_config", [False, True])
@pytest.mark.parametrize("repository_selected", [False, True])
def test_uninstall_tree_separates_retained_paths_and_integrations(
    tmp_path, keep_config, repository_selected
):
    from dataclasses import replace
    from rich.console import Console
    from rich.text import Text
    from apprc.definition.installation import (
        CleanupInventory,
        EditableCheckout,
        InventoryEntry,
        OwnedOutput,
    )
    from apprc.distribution.runtime._uninstall_controller import (
        UninstallPreparation,
        prepare_uninstall,
    )
    from apprc.interfaces.cli._installation_output import uninstall_tree
    from tests.support_installation import managed_installation

    directory, _ = managed_installation(tmp_path)
    preparation = prepare_uninstall(directory)
    assert (
        preparation.plan is not None
        and preparation.inspection.record is not None
    )
    config = tmp_path / "settings[private]"
    cache = tmp_path / "cache"
    command = tmp_path / "bin" / "app"
    checkout = tmp_path / "checkout"
    entry = InventoryEntry(config, "directory", None, "config")
    inventory = CleanupInventory(
        (
            InventoryEntry(cache, "tree", "a" * 64, "cache"),
            *(() if keep_config else (entry,)),
        ),
        (entry,) if keep_config else (),
    )
    if repository_selected:
        inventory = replace(
            inventory,
            entries=(
                *inventory.entries,
                InventoryEntry(checkout, "repository", "a" * 64),
            ),
        )
    record = replace(
        preparation.inspection.record,
        active_runtime=EditableCheckout(checkout, checkout / ".venv"),
        owned_outputs=(OwnedOutput("command", str(command), "a" * 64),),
    )
    preparation = UninstallPreparation(
        replace(preparation.plan, inventory=inventory),
        replace(preparation.inspection, record=record),
        inventory.entries,
        (),
        True,
    )
    tree = uninstall_tree(preparation)
    console = Console(record=True, width=250)
    with console.capture() as captured:
        console.print(tree)
    output = captured.get()

    def labels(node):
        for child in node.children:
            yield child.label
            yield from labels(child)

    path_labels = [label for label in labels(tree) if isinstance(label, Text)]
    by_name = {
        Path(label.plain.split("  ")[0]).name: label for label in path_labels
    }
    assert "Delete" in by_name[cache.name].plain
    assert "Delete" in by_name[command.name].plain
    assert ("Keep" in by_name[checkout.name].plain) is not repository_selected
    assert ("Keep" in by_name[config.name].plain) is keep_config
    assert output.count(str(tmp_path)) == 1
    assert not config.exists(), "Preview must not create or scan targets"
    assert any(span.style == "cyan" for span in by_name[config.name].spans)


@pytest.mark.parametrize(
    "color,no_color,expected",
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_installation_progress_honors_color_policy(
    monkeypatch, color, no_color, expected
):
    from apprc.distribution.runtime._install_progress import InstallProgress
    from apprc.interfaces.cli._installation_output import (
        InstallationProgressOutput,
    )

    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    app = typer.Typer()

    @app.command()
    def show(ctx: typer.Context):
        ctx.color = color
        output = InstallationProgressOutput(ctx, "Example", "managed")
        output(InstallProgress("stage", "Preparing Runtime"))
        output(
            InstallProgress(
                "result", "Environment", "CREATED", Path("/example/[literal]")
            )
        )
        output.complete()

    result = CliRunner().invoke(app, [], color=color)
    assert result.exit_code == 0, result.output
    assert "/example/[literal]" in result.output
    for code in (32, 35, 36):
        assert (f"\x1b[{code}m" in result.output) is expected


def test_uninstall_path_tree_shares_windows_parents_and_preserves_unc():
    from pathlib import PureWindowsPath
    from rich.console import Console
    from rich.tree import Tree
    from apprc.interfaces.cli._installation_output import _add_path_tree

    user = PureWindowsPath(r"C:\Users\example")
    app = user / "AppData" / "Local" / "persodb"
    checkout = PureWindowsPath(r"L:\repos\persodb")
    unc = PureWindowsPath(r"\\server\share\app\config")
    root = Tree("Preview")
    _add_path_tree(
        root,
        {
            app / "installation": ("Delete", "all contents"),
            app / "appdata": ("Delete", "all contents"),
            app / "config": ("Keep", "settings"),
            user / ".local" / "bin" / "pdb.exe": ("Delete", "command"),
            checkout: ("Keep", "checkout"),
            checkout / ".venv": ("Keep", "environment"),
            unc: ("Keep", "settings"),
        },
    )
    console = Console(width=250, color_system=None)
    with console.capture() as captured:
        console.print(root)
    output = captured.get()
    assert output.count(str(user)) == 1
    assert str(app) not in output
    assert "AppData\\Local\\persodb" in output
    assert "installation  Delete" in output
    assert "config  Keep" in output
    assert str(checkout) in output and ".venv  Keep" in output
    assert str(checkout / ".venv") not in output
    assert str(unc) in output


@pytest.mark.parametrize(
    ("arguments", "group"),
    [
        (("app", "update"), "app"),
        (("update",), "app"),
        (("manage", "update"), "manage"),
    ],
)
@pytest.mark.parametrize(
    ("option", "value"),
    [
        (None, None),
        ("--release", "preview/v2.0rc1"),
        ("--version", "2.0.0rc1"),
        ("-v", "2.0.0.301"),
    ],
)
def test_update_command_routes_share_confirmation(
    arguments: tuple[str, ...],
    group: str,
    option: str | None,
    value: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apprc.distribution.runtime import update

    requests: list[tuple[str, str | None, str | None]] = []

    def recorded_update(
        *_args: object,
        confirm: Callable[[str], None],
        maintenance_group: str,
        release_tag: str | None = None,
        release_version: str | None = None,
        **_kwargs: object,
    ) -> int:
        requests.append((maintenance_group, release_tag, release_version))
        confirm("Replace 1.0 with 2.0?")
        return 0

    monkeypatch.setattr(update, "update_application", recorded_update)
    args = [*arguments]
    if option is not None and value is not None:
        args.extend((option, value))
    app = _app(args=args, maintenance_group_name=group)
    refused = CliRunner().invoke(app, args)
    assert refused.exit_code != 0
    assert "Rerun with --yes" in Text.from_ansi(refused.output).plain
    args.append("--yes")
    accepted = CliRunner().invoke(app, args)
    assert accepted.exit_code == 0, accepted.output
    assert "Replace 1.0 with 2.0?" in accepted.output
    release_tag = value if option == "--release" else None
    release_version = value if option in {"--version", "-v"} else None
    assert requests == [(group, release_tag, release_version)] * 2


@pytest.mark.parametrize("route", [["update"], ["app", "update"]])
def test_preview_update_requires_managed_invocation(route: list[str]) -> None:
    args = [*route, "--preview", "--version", "2.0.0b1"]
    result = CliRunner().invoke(_app(args=args), args)
    assert result.exit_code == 1
    assert (
        "Run preview update through an installed managed command"
        in Text.from_ansi(result.output).plain
    )


def test_update_rejects_conflicting_release_selectors() -> None:
    args = ["app", "update", "-v", "2.0.0", "--release", "v2.0.0"]
    result = CliRunner().invoke(_app(args=args), args)

    assert result.exit_code == 1
    assert (
        "Choose either --version or --release."
        in Text.from_ansi(result.output).plain
    )


@pytest.mark.parametrize("arguments", [("app", "update"), ("update",)])
def test_update_prints_a_copyable_retry_command(
    arguments: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer import rich_utils

    from apprc.distribution.runtime import update
    from apprc.distribution.runtime._update_handoff import (
        EditableUpdateRetryError,
    )

    retry = "UV_PROJECT_ENVIRONMENT='some checkout/.venv' uv sync --locked"

    def fail_update(*_args: object, **_kwargs: object) -> int:
        raise EditableUpdateRetryError(f"Dependency sync failed.\n{retry}")

    monkeypatch.setattr(update, "update_application", fail_update)
    monkeypatch.setattr(rich_utils, "MAX_WIDTH", 40)
    args = [*arguments, "--yes"]
    result = CliRunner().invoke(_app(args=args), args)

    assert result.exit_code == 1
    assert result.stderr.splitlines() == [
        "Error: Dependency sync failed.",
        retry,
    ]


def test_update_alias_opt_out_keeps_host_update() -> None:
    app = typer.Typer()
    app.command("update")(lambda: typer.echo("host update"))
    with pytest.raises(RuntimeError, match="update"):
        rc.cli.mount_app_cli(
            app, rc.AppRC(app_id="alias-conflict"), installation_management=True
        )
    rc.cli.mount_app_cli(
        app,
        rc.AppRC(app_id="alias-opt-out", update_alias=False),
        installation_management=True,
    )
    runner = CliRunner()
    assert "host update" in runner.invoke(app, ["update"]).output
    assert runner.invoke(app, ["app", "update", "--help"]).exit_code == 0
