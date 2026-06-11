from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static

from apprc.config.tui_primitives import PathSuggester
from tests.support_config import (
    build_apprc_example_app_kit,
    set_apprc_example_app_apprc_toml,
    set_apprc_example_app_bootstrap,
)

pytestmark = [pytest.mark.requires_apprc_env("APPRC_EXAMPLE_APP")]


@pytest.mark.asyncio
async def test_config_setup_wizard_launches_with_host_overview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    setup_app = kit.setup_app()

    async with setup_app.run_test():
        title = setup_app.query_one("#setup-title", Static).content
        body = setup_app.query_one("#setup-body", Static).content

    assert "Example App config setup" in str(title)
    assert "Example App uses one small AppRC TOML" in str(body)
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in str(body)
    assert "AppRC TOML" in str(body)


@pytest.mark.asyncio
async def test_config_setup_wizard_opens_prefilled_path_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    setup_app = kit.setup_app()

    async with setup_app.run_test() as pilot:
        setup_app.query_one("#setup-start", Button).press()
        await pilot.pause()
        path_input = setup_app.screen.query_one("#path-input", Input)
        path_value = path_input.value
        suggester = path_input.suggester
        message = setup_app.screen.query_one("#path-message", Static).content

    assert path_value == str(tmp_path / "config" / "apprc_example_app")
    assert isinstance(suggester, PathSuggester)
    assert "Computed TOML path:" in str(message)
    assert "apprc_example_app.apprc.toml" in str(message)


@pytest.mark.asyncio
@pytest.mark.allow_missing_apprc_env
async def test_config_setup_wizard_asks_for_path_without_env(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    setup_app = kit.setup_app()

    async with setup_app.run_test() as pilot:
        setup_app.query_one("#setup-start", Button).press()
        await pilot.pause()
        path_input = setup_app.screen.query_one("#path-input", Input)
        message = setup_app.screen.query_one("#path-message", Static).content

    assert path_input.value == ""
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in str(message)
    assert "fixed file name apprc_example_app.apprc.toml" in str(message)


@pytest.mark.asyncio
async def test_config_setup_wizard_shows_existing_registry_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    set_apprc_example_app_apprc_toml(monkeypatch, tmp_path)
    kit = build_apprc_example_app_kit()
    kit.register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        make_default=True,
    )
    setup_app = kit.setup_app()

    async with setup_app.run_test() as pilot:
        setup_app.query_one("#setup-start", Button).press()
        await pilot.pause()
        body = setup_app.query_one("#setup-body", Static).content
        keep_button = setup_app.query_one("#existing-keep", Button)
        reset_button = setup_app.query_one("#existing-reset", Button)
        move_button = setup_app.query_one("#existing-move", Button)
        keep_disabled = keep_button.disabled
        reset_disabled = reset_button.disabled
        move_disabled = move_button.disabled

    assert "The current config has these storages registered:" in str(body)
    assert "alpha [default]" in str(body)
    assert keep_disabled is False
    assert reset_disabled is False
    assert move_disabled is False


@pytest.mark.asyncio
async def test_config_setup_wizard_finish_shows_doctor_and_next_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "alpha"
    set_apprc_example_app_bootstrap(
        monkeypatch,
        tmp_path,
        storage_root=storage_root,
    )
    kit = build_apprc_example_app_kit()
    registry = kit.register_storage(
        name="alpha",
        root=storage_root,
        make_default=True,
    )
    setup_app = kit.setup_app()

    async with setup_app.run_test():
        await setup_app._finish_setup(registry)
        title = setup_app.query_one("#setup-title", Static).content
        body = setup_app.query_one("#setup-body", Static).content

    assert "Done" in str(title)
    assert "doctor: ok" in str(body)
    assert "apprc_example_app config edit" in str(body)
    assert "apprc_example_app config show" in str(body)
    assert "apprc_example_app config doctor" in str(body)
    assert "export APPRC_EXAMPLE_APP_APPRC_TOML" in str(body)
    assert 'export APPRC_EXAMPLE_APP_STORAGE="alpha"' in str(body)
