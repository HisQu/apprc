from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Select, Static

import apprc as rc
from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationInspection,
    InstallationPlacement,
    InstallationRecord,
    UninstallPlan,
)
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import ResolveOptions
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
                    recovery="Run installation repair after inspection.",
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
        assert not app.home.query_one("#launcher-config", Button).disabled
        await pilot.click("#launcher-config")
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
    action = LauncherAction(
        id="long_running",
        label="Long-running command",
        argv=lambda _context, _interactive: (
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ),
        interactive=False,
    )
    context = LauncherContext(
        apprc=context.apprc,
        spec=LauncherSpec(actions=(action,), title=context.spec.title),
        options=context.options,
        environment=context.environment,
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
        await pilot.click("#launcher-config")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConfigEditorScreen)
        table = screen.query_one("#field-table", DataTable)
        assert screen.row_env_keys
        table.cursor_coordinate = Coordinate(0, 0)
        screen._open_selected_field_editor()
        await pilot.pause()
        assert isinstance(app.screen, ConfigValueEditScreen)


@pytest.mark.asyncio
async def test_launcher_uninstall_cancellation_does_not_start_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _launcher_context(tmp_path)
    record = InstallationRecord(
        schema_version=1,
        app_id=context.apprc.schema.app_id,
        generation_id=uuid4(),
        support_version="0.31.0",
        placement=InstallationPlacement(Layout.native()),
        status="removed-retained",
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
        app_id=record.app_id,
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
    apprc = rc.AppRC(app_id="launcher-path-error", paths=rc.Paths(cache=True))
    manager = apprc.installation(environment=environment)
    record = rc.InstallationRecord(
        1,
        apprc.schema.app_id,
        uuid4(),
        "0.31.0",
        InstallationPlacement(rc.Layout.native()),
        "removed-retained",
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
