from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from apprc.interfaces.tui._field_state import EditableConfigValueSource
from apprc.interfaces.tui._rendering import setting_title
from apprc.interfaces.tui._value_modal_rendering import (
    source_copy_is_disabled,
)
from apprc.interfaces.tui.modals.screens import ConfigValueEditScreen
from tests.support_config import WORKSPACE_EXAMPLE_OWNER


def test_value_edit_modal_opens_empty_target_for_multiple_scopes() -> None:
    screen = ConfigValueEditScreen(
        spec=WORKSPACE_EXAMPLE_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="user", raw_value="user-profile"),
            EditableConfigValueSource(
                key="workspace",
                raw_value="workspace-profile",
            ),
        ),
        writable_scopes=("user", "workspace"),
    )

    assert screen._target_value() == ""


def test_value_edit_modal_prefills_only_writable_scope() -> None:
    screen = ConfigValueEditScreen(
        spec=WORKSPACE_EXAMPLE_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="user", raw_value="user-profile"),
        ),
        writable_scopes=("user",),
    )

    assert screen._target_value() == "user-profile"


def test_value_edit_title_marks_restart_required_field() -> None:
    spec = WORKSPACE_EXAMPLE_OWNER.field("profile")
    restart_spec = replace(spec, restart_required=True)

    assert setting_title(restart_spec) == "Profile (restart required)"


def test_value_edit_modal_keyboard_save_requires_unambiguous_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = ConfigValueEditScreen(
        spec=WORKSPACE_EXAMPLE_OWNER.field("profile"),
        env_key="APPRC_EXAMPLE_APP_PROFILE",
        value_sources=(
            EditableConfigValueSource(key="user", raw_value="user-profile"),
            EditableConfigValueSource(
                key="workspace",
                raw_value="workspace-profile",
            ),
        ),
        writable_scopes=("user", "workspace"),
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

    assert len(notifications) == 1


def test_source_copy_availability_uses_actual_source_value() -> None:
    assert (
        source_copy_is_disabled(
            EditableConfigValueSource(key="workspace", raw_value=None)
        )
        is True
    )
    assert (
        source_copy_is_disabled(
            EditableConfigValueSource(key="workspace", raw_value="")
        )
        is False
    )
