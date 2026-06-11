from __future__ import annotations

from pathlib import Path

from apprc.config.storage.registry import ArchivedStorageRecord, StorageRecord
from apprc.config.tui.styles import ARCHIVE_STYLE, MISSING_STYLE, PATH_STYLE
from apprc.config.tui.field_state import (
    archived_storage_title,
    live_storage_title,
    missing_storage_title,
    selected_field_for_row,
)
from tests.support_config import APPRC_EXAMPLE_APP_OWNERS
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
