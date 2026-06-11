from __future__ import annotations

import shutil
from pathlib import Path

from apprc.config.storage.registry import (
    record_archived_storage,
    register_storage,
)
from apprc.config.tui.storage.entries import (
    ordered_existing_storage_names,
    ordered_storage_entries,
    storage_entry_index,
    storage_entry_label,
    suggest_storage_name,
)


def test_config_textual_storage_entries_order_live_missing_and_archived(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "config" / "demo.apprc.toml"
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    archive_path = tmp_path / "zeta.apprc.tar.xz"
    archive_path.write_bytes(b"placeholder")
    register_storage(
        name="beta",
        root=beta_root,
        make_default=False,
        path=registry_path,
    )
    registry = register_storage(
        name="alpha",
        root=alpha_root,
        make_default=True,
        path=registry_path,
    )
    registry = record_archived_storage(
        name="zeta",
        archive=archive_path,
        source_root=tmp_path / "zeta",
        path=registry_path,
    )
    shutil.rmtree(beta_root)

    entries = ordered_storage_entries(registry)

    assert [(entry.name, entry.kind) for entry in entries] == [
        ("alpha", "live"),
        ("beta", "missing"),
        ("zeta", "archived"),
    ]
    assert ordered_existing_storage_names(registry) == ["alpha"]
    assert storage_entry_index(entries, "beta") == 1
    assert storage_entry_index(entries, "missing") is None
    assert "alpha [default]" in storage_entry_label(registry, entries[0])
    assert "beta [missing]" in storage_entry_label(registry, entries[1])
    assert "zeta [Last Archived]" in storage_entry_label(registry, entries[2])


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
