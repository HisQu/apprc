from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Static
from typer.testing import CliRunner

from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.interfaces.tui._primitives import ConfirmScreen
from apprc.user_files.storage_roots.registry import (
    StorageRecord,
    StorageRegistry,
    register_storage,
    write_storage_registry,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelectorInput,
    StorageSelectorIssue,
)
from tests.support_config import (
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_editor_uses_fixed_dotenv_and_registry_labels() -> None:
    kit = build_apprc_example_app_kit()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        active_storage_root=Path("/tmp/storage"),
    )

    assert editor.kit.spec.storage_dotenv_filename == "apprc.storage.env"
    assert editor.apprc_toml_label == "apprc.toml"
    assert editor.init_command.endswith("config storage add NAME PATH")


@pytest.mark.asyncio
async def test_editor_hides_storage_controls_for_storage_free_app() -> None:
    editor = ConfigEditorApp(
        kit=build_storage_free_example_kit(),
        storage_registry=None,
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#storage-list")) == []
        for button_id in (
            "storage-new",
            "storage-rename",
            "storage-location",
            "storage-move",
        ):
            assert list(editor.query(f"#{button_id}")) == []
        assert editor.query_one("#field-table", DataTable).row_count > 0
        setup = editor.query_one("#config-setup", Button)
        assert str(setup.label) == "Set up user dotenv..."
        assert (
            "user dotenv is not set up"
            in str(editor.query_one("#scope-title", Static).content).lower()
        )


@pytest.mark.asyncio
async def test_editor_hides_setup_after_user_dotenv_is_initialized() -> None:
    kit = build_storage_free_example_kit()
    kit.spec.ensure_user_dotenv()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#config-setup")) == []
        scope_text = str(editor.query_one("#scope-title", Static).content)
        assert "User dotenv:" in scope_text
        assert str(kit.spec.user_dotenv_path()) in scope_text


@pytest.mark.asyncio
async def test_editor_exposes_every_user_registered_storage(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    registry_path = kit.spec.preferred_apprc_toml_path()
    registry = register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=registry_path,
    )
    registry = register_storage(
        name="beta",
        root=tmp_path / "beta",
        path=registry_path,
    )
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
        initial_storage="alpha",
        active_storage_root=tmp_path / "alpha",
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert editor.query_one("#storage-list").children.__len__() == 2
        assert editor.query_one("#storage-new", Button).disabled is False


@pytest.mark.asyncio
async def test_editor_saving_user_value_creates_only_user_dotenv() -> None:
    kit = build_storage_free_example_kit()
    kit.spec.ensure_user_dotenv()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)

    async with editor.run_test() as pilot:
        await pilot.pause()
        user_dotenv = kit.spec.user_dotenv_path()
        await editor._save_env_key(
            "STORAGE_FREE_APP_PROFILE",
            "user-profile",
            scope="user",
        )

        assert user_dotenv.read_text(encoding="utf-8") == (
            'STORAGE_FREE_APP_PROFILE="user-profile"\n'
        )
        assert not kit.spec.preferred_apprc_toml_path().exists()


@pytest.mark.asyncio
async def test_editor_saving_storage_value_creates_only_storage_dotenv(
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
        await editor._save_env_key(
            "APPRC_EXAMPLE_APP_PROFILE",
            "storage-profile",
            scope="storage",
        )

        assert (
            kit.spec.storage_dotenv_path(storage_root).read_text(
                encoding="utf-8"
            )
            == 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n'
        )
        assert not kit.spec.user_dotenv_path().exists()


@pytest.mark.asyncio
async def test_editor_duplicate_warning_cancels_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = build_storage_free_example_kit()
    user_dotenv = kit.spec.ensure_user_dotenv()
    editor = ConfigEditorApp(kit=kit, storage_registry=None)
    original = (
        "STORAGE_FREE_APP_PROFILE=first\nSTORAGE_FREE_APP_PROFILE=second\n"
    )
    user_dotenv.write_text(original, encoding="utf-8")
    shown_screens: list[object] = []

    async def cancel(screen: object) -> object | None:
        """Capture the confirmation and decline the write."""
        shown_screens.append(screen)
        return None

    monkeypatch.setattr(editor, "push_screen_wait", cancel)

    async with editor.run_test() as pilot:
        await pilot.pause()
        await editor._save_env_key(
            "STORAGE_FREE_APP_PROFILE",
            "new",
            scope="user",
        )

    assert len(shown_screens) == 1
    assert isinstance(shown_screens[0], ConfirmScreen)
    assert user_dotenv.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_editor_disables_storage_fields_until_marker_exists(
    tmp_path: Path,
) -> None:
    """A directory alone is not an initialized AppRC storage.

    :param tmp_path: Isolated uninitialized storage directory.
    """
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

        assert editor.query_one("#field-table", DataTable).disabled is True
        assert editor.query_one("#config-setup", Button).disabled is False
        assert "Missing AppRC marker" in str(
            editor.query_one("#scope-title", Static).content
        )


@pytest.mark.asyncio
async def test_editor_keeps_selector_failure_separate_from_setup() -> None:
    """A selector error does not claim that managed files need setup."""
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=None,
        storage_registry_error="apprc.toml is malformed",
        storage_selector_issue=StorageSelectorIssue(
            selector=StorageSelectorInput(
                source="APPRC_EXAMPLE_APP_STORAGE",
                raw_value="broken",
                source_kind="process_environment",
            ),
            message="Unknown storage 'broken'",
        ),
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        status = editor.query_one("#selector-status", Static)
        assert "Unknown storage 'broken'" in str(status.content)
        assert "process environment" in str(status.content)
        assert list(editor.query("#config-setup")) == []


@pytest.mark.asyncio
async def test_editor_keeps_registered_storages_usable_with_bad_override(
    tmp_path: Path,
) -> None:
    """An invalid shell selector must not hide valid registry entries.

    :param tmp_path: Isolated storage parent.
    """
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    registry = register_storage(
        name="opa",
        root=tmp_path / "opa",
        path=kit.spec.preferred_apprc_toml_path(),
    )
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
        initial_storage="opa",
        storage_selector_issue=StorageSelectorIssue(
            selector=StorageSelectorInput(
                source="APPRC_EXAMPLE_APP_STORAGE",
                raw_value="ontology",
                source_kind="process_environment",
            ),
            message="Unknown storage 'ontology'. Known storages: opa.",
            configured_storage="opa",
        ),
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        status = str(editor.query_one("#selector-status", Static).content)
        assert "overrides selected_storage='opa'" in status
        assert "Registered storages: opa" in status
        assert len(editor.query_one("#storage-list").children) == 1
        assert editor.query_one("#field-table", DataTable).disabled is False
        assert list(editor.query("#config-setup")) == []
        assert str(editor.query_one("#storage-location", Button).label) == (
            "Reconnect"
        )


@pytest.mark.asyncio
async def test_editor_offers_reconnect_for_missing_registered_root(
    tmp_path: Path,
) -> None:
    """A missing registered directory is not a setup operation.

    :param tmp_path: Isolated storage parent.
    """
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_user_dotenv()
    root = tmp_path / "manually-moved"
    registry = StorageRegistry(
        path=kit.spec.preferred_apprc_toml_path(),
        storages={"opa": StorageRecord(name="opa", root=root)},
        selected_storage="opa",
        archived_storages={},
    )
    write_storage_registry(registry)
    editor = ConfigEditorApp(
        kit=kit,
        storage_registry=registry,
        initial_storage="opa",
    )

    async with editor.run_test() as pilot:
        await pilot.pause()

        assert list(editor.query("#config-setup")) == []
        reconnect = editor.query_one("#storage-location", Button)
        assert str(reconnect.label) == "Reconnect"
        assert reconnect.disabled is False
        scope = str(editor.query_one("#scope-title", Static).content)
        assert "Missing storage root" in scope


def test_config_edit_opens_when_storage_selector_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Editor startup converts selector failures into repairable state.

    :param monkeypatch: Process environment mutation fixture.
    :param tmp_path: Isolated AppRC directory.
    """
    kit = build_apprc_example_app_kit()
    monkeypatch.setenv(
        kit.spec.apprc_dir_env_key,
        str(tmp_path / "apprc"),
    )
    monkeypatch.setenv(
        kit.spec.require_storage_selector_env_key(),
        "unknown",
    )
    kit.spec.ensure_user_dotenv()
    register_storage(
        name="opa",
        root=tmp_path / "opa",
        path=kit.spec.preferred_apprc_toml_path(),
    )
    launched: list[tuple[StorageSelectorIssue | None, tuple[str, ...]]] = []

    class HeadlessEditor(ConfigEditorApp):
        """Record editor launch without starting a terminal application."""

        def run(self, *args: object, **kwargs: object) -> None:
            """Record one launch attempt.

            :param args: Ignored Textual positional arguments.
            :param kwargs: Ignored Textual keyword arguments.
            :return: None.
            """
            registry = self.storage_registry
            launched.append(
                (
                    self.storage_selector_issue,
                    tuple(registry.storages) if registry is not None else (),
                )
            )

    app = kit.typer_app(editor_app_cls=HeadlessEditor)

    result = CliRunner().invoke(app, ["edit"])

    assert result.exit_code == 0, result.output
    assert len(launched) == 1
    issue, storage_names = launched[0]
    assert issue is not None
    assert issue.selector is not None
    assert issue.selector.raw_value == "unknown"
    assert issue.selector.source_kind == "process_environment"
    assert issue.configured_storage == "opa"
    assert storage_names == ("opa",)
