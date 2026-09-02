from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from textual.containers import HorizontalScroll
from textual.widgets import Button, DataTable, ListView

from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.tui._primitives import (
    ConfirmScreen,
    PathInputResult,
    PathInputScreen,
    StorageNameResult,
    StorageNameScreen,
)
from apprc.interfaces.tui.editor.storage_editing import (
    StorageEditingWorkflows,
)
from apprc.interfaces.tui.storage.selection import (
    LiveStorageSelection,
    MissingStorageSelection,
)
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
    record_archived_storage,
    register_storage,
    write_storage_registry,
)
from apprc.user_files.storage_roots.model import StorageRecord, StorageRegistry
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.interfaces.tui.editor.workflows import (
    ConfigEditorStorageWorkflows,
)
from tests.support_config import (
    ApprcExampleAppEnv,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_editor_uses_new_storage_env_and_index_labels() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
    )

    assert editor.kit.spec.storage_env_filename == ".env.apprc-storage"
    assert editor.index_label == "apprc_example_app.apprc.toml"
    assert editor.init_command.endswith("config storage add NAME PATH")


def test_editor_init_command_uses_custom_config_group_name() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
        config_group_name="settings",
    )

    assert editor.init_command.endswith("settings storage add NAME PATH")
    assert " config storage add " not in editor.init_command


class RestoreFakeEditor:
    """Minimal editor facade for archive-import workflow tests."""

    def __init__(self, *, responses: list[object | None]) -> None:
        """Store modal responses returned by ``push_screen_wait``."""
        self.responses = responses
        self.notifications: list[tuple[str, dict[str, object]]] = []

    async def push_screen_wait(self, screen: object) -> object | None:
        """Return the next scripted modal response."""
        return self.responses.pop(0)

    def notify(self, message: str, **kwargs: object) -> None:
        """Capture workflow notifications."""
        self.notifications.append((message, kwargs))

    def _suggest_storage_name(self, path: Path) -> str:
        """Return a stable storage name for restored paths."""
        return path.name


class NewStorageFakeEditor(RestoreFakeEditor):
    """Minimal editor facade for new-storage routing tests."""

    def _require_storage_registry(self) -> object:
        """Pretend a named-storage registry is available."""
        return object()


class StorageEditingFakeEditor:
    """Minimal editor facade for named-storage editing workflow tests."""

    def __init__(
        self,
        *,
        registry: StorageRegistry,
        selection: LiveStorageSelection | MissingStorageSelection,
        responses: list[object | None],
    ) -> None:
        """Store selected storage state and scripted modal responses."""
        self.storage_registry = registry
        self.selection = selection
        self.responses = responses
        self.notifications: list[tuple[str, dict[str, object]]] = []
        self.screens: list[object] = []
        self.refreshed_names: list[str | None] = []

    def _require_storage_registry(self) -> StorageRegistry:
        """Return the configured registry for the editing workflow."""
        return self.storage_registry

    async def push_screen_wait(self, screen: object) -> object | None:
        """Capture a modal and return the next scripted response."""
        self.screens.append(screen)
        return self.responses.pop(0)

    async def _refresh_storage_list(
        self,
        *,
        select_name: str | None = None,
    ) -> None:
        """Capture the selector requested after a successful update."""
        self.refreshed_names.append(select_name)

    def notify(self, message: str, **kwargs: object) -> None:
        """Capture workflow notifications for assertions."""
        self.notifications.append((message, kwargs))


@pytest.mark.asyncio
async def test_editor_compact_storage_controls_enable_live_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert isinstance(
            editor.query_one("#config-action-row"), HorizontalScroll
        )
        assert [
            str(editor.query_one(f"#{button_id}", Button).label)
            for button_id in (
                "storage-new",
                "storage-register-active",
                "storage-rename",
                "storage-location",
                "storage-move",
                "storage-archive",
                "storage-delete",
            )
        ] == [
            "New",
            "Register",
            "Rename",
            "Location",
            "Move",
            "Archive",
            "Delete",
        ]
        for button_id in (
            "storage-rename",
            "storage-location",
            "storage-move",
            "storage-archive",
            "storage-delete",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is False


@pytest.mark.asyncio
async def test_editor_config_action_row_reserves_scrollbar_height(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=tmp_path / "demo.apprc.toml",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        action_row = editor.query_one("#config-action-row", HorizontalScroll)
        new_button = editor.query_one("#storage-new", Button)

        assert action_row.virtual_size.width > action_row.size.width
        assert action_row.size.height > new_button.size.height


@pytest.mark.asyncio
async def test_editor_serializes_config_actions_until_current_workflow_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=tmp_path / "demo.apprc.toml",
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)
    started = asyncio.Event()
    finish = asyncio.Event()
    rename_calls: list[None] = []
    exit_calls: list[None] = []

    async def wait_to_move_storage() -> None:
        started.set()
        await finish.wait()

    async def record_rename_attempt() -> None:
        rename_calls.append(None)

    monkeypatch.setattr(
        editor.storage_workflows,
        "open_move_storage_flow",
        wait_to_move_storage,
    )
    monkeypatch.setattr(
        editor.storage_workflows,
        "open_rename_storage_flow",
        record_rename_attempt,
    )
    monkeypatch.setattr(editor, "exit", lambda: exit_calls.append(None))

    async with editor.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#storage-move")
        await asyncio.wait_for(started.wait(), timeout=1)
        await pilot.pause()

        assert editor._config_action_in_progress is True
        assert editor.query_one("#config-setup", Button).disabled is True
        assert editor.query_one("#storage-list", ListView).disabled is True
        assert editor.query_one("#field-table", DataTable).disabled is True
        for button_id in (
            "storage-new",
            "storage-register-active",
            "storage-rename",
            "storage-location",
            "storage-move",
            "storage-archive",
            "storage-delete",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is True

        await editor.action_quit()
        assert exit_calls == []

        await pilot.click("#storage-rename")
        await pilot.pause()
        assert rename_calls == []

        finish.set()
        await pilot.pause()
        await pilot.pause()

        assert editor._config_action_in_progress is False
        assert editor.query_one("#storage-list", ListView).disabled is False
        assert editor.query_one("#storage-move", Button).disabled is False

        await editor.action_quit()
        assert exit_calls == [None]


@pytest.mark.asyncio
async def test_editor_storage_edit_controls_repair_missing_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=storage_root,
        path=index_path,
    )
    shutil.rmtree(storage_root)
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await pilot.pause()

        for button_id in (
            "storage-rename",
            "storage-location",
            "storage-delete",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is False
        for button_id in ("storage-move", "storage-archive"):
            assert editor.query_one(f"#{button_id}", Button).disabled is True


@pytest.mark.asyncio
async def test_editor_storage_edit_controls_disable_for_archived_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    archive_path = tmp_path / "alpha.apprc.tar.xz"
    archive_path.write_bytes(b"placeholder")
    registry = record_archived_storage(
        name="alpha",
        archive=archive_path,
        source_root=tmp_path / "alpha",
        path=index_path,
    )
    editor = ConfigEditorApp(kit=kit, storage_registry=registry)

    async with editor.run_test() as pilot:
        await pilot.pause()

        for button_id in (
            "storage-register-active",
            "storage-rename",
            "storage-location",
            "storage-move",
            "storage-archive",
            "storage-delete",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is True


@pytest.mark.asyncio
async def test_editor_storage_edit_controls_disable_for_unregistered_active_path(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    active_root = tmp_path / "active"
    registry = register_storage(
        name="alpha",
        root=tmp_path / "registered-alpha",
        path=index_path,
    )
    active_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
        active_storage_root=active_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert (
            editor.query_one("#storage-register-active", Button).disabled
            is False
        )
        for button_id in (
            "storage-rename",
            "storage-location",
            "storage-move",
            "storage-archive",
            "storage-delete",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is True


@pytest.mark.asyncio
async def test_editor_rename_storage_warns_about_external_selectors(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    archive_path = tmp_path / "alpha.apprc.tar.xz"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    registry = record_archived_storage(
        name="alpha",
        archive=archive_path,
        source_root=source_root,
        path=index_path,
    )
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[StorageNameResult(name="beta"), "rename"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_rename_storage_flow()

    assert isinstance(editor.screens[0], StorageNameScreen)
    assert editor.screens[0].default_name == "alpha"
    assert isinstance(editor.screens[1], ConfirmScreen)
    assert "--storage" in str(editor.screens[1].message)
    assert "environment" in str(editor.screens[1].message)
    assert set(editor.storage_registry.storages) == {"beta"}
    assert set(editor.storage_registry.archived_storages) == {"beta"}
    assert editor.refreshed_names == ["beta"]
    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_editor_rename_storage_ignores_an_unchanged_name(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
    )
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[StorageNameResult(name="alpha")],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_rename_storage_flow()

    assert len(editor.screens) == 1
    assert set(editor.storage_registry.storages) == {"alpha"}
    assert editor.refreshed_names == []


@pytest.mark.asyncio
async def test_editor_location_cancel_keeps_registry_unchanged(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[None],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_storage_location_flow()

    assert len(editor.screens) == 1
    assert (
        editor.storage_registry.selected("alpha").root == source_root.resolve()
    )
    assert editor.refreshed_names == []


@pytest.mark.asyncio
async def test_editor_location_repoints_missing_storage_without_creating_files(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "missing-alpha"
    target_root = tmp_path / "repaired-alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    shutil.rmtree(source_root)
    target_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=MissingStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=target_root), "update"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_storage_location_flow()

    assert isinstance(editor.screens[0], PathInputScreen)
    assert editor.screens[0].value == str(source_root.resolve())
    assert isinstance(editor.screens[1], ConfirmScreen)
    assert "--storage" in str(editor.screens[1].message)
    assert "environment" in str(editor.screens[1].message)
    assert (
        editor.storage_registry.selected("alpha").root == target_root.resolve()
    )
    assert not (target_root / ".env.apprc-storage").exists()
    assert editor.refreshed_names == ["alpha"]


@pytest.mark.asyncio
async def test_editor_location_rejects_missing_destination(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    missing_root = tmp_path / "not-created"
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=missing_root)],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_storage_location_flow()

    assert (
        editor.storage_registry.selected("alpha").root == source_root.resolve()
    )
    assert len(editor.screens) == 1
    assert "does not exist" in editor.notifications[0][0]


@pytest.mark.asyncio
async def test_editor_move_storage_moves_complete_directory_to_new_root(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "moved-alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_move_storage_flow()

    assert isinstance(editor.screens[1], ConfirmScreen)
    assert "Close programs" in str(editor.screens[1].message)
    assert "--storage" in str(editor.screens[1].message)
    assert not source_root.exists()
    assert (destination_root / "payload.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert (destination_root / ".env.apprc-storage").is_file()
    assert editor.storage_registry.selected("alpha").root == destination_root
    assert editor.refreshed_names == ["alpha"]


@pytest.mark.asyncio
async def test_editor_move_storage_uses_empty_destination_as_root(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_move_storage_flow()

    assert (destination_root / "payload.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert not (destination_root / source_root.name).exists()
    assert not list(tmp_path.glob(".empty-destination.apprc-empty-*"))


@pytest.mark.asyncio
async def test_editor_move_storage_restores_empty_destination_when_filesystem_rename_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    original_replace = os.replace

    def fail_source_rename(source: Path, destination: Path) -> None:
        if source == source_root and destination == destination_root:
            raise OSError("rename blocked")
        original_replace(source, destination)

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing.os.replace",
        fail_source_rename,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert not list(tmp_path.glob(".empty-destination.apprc-empty-*"))
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "error"


@pytest.mark.asyncio
async def test_editor_move_storage_rejects_unsafe_destinations(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    populated_root = tmp_path / "populated"
    populated_root.mkdir()
    (populated_root / "existing.txt").write_text("keep", encoding="utf-8")
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    assert (
        workflow._move_destination(
            source_root=source_root.resolve(),
            candidate=source_root / "nested",
        )
        is None
    )
    assert (
        workflow._move_destination(
            source_root=source_root.resolve(),
            candidate=populated_root,
        )
        is None
    )
    assert len(editor.notifications) == 2


@pytest.mark.asyncio
async def test_editor_move_storage_rejects_another_live_selector_at_source(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    registry = register_storage(
        name="beta",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_move_storage_flow()

    assert editor.screens == []
    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.storage_registry.selected("beta").root == source_root
    assert "'beta'" in editor.notifications[0][0]


@pytest.mark.asyncio
async def test_editor_move_storage_rejects_symbolic_link_root(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    target_root = tmp_path / "alpha-target"
    target_root.mkdir()
    (target_root / "payload.txt").write_text("keep", encoding="utf-8")
    symbolic_root = tmp_path / "alpha-link"
    try:
        symbolic_root.symlink_to(target_root, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable in this test environment.")
    registry = StorageRegistry(
        path=index_path,
        storages={"alpha": StorageRecord(name="alpha", root=symbolic_root)},
    )
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_move_storage_flow()

    assert editor.screens == []
    assert symbolic_root.is_symlink()
    assert (target_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert "symbolic links" in editor.notifications[0][0]


@pytest.mark.asyncio
async def test_editor_location_repoints_symbolic_link_root_before_move(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    target_root = tmp_path / "alpha-target"
    target_root.mkdir()
    (target_root / "payload.txt").write_text("keep", encoding="utf-8")
    symbolic_root = tmp_path / "alpha-link"
    try:
        symbolic_root.symlink_to(target_root, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable in this test environment.")
    registry = StorageRegistry(
        path=index_path,
        storages={"alpha": StorageRecord(name="alpha", root=symbolic_root)},
    )
    write_storage_registry(registry)
    destination_root = tmp_path / "moved-alpha"
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[
            PathInputResult(path=target_root),
            "update",
            PathInputResult(path=destination_root),
            "move",
        ],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    await workflow.open_storage_location_flow()

    assert editor.storage_registry.selected("alpha").root == target_root
    editor.selection = LiveStorageSelection(
        editor.storage_registry.selected("alpha")
    )
    await workflow.open_move_storage_flow()

    assert not target_root.exists()
    assert (destination_root / "payload.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert editor.storage_registry.selected("alpha").root == destination_root


@pytest.mark.asyncio
async def test_editor_move_storage_restores_source_after_registry_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))

    def fail_registry_update(**_: object) -> StorageRegistry:
        raise OSError("write blocked")

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing._update_storage",
        fail_registry_update,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "error"


@pytest.mark.asyncio
async def test_editor_move_storage_copies_across_filesystems_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "moved-alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )

    await workflow.open_move_storage_flow()

    assert not source_root.exists()
    assert (destination_root / "payload.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert editor.storage_registry.selected("alpha").root == destination_root


@pytest.mark.asyncio
async def test_editor_move_storage_cancels_changed_cross_filesystem_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "moved-alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )
    original_copytree = shutil.copytree

    def copy_tree_then_change_source(
        source: Path,
        destination: Path,
        **kwargs: Any,
    ) -> Path:
        original_copytree(source, destination, **kwargs)
        (source / "written-during-move.txt").write_text(
            "keep this too",
            encoding="utf-8",
        )
        return destination

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing.shutil.copytree",
        copy_tree_then_change_source,
    )

    await workflow.open_move_storage_flow()

    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert (source_root / "written-during-move.txt").read_text(
        encoding="utf-8"
    ) == "keep this too"
    assert editor.storage_registry.selected("alpha").root == source_root
    assert not list(tmp_path.glob(".moved-alpha.apprc-moving-*"))
    assert not list(tmp_path.glob(".moved-alpha.apprc-empty-*"))
    assert editor.notifications[-1][1]["severity"] == "error"
    assert "registry was not updated" in editor.notifications[-1][0]


@pytest.mark.asyncio
async def test_editor_move_storage_restores_empty_destination_when_source_check_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )
    original_snapshot = workflow._directory_snapshot
    snapshot_calls = 0

    def fail_source_check_snapshot(root: Path) -> tuple[object, ...]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            raise OSError("source check blocked")
        return original_snapshot(root)

    monkeypatch.setattr(
        workflow,
        "_directory_snapshot",
        fail_source_check_snapshot,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert not list(tmp_path.glob(".empty-destination.apprc-empty-*"))
    assert list(tmp_path.glob(".empty-destination.apprc-moving-*"))
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "warning"
    assert "registry was not updated" in editor.notifications[-1][0]


@pytest.mark.asyncio
async def test_editor_move_storage_restores_empty_destination_when_copy_promotion_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )
    original_replace = os.replace

    def fail_copy_promotion(source: Path, destination: Path) -> None:
        if (
            source.name.startswith(".empty-destination.apprc-moving-")
            and destination == destination_root
        ):
            raise OSError("promotion blocked")
        original_replace(source, destination)

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing.os.replace",
        fail_copy_promotion,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert not list(tmp_path.glob(".empty-destination.apprc-moving-*"))
    assert not list(tmp_path.glob(".empty-destination.apprc-empty-*"))
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "error"


@pytest.mark.asyncio
async def test_editor_move_storage_warns_when_cross_filesystem_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "moved-alpha"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )

    def fail_source_cleanup(path: Path, *_: object, **__: object) -> None:
        assert path == source_root
        raise OSError("source cleanup blocked")

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing.shutil.rmtree",
        fail_source_cleanup,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert (destination_root / "payload.txt").read_text(
        encoding="utf-8"
    ) == "keep"
    assert editor.storage_registry.selected("alpha").root == destination_root
    assert editor.notifications[-2][1]["severity"] == "warning"
    assert editor.notifications[-1][0] == "Moved storage 'alpha'"


@pytest.mark.asyncio
async def test_editor_move_storage_restores_empty_destination_when_copy_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )

    def fail_copytree(
        source: Path,
        destination: Path,
        **_: object,
    ) -> None:
        (destination / "partial.txt").write_text("partial", encoding="utf-8")
        raise shutil.Error("copy blocked")

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing.shutil.copytree",
        fail_copytree,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert not list(tmp_path.glob(".empty-destination.apprc-moving-*"))
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "error"


@pytest.mark.asyncio
async def test_editor_move_storage_rolls_back_cross_filesystem_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    destination_root = tmp_path / "empty-destination"
    registry = register_storage(
        name="alpha",
        root=source_root,
        path=index_path,
    )
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    destination_root.mkdir()
    editor = StorageEditingFakeEditor(
        registry=registry,
        selection=LiveStorageSelection(registry.selected("alpha")),
        responses=[PathInputResult(path=destination_root), "move"],
    )
    workflow = StorageEditingWorkflows(cast(Any, editor))
    monkeypatch.setattr(
        workflow,
        "_move_requires_copy",
        lambda **_: True,
    )

    def fail_registry_update(**_: object) -> StorageRegistry:
        raise OSError("write blocked")

    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_editing._update_storage",
        fail_registry_update,
    )

    await workflow.open_move_storage_flow()

    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert destination_root.is_dir()
    assert not any(destination_root.iterdir())
    assert editor.storage_registry.selected("alpha").root == source_root
    assert editor.notifications[-1][1]["severity"] == "error"


@pytest.mark.asyncio
async def test_editor_new_storage_archive_path_opens_import_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "alpha.apprc.tar.xz"
    editor = NewStorageFakeEditor(responses=[SimpleNamespace(path=archive)])
    workflow = ConfigEditorStorageWorkflows(cast(Any, editor))
    imported: list[Path] = []
    registered: list[Path] = []

    async def open_archive_import_flow(path: Path) -> None:
        imported.append(path)

    async def register_storage_directory_flow(
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        registered.append(storage_root)

    monkeypatch.setattr(
        workflow,
        "open_archive_import_flow",
        open_archive_import_flow,
    )
    monkeypatch.setattr(
        workflow,
        "register_storage_directory_flow",
        register_storage_directory_flow,
    )

    await workflow.open_new_storage_flow()

    assert imported == [archive]
    assert registered == []


@pytest.mark.asyncio
async def test_editor_new_storage_creates_first_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Persist the first named storage from an empty in-memory registry.

    :param monkeypatch: Fixture used to script modal answers.
    :param tmp_path: Temporary root for the index and storage directory.
    """
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "config" / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_storage_registry_or_empty(index_path),
    )
    responses: list[object | None] = [
        PathInputResult(path=storage_root),
        "create",
        StorageNameResult(name="alpha"),
    ]

    async def push_screen_wait(_: object) -> object | None:
        return responses.pop(0)

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor.storage_workflows.open_new_storage_flow()

    assert index_path.is_file()
    assert (storage_root / ".env.apprc-storage").is_file()
    assert editor.storage_registry is not None
    assert editor.storage_registry.selected("alpha").root == (
        storage_root.resolve()
    )


@pytest.mark.asyncio
async def test_editor_restore_replacement_mode_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "alpha.apprc.tar.xz"
    archive.write_bytes(b"placeholder")
    destination = tmp_path / "alpha"
    destination.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    editor = RestoreFakeEditor(
        responses=[SimpleNamespace(path=destination), "confirm"],
    )
    workflow = ConfigEditorStorageWorkflows(cast(Any, editor))
    replace_modes: list[bool] = []
    registered: list[Path] = []

    async def run_extract_progress(
        *,
        archive_path: Path,
        destination_root: Path,
        replace_existing: bool = False,
    ) -> Path:
        replace_modes.append(replace_existing)
        return destination_root

    async def register_storage_directory_flow(
        storage_root: Path,
        *,
        default_name: str,
    ) -> None:
        registered.append(storage_root)

    monkeypatch.setattr(
        workflow,
        "run_extract_progress",
        run_extract_progress,
    )
    monkeypatch.setattr(
        workflow,
        "register_storage_directory_flow",
        register_storage_directory_flow,
    )

    await workflow.open_archive_import_flow(archive)

    assert replace_modes == [True]
    assert registered == [destination.resolve()]


@pytest.mark.asyncio
async def test_editor_restore_cancel_does_not_replace_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "alpha.apprc.tar.xz"
    archive.write_bytes(b"placeholder")
    destination = tmp_path / "alpha"
    destination.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    editor = RestoreFakeEditor(
        responses=[SimpleNamespace(path=destination), None]
    )
    workflow = ConfigEditorStorageWorkflows(cast(Any, editor))
    extract_called = False

    async def run_extract_progress(
        *,
        archive_path: Path,
        destination_root: Path,
        replace_existing: bool = False,
    ) -> Path:
        nonlocal extract_called
        extract_called = True
        return destination_root

    monkeypatch.setattr(
        workflow,
        "run_extract_progress",
        run_extract_progress,
    )

    await workflow.open_archive_import_flow(archive)

    assert extract_called is False
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_editor_storage_delete_unregisters_before_content_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    register_storage(name="alpha", root=storage_root, path=index_path)
    registry = load_storage_registry_or_empty(index_path)
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
    )
    notifications: list[tuple[str, dict[str, object]]] = []

    async def refresh_storage_list(
        *,
        select_name: str | None = None,
    ) -> None:
        return None

    def notify(message: str, **kwargs: object) -> None:
        notifications.append((message, kwargs))

    def fail_rmtree(path: Path) -> None:
        raise OSError("blocked")

    monkeypatch.setattr(editor, "_refresh_storage_list", refresh_storage_list)
    monkeypatch.setattr(editor, "_registered_active_storage_name", lambda: None)
    monkeypatch.setattr(editor, "notify", notify)
    monkeypatch.setattr(
        "apprc.interfaces.tui.editor.storage_removal.shutil.rmtree",
        fail_rmtree,
    )

    removed = await editor.storage_workflows.remove_live_storage(
        "alpha",
        delete_content=True,
    )

    assert removed is True
    assert load_storage_registry_or_empty(index_path).storages == {}
    assert storage_root.exists()
    assert notifications[-1][1]["severity"] == "warning"


@pytest.mark.asyncio
async def test_editor_storage_registration_shows_rollback_cleanup_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_storage_registry_or_empty(index_path),
    )
    responses: list[object | None] = [StorageNameResult(name="alpha")]
    notifications: list[tuple[str, dict[str, object]]] = []
    original_unlink = Path.unlink

    async def push_screen_wait(screen: object) -> object | None:
        return responses.pop(0)

    async def refresh_storage_list(
        *,
        select_name: str | None = None,
    ) -> None:
        return None

    def notify(message: str, **kwargs: object) -> None:
        notifications.append((message, kwargs))

    def fail_write(_: object) -> None:
        raise OSError("blocked")

    def fail_storage_env_unlink(
        self: Path,
        missing_ok: bool = False,
    ) -> None:
        if self.name == ".env.apprc-storage":
            raise OSError("unlink blocked")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(editor, "push_screen_wait", push_screen_wait)
    monkeypatch.setattr(editor, "_refresh_storage_list", refresh_storage_list)
    monkeypatch.setattr(editor, "notify", notify)
    monkeypatch.setattr(
        "apprc.user_files.storage_roots.registry.write_storage_registry",
        fail_write,
    )
    monkeypatch.setattr(Path, "unlink", fail_storage_env_unlink)

    await editor.storage_workflows.register_storage_directory_flow(
        storage_root,
        default_name="alpha",
    )

    assert notifications[0][1]["severity"] == "error"
    assert "blocked" in notifications[0][0]
    assert any(
        kwargs["severity"] == "warning"
        and "remove empty storage env file" in message
        for message, kwargs in notifications
    )


@pytest.mark.asyncio
async def test_editor_open_does_not_create_storage_env_file(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        table = editor.query_one("#field-table", DataTable)

        assert not (storage_root / ".env.apprc-storage").exists()
        assert table.row_count > 0


@pytest.mark.asyncio
async def test_editor_enables_first_storage_actions_with_empty_registry(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    index_path = tmp_path / "config" / "demo.apprc.toml"
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=load_storage_registry_or_empty(index_path),
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#config-setup", Button).disabled is False
        assert editor.query_one("#storage-new", Button).disabled is False
        assert (
            editor.query_one("#storage-register-active", Button).disabled
            is False
        )
        for button_id in (
            "storage-rename",
            "storage-location",
            "storage-move",
        ):
            assert editor.query_one(f"#{button_id}", Button).disabled is True
        assert not index_path.exists()


@pytest.mark.asyncio
async def test_editor_blocks_named_storage_writes_after_index_error(
    tmp_path: Path,
) -> None:
    """Keep setup available without replacing an invalid existing index.

    :param tmp_path: Temporary root for the active storage path.
    """
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        storage_registry_error="Named-storage index is invalid.",
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#config-setup", Button).disabled is False
        assert editor.query_one("#storage-new", Button).disabled is True
        assert (
            editor.query_one("#storage-register-active", Button).disabled
            is True
        )


@pytest.mark.asyncio
async def test_editor_hides_storage_management_for_storage_free_app() -> None:
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#config-setup", Button).disabled is False
        assert list(editor.query("#storage-list")) == []
        for button_id in (
            "storage-new",
            "storage-rename",
            "storage-location",
            "storage-move",
        ):
            assert list(editor.query(f"#{button_id}")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0


@pytest.mark.asyncio
async def test_editor_hides_named_storage_controls_when_disabled(
    tmp_path: Path,
) -> None:
    kit = AppConfigKit(
        app_name="path_only_app",
        display_name="Path-Only App",
        config_package="apprc",
        envs=(ApprcExampleAppEnv,),
        storage_env_key="PATH_ONLY_APP_STORAGE",
        storage_layer=StorageLayerState.REQUIRED,
        named_storage_layer=CapabilityState.DISABLED,
        index_filename="path_only_app.apprc.toml",
    )
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#config-setup", Button).disabled is False
        assert list(editor.query("#storage-list")) == []
        for button_id in (
            "storage-new",
            "storage-rename",
            "storage-location",
            "storage-move",
        ):
            assert list(editor.query(f"#{button_id}")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0
        assert not (storage_root / ".env.apprc-storage").exists()


@pytest.mark.asyncio
async def test_editor_saving_to_app_creates_only_app_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        app_wide_env = kit.spec.app_wide_env_path()

        assert not app_wide_env.exists()
        editor._save_env_key(
            "STORAGE_FREE_APP_PROFILE",
            "app-profile",
            scope="app",
        )

        assert app_wide_env.is_file()
        assert 'STORAGE_FREE_APP_PROFILE="app-profile"\n' in (
            app_wide_env.read_text(encoding="utf-8")
        )


@pytest.mark.asyncio
async def test_editor_saving_to_storage_creates_only_storage_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=storage_root,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()
        storage_env = storage_root / ".env.apprc-storage"
        app_wide_env = kit.spec.app_wide_env_path()

        assert not storage_env.exists()
        assert not app_wide_env.exists()
        editor._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "storage-profile",
            scope="storage",
        )

        assert storage_env.is_file()
        assert not app_wide_env.exists()
        assert 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n' in (
            storage_env.read_text(encoding="utf-8")
        )
