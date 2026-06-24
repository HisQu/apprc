from __future__ import annotations

import shutil
from pathlib import Path

from apprc.runtime_config.storage.registry import (
    record_archived_storage,
    register_storage,
)
from apprc.runtime_config.tui.styles import (
    ARCHIVE_STYLE,
    MISSING_STYLE,
    PATH_STYLE,
)
from apprc.runtime_config.tui.storage.entries import (
    ordered_storage_entries,
    storage_entry_index,
    storage_entry_label,
    suggest_storage_name,
)
from tests.support_tui import text_has_span


def test_config_textual_storage_entries_order_live_missing_and_archived(
    tmp_path: Path,
) -> None:
    apprc_toml_path = tmp_path / "config" / "demo.apprc.toml"
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    archive_path = tmp_path / "zeta.apprc.tar.xz"
    archive_path.write_bytes(b"placeholder")
    register_storage(
        name="beta",
        root=beta_root,
        path=apprc_toml_path,
    )
    registry = register_storage(
        name="alpha",
        root=alpha_root,
        path=apprc_toml_path,
    )
    registry = record_archived_storage(
        name="zeta",
        archive=archive_path,
        source_root=tmp_path / "zeta",
        path=apprc_toml_path,
    )
    shutil.rmtree(beta_root)

    entries = ordered_storage_entries(registry)

    assert [(entry.name, entry.kind) for entry in entries] == [
        ("alpha", "live"),
        ("beta", "missing"),
        ("zeta", "archived"),
    ]
    assert storage_entry_index(entries, "beta") == 1
    assert storage_entry_index(entries, "missing") is None
    alpha_label = storage_entry_label(registry, entries[0])
    beta_label = storage_entry_label(registry, entries[1])
    zeta_label = storage_entry_label(registry, entries[2])
    assert "alpha" in alpha_label.plain
    assert "beta [missing]" in beta_label.plain
    assert "zeta [Last Archived]" in zeta_label.plain
    assert text_has_span(
        alpha_label,
        str(registry.selected("alpha").root),
        PATH_STYLE,
    )
    assert text_has_span(beta_label, "[missing]", MISSING_STYLE)
    assert text_has_span(
        beta_label, str(registry.selected("beta").root), PATH_STYLE
    )
    assert text_has_span(zeta_label, "[Last Archived]", ARCHIVE_STYLE)
    assert text_has_span(
        zeta_label,
        str(registry.archived_storages["zeta"].archive),
        PATH_STYLE,
    )


def test_suggest_storage_name_normalizes_paths_and_archives() -> None:
    assert (
        suggest_storage_name(
            Path("/tmp/My Storage!"),
            fallback_name="demo_stor-1",
        )
        == "My-Storage"
    )
    assert (
        suggest_storage_name(
            Path("/tmp/Project Name.apprc.tar.xz"),
            fallback_name="demo_stor-1",
        )
        == "Project-Name"
    )
    assert (
        suggest_storage_name(Path("/"), fallback_name="demo_stor-1")
        == "demo_stor-1"
    )
