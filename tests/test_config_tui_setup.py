from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import Button, Input, Static

from apprc.config.setup.flow import ConfigSetupResult
from apprc.config.tui.primitives import PathSuggester
from apprc.config.tui.styles import ENV_KEY_STYLE, PATH_INPUT_CLASS
from tests.support_config import (
    build_apprc_example_app_kit,
    set_apprc_example_app_apprc_toml,
    set_apprc_example_app_bootstrap,
)
from tests.support_tui import text_has_span

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
    assert "Example App needs one active storage root" in str(body)
    assert "Optional multi-storage management" in str(body)
    assert "Setup starts by choosing the active storage root" in str(body)
    assert "APPRC_EXAMPLE_APP_APPRC_TOML" in str(body)
    assert isinstance(body, Text)
    assert text_has_span(body, "APPRC_EXAMPLE_APP_APPRC_TOML", ENV_KEY_STYLE)


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
        title = setup_app.screen.query_one("#path-title", Static).content
        message = setup_app.screen.query_one("#path-message", Static).content

    assert path_value == str(tmp_path / "default-storage")
    assert isinstance(suggester, PathSuggester)
    assert path_input.has_class(PATH_INPUT_CLASS)
    assert "Active storage root" in str(title)
    assert "A storage root is where the application keeps user data" in (
        str(message)
    )
    assert "Optional multi-storage management" in str(message)
    assert isinstance(message, Text)


@pytest.mark.asyncio
@pytest.mark.allow_missing_apprc_env
async def test_config_setup_wizard_asks_for_path_without_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    kit = build_apprc_example_app_kit()
    setup_app = kit.setup_app()

    async with setup_app.run_test() as pilot:
        setup_app.query_one("#setup-start", Button).press()
        await pilot.pause()
        path_input = setup_app.screen.query_one("#path-input", Input)
        message = setup_app.screen.query_one("#path-message", Static).content

    assert path_input.value == str(
        tmp_path / "data" / "apprc_example_app" / "apprc_example_app_stor-1"
    )
    assert path_input.has_class(PATH_INPUT_CLASS)
    assert "APPRC_EXAMPLE_APP_STORAGE" in str(message)
    assert "storage-local .env.apprc_example_app" in str(message)
    assert isinstance(message, Text)
    assert text_has_span(message, "APPRC_EXAMPLE_APP_STORAGE", ENV_KEY_STYLE)


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
    )
    setup_app = kit.setup_app()

    async with setup_app.run_test() as pilot:
        setup_app.query_one("#setup-start", Button).press()
        await pilot.pause()
        setup_app.screen.query_one("#path-continue", Button).press()
        await pilot.pause()
        setup_app.screen.query_one("#multi", Button).press()
        await pilot.pause()
        body = setup_app.screen.query_one("#confirm-message", Static).content
        keep_button = setup_app.screen.query_one("#existing-keep", Button)
        reset_button = setup_app.screen.query_one("#existing-reset", Button)
        move_button = setup_app.screen.query_one("#existing-move", Button)
        keep_disabled = keep_button.disabled
        reset_disabled = reset_button.disabled
        move_disabled = move_button.disabled

    assert "The current AppRC TOML has these storages registered:" in str(body)
    assert "1. alpha:" in str(body)
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
    )
    setup_app = kit.setup_app()

    async with setup_app.run_test():
        await setup_app._finish_setup(
            ConfigSetupResult(
                registry=registry,
                active_storage_root=storage_root.resolve(),
                registered_storage_name="alpha",
            )
        )
        title = setup_app.query_one("#setup-title", Static).content
        body = setup_app.query_one("#setup-body", Static).content

    assert "Done" in str(title)
    assert "Example App setup files are ready." in str(body)
    assert "Add these to your environment:" in str(body)
    assert "Shell:" in str(body)
    assert "Or Dotenv:" in str(body)
    assert "Without APPRC_EXAMPLE_APP_STORAGE" in str(body)
    assert "apprc_example_app config edit" in str(body)
    assert "apprc_example_app config show" in str(body)
    assert "apprc_example_app config doctor" in str(body)
    assert "export APPRC_EXAMPLE_APP_APPRC_TOML" in str(body)
    assert (
        f'export APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"'
        in str(body)
    )
    assert f'APPRC_EXAMPLE_APP_STORAGE="{storage_root.resolve()}"' in (
        str(body)
    )
    assert isinstance(body, Text)
    assert text_has_span(body, "Shell:", "bold")
    assert text_has_span(body, "Or Dotenv:", "bold")
