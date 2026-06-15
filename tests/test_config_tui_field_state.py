from __future__ import annotations

from pathlib import Path

from apprc.config.storage.registry import ArchivedStorageRecord, StorageRecord
from apprc.config.tui.styles import ARCHIVE_STYLE, MISSING_STYLE, PATH_STYLE
from apprc.config.tui.field_state import (
    archived_storage_title,
    config_value_sources,
    live_storage_title,
    missing_storage_title,
    selected_field_for_row,
)
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNER,
    APPRC_EXAMPLE_APP_OWNERS,
)
from tests.support_tui import text_has_span


def test_selected_field_for_row_ignores_non_field_rows() -> None:
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
            row_index=None,
        )
        is None
    )
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=[None],
            row_index=0,
        )
        is None
    )
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
            row_index=10,
        )
        is None
    )


def test_selected_field_for_row_resolves_known_env_key() -> None:
    selected = selected_field_for_row(
        owners=APPRC_EXAMPLE_APP_OWNERS,
        row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
        row_index=0,
    )

    assert selected is not None
    assert selected.spec.name == "profile"
    assert selected.owner.env_key("profile") == "APPRC_EXAMPLE_APP_PROFILE"


def test_config_value_sources_prefer_shell_over_local_and_shared() -> None:
    profile = APPRC_EXAMPLE_APP_OWNER.field("profile")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("profile")

    sources = config_value_sources(
        spec=profile,
        env_key=env_key,
        local_values={env_key: "local-profile"},
        shell_env={env_key: "shell-profile"},
        shared_values={env_key: "shared-profile"},
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["effective"].raw_value == "shell-profile"
    assert sources_by_key["shell"].raw_value == "shell-profile"
    assert sources_by_key["local"].raw_value == "local-profile"
    assert sources_by_key["shared"].raw_value == "shared-profile"


def test_config_value_sources_keep_empty_local_values_copyable() -> None:
    profile = APPRC_EXAMPLE_APP_OWNER.field("profile")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("profile")

    sources = config_value_sources(
        spec=profile,
        env_key=env_key,
        local_values={env_key: ""},
        shell_env={},
        shared_values={env_key: "shared-profile"},
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["effective"].raw_value == ""
    assert sources_by_key["local"].raw_value == ""
    assert sources_by_key["local"].is_available is True


def test_config_value_sources_disable_missing_required_values() -> None:
    access_token = APPRC_EXAMPLE_APP_OWNER.field("access_token")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("access_token")

    sources = config_value_sources(
        spec=access_token,
        env_key=env_key,
        local_values={},
        shell_env={},
        shared_values={},
    )

    assert all(not source.is_available for source in sources)


def test_config_value_sources_fall_back_to_declared_shared_default() -> None:
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("enabled")

    sources = config_value_sources(
        spec=enabled,
        env_key=env_key,
        local_values={},
        shell_env={},
        shared_values=None,
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["shared"].raw_value == "true"
    assert sources_by_key["effective"].raw_value == "true"


def test_storage_titles_match_editor_text() -> None:
    root = Path("/tmp/demo-storage")
    local_env = root / ".env.apprc_example_app"
    live = StorageRecord(name="alpha", root=root)
    archived = ArchivedStorageRecord(
        name="beta",
        archive=Path("/tmp/beta.apprc.tar.xz"),
        source_root=Path("/tmp/beta"),
    )

    live_title = live_storage_title(live, local_env)
    missing_title = missing_storage_title(live)
    archived_title = archived_storage_title(archived)

    assert live_title.plain == (
        "alpha: /tmp/demo-storage\n/tmp/demo-storage/.env.apprc_example_app"
    )
    assert missing_title.plain == (
        "alpha: Missing storage root\n"
        "Root: /tmp/demo-storage\n"
        "No storage-local env file is available."
    )
    assert archived_title.plain == (
        "beta: Last Archived\n"
        "Archive: /tmp/beta.apprc.tar.xz\n"
        "Last source: /tmp/beta"
    )
    assert text_has_span(live_title, "/tmp/demo-storage", PATH_STYLE)
    assert text_has_span(
        live_title,
        "/tmp/demo-storage/.env.apprc_example_app",
        PATH_STYLE,
    )
    assert text_has_span(missing_title, "Missing storage root", MISSING_STYLE)
    assert text_has_span(missing_title, "/tmp/demo-storage", PATH_STYLE)
    assert text_has_span(archived_title, "Last Archived", ARCHIVE_STYLE)
    assert text_has_span(archived_title, "/tmp/beta.apprc.tar.xz", PATH_STYLE)
    assert text_has_span(archived_title, "/tmp/beta", PATH_STYLE)
