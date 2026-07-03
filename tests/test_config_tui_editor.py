from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from textual.widgets import Button, DataTable

from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.tui._primitives import StorageNameResult
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
    register_storage,
)
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
async def test_editor_disables_named_storage_controls_without_index(
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

        assert list(editor.query("#storage-list")) == []
        assert list(editor.query("#storage-new")) == []
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

        assert list(editor.query("#storage-list")) == []
        assert list(editor.query("#storage-new")) == []
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
