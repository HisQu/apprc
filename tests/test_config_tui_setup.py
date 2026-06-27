from __future__ import annotations

from apprc.runtime_config.setup.text import setup_overview_text
from apprc.runtime_config.tui.setup import ConfigSetupApp
from tests.support_config import (
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_setup_overview_text_describes_storage_route() -> None:
    text = setup_overview_text(build_apprc_example_app_kit())

    assert "selected storage root" in text


def test_setup_overview_text_describes_app_wide_route() -> None:
    text = setup_overview_text(build_storage_free_example_kit())

    assert "app-wide config" in text


def test_config_setup_app_stores_kit() -> None:
    kit = build_apprc_example_app_kit()
    app = ConfigSetupApp(kit=kit)

    assert app.kit is kit
