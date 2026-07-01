from __future__ import annotations

from typing import Any

import pytest

from apprc.interfaces.tui._field_state import EditableConfigValueSource
from apprc.interfaces.tui.modals.screens import ConfigValueEditScreen
from apprc.interfaces.tui._value_modal_rendering import (
    source_copy_is_disabled,
)
from tests.support_config import APPRC_EXAMPLE_APP_OWNER


def test_value_edit_modal_opens_empty_target_for_multiple_scopes() -> None:
    screen = ConfigValueEditScreen(
        spec=APPRC_EXAMPLE_APP_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="app", raw_value="app-profile"),
            EditableConfigValueSource(
                key="storage",
                raw_value="storage-profile",
            ),
        ),
        writable_scopes=("app", "storage"),
    )

    assert screen._target_value() == ""


def test_value_edit_modal_prefills_only_writable_scope() -> None:
    screen = ConfigValueEditScreen(
        spec=APPRC_EXAMPLE_APP_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="app", raw_value="app-profile"),
        ),
        writable_scopes=("app",),
    )

    assert screen._target_value() == "app-profile"


def test_value_edit_modal_keyboard_save_requires_unambiguous_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = ConfigValueEditScreen(
        spec=APPRC_EXAMPLE_APP_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="app", raw_value="app-profile"),
            EditableConfigValueSource(
                key="storage",
                raw_value="storage-profile",
            ),
        ),
        writable_scopes=("app", "storage"),
    )
    notifications: list[str] = []

    def record_notification(
        message: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        notifications.append(message)

    def fail_save(raw_scope: str) -> None:
        raise AssertionError(f"unexpected inferred save to {raw_scope}")

    monkeypatch.setattr(screen, "notify", record_notification)
    monkeypatch.setattr(screen, "_save_scope", fail_save)

    screen.action_save()

    assert notifications == ["Choose Save App-wide or Save Storage."]


def test_source_copy_availability_uses_actual_source_value() -> None:
    assert (
        source_copy_is_disabled(
            EditableConfigValueSource(key="storage", raw_value=None)
        )
        is True
    )
    assert (
        source_copy_is_disabled(
            EditableConfigValueSource(key="storage", raw_value="")
        )
        is False
    )
