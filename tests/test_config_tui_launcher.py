from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Select, Static
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.installation import (
    CleanupInventory,
    EditableCheckout,
    InstallationDiagnostic,
    InstallationInspection,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
    RuntimeSlot,
    UninstallPlan,
)
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import ResolveOptions
from apprc.distribution.runtime._leases import (
    acquire_runtime_lease,
    try_retire_runtime_slot,
)
from apprc.distribution.runtime import controllers
from apprc.distribution.runtime.controllers import UninstallPreparation
from apprc.interfaces.tui._primitives import ConfirmScreen
from apprc.interfaces.tui.editor import ConfigEditorScreen
from apprc.interfaces.tui.launcher.app import LauncherApp, LauncherInfoScreen
from apprc.interfaces.tui.launcher.model import (
    LauncherAction,
    LauncherContext,
    LauncherSpec,
    run_launcher,
)
from apprc.interfaces.tui.modals import ConfigValueEditScreen
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.interfaces.cli import mount_app_cli
from tests.support_config import build_config_only_example_app


def _launcher_context(
    tmp_path: Path, *, invalid: bool = False, cache_only: bool = False
) -> LauncherContext:
    environment = {
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
    }
    apprc = rc.AppRC(
        app_id="launcher-test",
        command_name="launcher-test",
        paths=Paths(cache=True) if cache_only else Paths(config=True),
        user_dotenv=None if cache_only else rc.UserDotenv(),
    )
    installation = apprc.installation(environment=environment)
    inspection = (
        InstallationInspection(
            status="invalid",
            directory=installation.directory,
            revision=None,
            app_id="launcher-test",
            diagnostics=(
                InstallationDiagnostic(
                    code="malformed",
                    message="The saved record is invalid.",
                    recovery="Run app repair after inspection.",
                ),
            ),
        )
        if invalid
        else installation.inspect()
    )
    paths = (
        None
        if invalid
        else apprc.paths(ResolveOptions(), environment=environment)
    )
    if cache_only and paths is not None:
        assert paths.cache_dir is not None
        paths.cache_dir.mkdir(parents=True)
    action = LauncherAction(
        id="main",
        label="Main command",
        argv=lambda _context, _interactive: (
            sys.executable,
            "-c",
            "pass",
        ),
    )
    return LauncherContext(
        apprc=apprc,
        spec=LauncherSpec(actions=(action,), title="Example launcher"),
        options=ResolveOptions(),
        environment=environment,
        inspection=inspection,
        paths=paths,
        cwd=tmp_path,
    )


@pytest.mark.asyncio
async def test_launcher_opens_reusable_config_screen_in_same_app(
    tmp_path: Path,
) -> None:
    app = LauncherApp(context=_launcher_context(tmp_path), handlers={})

    async with app.run_test() as pilot:
        assert app.screen is app.home
        config_button = app.home.query_one("#launcher-config", Button)
        assert not config_button.disabled
        # > Long fixture paths can place actions below the viewport.
        config_button.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(config_button)
        await pilot.pause()
        assert isinstance(app.screen, ConfigEditorScreen)


@pytest.mark.asyncio
async def test_invalid_installation_shows_diagnostics_and_disables_unsafe_actions(
    tmp_path: Path,
) -> None:
    app = LauncherApp(
        context=_launcher_context(tmp_path, invalid=True),
        handlers={},
    )

    async with app.run_test():
        assert app.home.query_one("#launcher-action-main", Button).disabled
        assert app.home.query_one("#launcher-config", Button).disabled
        assert app.home.query_one("#launcher-workspaces", Button).disabled
        assert app.home.query_one("#launcher-uninstall", Button).disabled
        assert not app.home.query_one("#launcher-repair", Button).disabled


@pytest.mark.asyncio
async def test_paths_without_resolved_components_expose_only_installation(
    tmp_path: Path,
) -> None:
    app = LauncherApp(
        context=_launcher_context(tmp_path, invalid=True), handlers={}
    )
    async with app.run_test() as pilot:
        paths_button = app.home.query_one("#launcher-paths", Button)
        for _ in range(len(app.home.query(Button))):
            if app.focused is paths_button:
                break
            await pilot.press("tab")
        assert app.focused is paths_button
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LauncherInfoScreen)
        assert set(screen.directories) == {"installation"}
        await pilot.click("#launcher-copy-path")
        assert app.clipboard == str(app.context.inspection.directory)


@pytest.mark.parametrize("viewport", [(80, 24), (48, 16)])
@pytest.mark.asyncio
async def test_launcher_quit_stops_and_awaits_its_owned_foreground_child(
    tmp_path: Path, viewport: tuple[int, int]
) -> None:
    context = _launcher_context(tmp_path)
    child_environment = dict(context.environment)
    child_environment["LAUNCHER_CHILD_TOKEN"] = "captured-value"
    marker = tmp_path / "child-environment.txt"
    child_code = (
        "import os,time; "
        f"open({str(marker)!r}, 'w').write(os.environ['LAUNCHER_CHILD_TOKEN']); "
        "time.sleep(30)"
    )
    action = LauncherAction(
        id="long_running",
        label="Long-running command",
        argv=lambda _context, _interactive: (
            sys.executable,
            "-c",
            child_code,
        ),
        interactive=False,
    )
    context = LauncherContext(
        apprc=context.apprc,
        spec=LauncherSpec(actions=(action,), title=context.spec.title),
        options=context.options,
        environment=child_environment,
        inspection=context.inspection,
        paths=context.paths,
        cwd=context.cwd,
    )
    app = LauncherApp(context=context, handlers={})
    owned_process = None

    async with app.run_test() as pilot:
        await pilot.resize_terminal(*viewport)
        try:
            action_button = app.home.query_one(
                "#launcher-action-long_running", Button
            )
            action_button.focus()
            await pilot.press("enter")
            await pilot.pause()
            processes = tuple(app.home._children.values())
            assert len(processes) == 1
            owned_process = processes[0]
            for _ in range(100):
                if marker.exists():
                    break
                await asyncio.sleep(0.01)
            assert marker.read_text(encoding="utf-8") == "captured-value"
            quit_button = app.home.query_one("#launcher-quit", Button)
            for _ in range(len(app.home.query(Button))):
                if app.focused is quit_button:
                    break
                await pilot.press("tab")
            assert app.focused is quit_button
            await pilot.pause()
            await pilot.click(quit_button)
            await pilot.pause()
            assert owned_process.returncode is not None
            assert owned_process.pid not in app.home._children
            assert not app.home._children
        finally:
            if owned_process is not None and owned_process.returncode is None:
                owned_process.terminate()
                await owned_process.wait()


@pytest.mark.skipif(
    os.name == "nt", reason="Managed lease inheritance uses POSIX descriptors."
)
@pytest.mark.asyncio
async def test_launcher_child_keeps_managed_runtime_leased_until_quit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _launcher_context(tmp_path)
    slot = tmp_path / "installation" / "runtimes" / str(uuid4())
    slot.mkdir(parents=True)
    prefix = slot / ".venv"
    prefix.mkdir()
    ready = tmp_path / "lease-child-ready"
    gate = tmp_path / "lease-child-gate"
    os.mkfifo(gate)
    lease = acquire_runtime_lease(slot)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    child_environment = lease.environment(dict(context.environment))
    child_code = (
        "from pathlib import Path; "
        f"Path({str(ready)!r}).write_text('ready'); "
        f"open({str(gate)!r}, 'rb').read()"
    )
    action = LauncherAction(
        id="lease_child",
        label="Lease child",
        argv=lambda _context, _interactive: (
            sys.executable,
            "-c",
            child_code,
        ),
        interactive=False,
    )
    context = LauncherContext(
        apprc=context.apprc,
        spec=LauncherSpec(actions=(action,)),
        options=context.options,
        environment=child_environment,
        inspection=context.inspection,
        paths=context.paths,
        cwd=context.cwd,
    )
    app = LauncherApp(context=context, handlers={})
    owned_process = None

    try:
        async with app.run_test() as pilot:
            action_button = app.home.query_one(
                "#launcher-action-lease_child", Button
            )
            action_button.focus()
            await pilot.press("enter")
            await pilot.pause()
            processes = tuple(app.home._children.values())
            assert len(processes) == 1
            owned_process = processes[0]
            for _ in range(100):
                if ready.exists():
                    break
                await asyncio.sleep(0.01)
            assert ready.read_text(encoding="utf-8") == "ready"
            assert owned_process.returncode is None

            lease.close()
            assert not try_retire_runtime_slot(slot)

            quit_button = app.home.query_one("#launcher-quit", Button)
            for _ in range(len(app.home.query(Button))):
                if app.focused is quit_button:
                    break
                await pilot.press("tab")
            assert app.focused is quit_button
            await pilot.click(quit_button)
            await pilot.pause()
            assert owned_process.returncode is not None
            assert owned_process.pid not in app.home._children
            assert not app.home._children

        assert try_retire_runtime_slot(slot)
    finally:
        if lease.handle >= 0:
            lease.close()
        if owned_process is not None and owned_process.returncode is None:
            owned_process.terminate()
            await owned_process.wait()
        if slot.exists():
            assert try_retire_runtime_slot(slot)
        gate.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_launcher_editor_opens_field_modal_in_the_existing_app(
    tmp_path: Path,
) -> None:
    base = _launcher_context(tmp_path)
    apprc = build_config_only_example_app()
    context = LauncherContext(
        apprc=apprc,
        spec=base.spec,
        options=ResolveOptions(),
        environment=base.environment,
        inspection=apprc.installation(environment=base.environment).inspect(),
        paths=apprc.paths(ResolveOptions(), environment=base.environment),
        cwd=base.cwd,
    )
    app = LauncherApp(context=context, handlers={})

    async with app.run_test() as pilot:
        config_button = app.home.query_one("#launcher-config", Button)
        config_button.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(config_button)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConfigEditorScreen)
        table = screen.query_one("#field-table", DataTable)
        assert screen.row_env_keys
        table.cursor_coordinate = Coordinate(0, 0)
        screen._open_selected_field_editor()
        await pilot.pause()
        assert isinstance(app.screen, ConfigValueEditScreen)


@pytest.mark.parametrize("editable", [False, True], ids=["managed", "editable"])
@pytest.mark.asyncio
async def test_launcher_uninstall_cancellation_does_not_start_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    editable: bool,
) -> None:
    context = _launcher_context(tmp_path)
    identity = InstallationIdentity(
        "launcher-test",
        "launcher-test",
        "launcher_test",
        None,
        ("launcher-test",),
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="launcher-test",
        generation_id=uuid4(),
        support_version="0.34.0",
        placement=InstallationPlacement(Layout.native()),
        status="ready",
        active_runtime=(
            EditableCheckout(tmp_path / "checkout", tmp_path / "checkout/.venv")
            if editable
            else RuntimeSlot(
                slot_id=uuid4(),
                source=ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
                selection=RuntimeSelection("3.14"),
                version="1.0.0",
                python_version="3.14.0",
            )
        ),
    )
    manager = context.apprc.installation(environment=context.environment)
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)
    inspection = manager.inspect()
    record_path = manager.directory / "installation.json"
    before = record_path.read_bytes()
    app = LauncherApp(
        context=LauncherContext(
            apprc=context.apprc,
            spec=context.spec,
            options=context.options,
            environment=context.environment,
            inspection=inspection,
            paths=context.paths,
            cwd=context.cwd,
        ),
        handlers={},
    )
    plan = UninstallPlan(
        directory=inspection.directory,
        expected_revision=inspection.revision or "",
        expected_generation=record.generation_id,
        app_id=record.identity.app_id,
        operation_id=uuid4(),
        placement=record.placement,
        inventory=CleanupInventory(),
    )
    preparation = UninstallPreparation(
        plan=plan,
        inspection=inspection,
        entries=(),
        diagnostics=(),
        can_execute=True,
    )
    monkeypatch.setattr(
        controllers,
        "prepare_uninstall",
        lambda *_args, **_kwargs: preparation,
    )

    handoff_started = False

    def fail_if_handoff_starts(*_args: object, **_kwargs: object) -> None:
        nonlocal handoff_started
        handoff_started = True
        raise AssertionError("Canceled uninstall must not start a handoff.")

    monkeypatch.setattr(
        controllers, "start_uninstall_handoff", fail_if_handoff_starts
    )

    async with app.run_test() as pilot:
        await pilot.press("end")
        await pilot.pause()
        await pilot.click("#launcher-uninstall")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        maintenance_worker = next(
            worker
            for worker in app.workers
            if worker.group == "launcher-maintenance"
        )
        await pilot.click("#confirm-cancel")
        await app.workers.wait_for_complete((maintenance_worker,))

    assert record_path.read_bytes() == before
    assert manager.inspect() == inspection
    assert not handoff_started


@pytest.mark.asyncio
async def test_launcher_path_selection_copies_only_enabled_cache_path(
    tmp_path: Path,
) -> None:
    app = LauncherApp(
        context=_launcher_context(tmp_path, cache_only=True), handlers={}
    )
    async with app.run_test() as pilot:
        await pilot.resize_terminal(48, 16)
        paths_button = app.home.query_one("#launcher-paths", Button)
        for _ in range(len(app.home.query(Button))):
            if app.focused is paths_button:
                break
            await pilot.press("tab")
        assert app.focused is paths_button
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LauncherInfoScreen)
        selection = screen.query_one("#launcher-path-selection", Select)
        assert set(screen.directories) == {"cache", "installation"}
        assert selection.value == "cache"
        expected = str(screen.directories["cache"])
        await pilot.click("#launcher-copy-path")
        assert app.clipboard == expected
        selection.focus()
        await pilot.press("enter")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert selection.value == "installation"
        await pilot.click("#launcher-copy-path")
        assert app.clipboard == str(app.context.inspection.directory)
        await pilot.click("#launcher-info-back")


@pytest.mark.asyncio
async def test_launcher_path_actions_keep_missing_copy_and_refuse_new_link(
    tmp_path: Path,
) -> None:
    context = _launcher_context(tmp_path, cache_only=True)
    assert context.paths is not None and context.paths.cache_dir is not None
    cache = context.paths.cache_dir
    cache.rmdir()
    app = LauncherApp(context=context, handlers={})
    opened: list[tuple[str, ...]] = []

    async def observe_open(argv: Sequence[str]) -> None:
        opened.append(tuple(argv))

    async with app.run_test() as pilot:
        paths_button = app.home.query_one("#launcher-paths", Button)
        for _ in range(len(app.home.query(Button))):
            if app.focused is paths_button:
                break
            await pilot.press("tab")
        assert app.focused is paths_button
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LauncherInfoScreen)
        assert screen.query_one("#launcher-open-path", Button).disabled
        await pilot.click("#launcher-copy-path")
        assert app.clipboard == str(cache)

        cache.mkdir()
        selection = screen.query_one("#launcher-path-selection", Select)
        selection.value = "installation"
        await pilot.pause()
        selection.value = "cache"
        await pilot.pause()
        assert not screen.query_one("#launcher-open-path", Button).disabled
        screen.open_path = observe_open
        cache.rmdir()
        cache.symlink_to(tmp_path, target_is_directory=True)
        await pilot.click("#launcher-open-path")
        workers = tuple(app.workers)
        await app.workers.wait_for_complete(workers)
        assert opened == []
        assert cache.exists() and cache.is_symlink()


def test_launcher_reports_unusable_placement_without_invalidating_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    environment = dict(_launcher_context(tmp_path).environment)
    environment.update(
        {
            "USERPROFILE": str(tmp_path),
            "LOCALAPPDATA": str(tmp_path / "local"),
        }
    )
    apprc = rc.AppRC(
        app_id="launcher-path-error",
        command_name="launcher-path-error",
        paths=rc.Paths(cache=True),
    )
    manager = apprc.installation(environment=environment)
    identity = rc.InstallationIdentity(
        "launcher-path-error",
        "launcher-path-error",
        "launcher_path_error",
        None,
        ("launcher-path-error",),
    )
    record = rc.InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="launcher-path-error",
        generation_id=uuid4(),
        support_version="0.34.0",
        placement=InstallationPlacement(rc.Layout.native()),
        status="removed-retained",
    )
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)
    record_path = manager.directory / "installation.json"
    before = record_path.read_bytes()
    with pytest.raises(rc.InstallationError) as failure:
        apprc.paths(environment=environment)
    spec = LauncherSpec(
        actions=(
            LauncherAction(
                "run", "Run", lambda _context, _dry_run: (sys.executable,)
            ),
        )
    )

    async def observe(app: LauncherApp) -> None:
        async with app.run_test():
            status = json.loads(
                str(app.home.query_one("#launcher-status", Static).content)
            )
            assert status["status"] == "error"
            assert status["path_error"] == str(failure.value)
            assert app.home.query_one("#launcher-action-run", Button).disabled

    def run(app: LauncherApp) -> None:
        asyncio.run(observe(app))

    monkeypatch.setattr(LauncherApp, "run", run)
    run_launcher(apprc, spec=spec, environment=environment)
    assert record_path.read_bytes() == before
    assert manager.inspect().status == "removed-retained"
    assert not (tmp_path / "xdg-cache").exists()


def test_cli_launch_uses_captured_selectors_and_real_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from apprc.definition.resolution import ResolveOptions

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    apprc = rc.AppRC(app_id="cli-launch-test", paths=rc.Paths(cache=True))
    manager = apprc.installation()
    manager.directory.mkdir(parents=True)
    record_path = manager.directory / "installation.json"
    record_path.write_text("{invalid", encoding="utf-8")
    original_record = record_path.read_bytes()
    original_diagnostics = [
        item.message for item in manager.inspect().diagnostics
    ]
    first_env = tmp_path / "first.env"
    second_env = tmp_path / "second.env"
    first_env.write_text("FIRST=one\n", encoding="utf-8")
    second_env.write_text("SECOND=two\n", encoding="utf-8")
    selected_root = tmp_path / "missing-selected-root"
    observed: list[LauncherApp] = []

    async def observe(app: LauncherApp) -> None:
        async with app.run_test():
            status = json.loads(
                str(app.home.query_one("#launcher-status", Static).content)
            )
            assert status["diagnostics"] == original_diagnostics
            assert app.home.query_one("#launcher-action-run", Button).disabled
            assert (
                app.home.query_one("#launcher-repair", Button).disabled is False
            )

    def run(app: LauncherApp) -> None:
        observed.append(app)
        asyncio.run(observe(app))

    monkeypatch.setattr(LauncherApp, "run", run)
    spec = LauncherSpec(
        actions=(
            LauncherAction(
                "run", "Run", lambda _context, _dry_run: (sys.executable,)
            ),
        )
    )
    app = typer.Typer()
    mount_app_cli(app, apprc, launcher_spec=spec)
    result = CliRunner().invoke(
        app,
        [
            "--layout",
            "single-root",
            "--app-root",
            str(selected_root),
            "--env-file",
            str(first_env),
            "--env-file",
            str(second_env),
            "-o",
            "-s",
            "--workspace",
            "sample",
            "--log-level",
            "DEBUG",
            "launch",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    context = observed[0].context
    assert context.options == ResolveOptions(
        env_files=(first_env, second_env),
        env_file_overrides_os_environ=True,
        load_dotenv_layers=False,
        workspace="sample",
        layout=Layout.single_root(selected_root),
    )
    assert context.log_level == "DEBUG"
    assert context.environment["HOME"] == str(home)
    assert record_path.read_bytes() == original_record
    assert not selected_root.exists()


def test_cli_launch_help_is_local_and_absent_spec_has_no_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(_app: LauncherApp) -> None:
        raise AssertionError("launch help must not start Textual")

    monkeypatch.setattr(LauncherApp, "run", unexpected_run)
    app = typer.Typer()
    mount_app_cli(
        app,
        build_config_only_example_app(),
        launcher_spec=LauncherSpec(),
    )
    result = CliRunner().invoke(app, ["launch", "--help"])
    assert result.exit_code == 0, result.output
    assert "Open the interactive AppRC application launcher." in result.output

    root_help = CliRunner().invoke(app, ["--help"])
    assert root_help.exit_code == 0, root_help.output
    assert (
        "Open the interactive AppRC application launcher." in root_help.output
    )

    absent = typer.Typer()
    mount_app_cli(absent, build_config_only_example_app())
    result = CliRunner().invoke(absent, ["launch"])
    assert result.exit_code != 0
    assert "No such command" in result.output
