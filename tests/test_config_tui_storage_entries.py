from __future__ import annotations

import shutil
from pathlib import Path

from apprc import AppRC, Layout, Paths, Workspaces
from apprc.interfaces.tui._styles import (
    ARCHIVE_STYLE,
    MISSING_STYLE,
    PATH_STYLE,
)
from apprc.interfaces.tui.workspaces.entries import (
    ordered_workspace_entries,
    suggest_workspace_name,
    workspace_entry_index,
    workspace_entry_label,
)
from tests.support_tui import text_has_span


def test_config_textual_workspace_entries_order_live_missing_and_archived(
    tmp_path: Path,
) -> None:
    apprc_root = tmp_path / "config"
    app = AppRC(
        app_id="workspace-entry-test",
        paths=Paths(config=True),
        layout=Layout.single_root(apprc_root),
        workspaces=Workspaces(selector_env_key="WORKSPACE_ENTRY_TEST"),
    )
    manager = app.workspaces(environment={})
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    zeta_root = tmp_path / "zeta"
    zeta_root.mkdir()
    archive_path = tmp_path / "zeta.apprc.tar.xz"
    manager.register_workspace(name="alpha", root=alpha_root)
    manager.register_workspace(name="beta", root=beta_root)
    manager.register_workspace(name="zeta", root=zeta_root)
    manager.archive_workspace(name="zeta", destination=archive_path)
    manager.remove_workspace(name="zeta")
    registry = manager.registry()
    shutil.rmtree(beta_root)

    entries = ordered_workspace_entries(registry)

    assert [(entry.name, entry.kind) for entry in entries] == [
        ("alpha", "live"),
        ("beta", "missing"),
        ("zeta", "archived"),
    ]
    assert workspace_entry_index(entries, "beta") == 1
    assert workspace_entry_index(entries, "missing") is None
    alpha_label = workspace_entry_label(registry, entries[0])
    beta_label = workspace_entry_label(registry, entries[1])
    zeta_label = workspace_entry_label(registry, entries[2])
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
        str(registry.archived_workspaces["zeta"].archive),
        PATH_STYLE,
    )


def test_suggest_workspace_name_normalizes_paths_and_archives() -> None:
    assert (
        suggest_workspace_name(
            Path("/tmp/My Workspace!"),
            fallback_name="demo_work-1",
        )
        == "My-Workspace"
    )
    assert (
        suggest_workspace_name(
            Path("/tmp/Project Name.apprc.tar.xz"),
            fallback_name="demo_work-1",
        )
        == "Project-Name"
    )
    assert (
        suggest_workspace_name(Path("/"), fallback_name="demo_work-1")
        == "demo_work-1"
    )
