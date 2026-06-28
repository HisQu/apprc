from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from apprc.runtime_config.app_spec import CapabilityState
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.registry import StorageRegistry
from apprc.runtime_config.tui.editor import ConfigEditorApp
from tests.support_config import (
    ApprcExampleAppConfigState,
    StorageFreeExampleEnv,
    StorageFreeExampleConfigState,
    StorageFreeExampleConfigStateWithoutStorage,
    apprc_example_app_state,
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


class CapturingConfigEditorApp(ConfigEditorApp):
    """Test editor that records launch state without starting Textual."""

    active_storage_root_seen: ClassVar[Path | None] = None
    storage_registry_seen: ClassVar[StorageRegistry | None] = None
    initial_storage_seen: ClassVar[str | None] = None
    run_count: ClassVar[int] = 0

    @classmethod
    def reset(cls) -> None:
        """Clear captured constructor and run values."""
        cls.active_storage_root_seen = None
        cls.storage_registry_seen = None
        cls.initial_storage_seen = None
        cls.run_count = 0

    def __init__(
        self,
        *,
        kit: AppConfigKit,
        storage_registry: StorageRegistry | None,
        initial_storage: str | None = None,
        active_storage_root: Path | None = None,
    ) -> None:
        """Record editor launch arguments."""
        super().__init__(
            kit=kit,
            storage_registry=storage_registry,
            initial_storage=initial_storage,
            active_storage_root=active_storage_root,
        )
        type(self).active_storage_root_seen = self.active_storage_root
        type(self).storage_registry_seen = storage_registry
        type(self).initial_storage_seen = initial_storage

    def run(self, *args: object, **kwargs: object) -> None:
        """Record that the editor would have launched."""
        type(self).run_count += 1


def test_config_paths_reports_zero_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["writes"] == "none"
    assert payload["capabilities"] == {
        "app_wide": "optional",
        "named_storage": "optional",
        "storage": "required",
    }
    assert not Path(payload["app_wide_env"]).exists()
    assert not Path(payload["index_path"]).exists()


def test_config_app_init_creates_app_wide_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    app = kit.typer_app(state_type=StorageFreeExampleConfigState)

    result = CliRunner().invoke(app, ["app", "init"])

    assert result.exit_code == 0, result.output
    assert kit.spec.app_wide_env_path().is_file()
    assert "app_wide_env:" in result.output


def test_config_storage_add_list_and_remove(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    index_path = tmp_path / "config" / "demo.apprc.toml"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(index_path))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()
    storage_root = tmp_path / "alpha"

    add = runner.invoke(
        app,
        ["storage", "add", "alpha", str(storage_root), "--yes"],
    )
    listed = runner.invoke(app, ["storage", "list", "--json"])
    removed = runner.invoke(app, ["storage", "remove", "alpha"])
    listed_after = runner.invoke(app, ["storage", "list", "--json"])

    assert add.exit_code == 0, add.output
    assert index_path.is_file()
    assert (storage_root / ".env.apprc-storage").is_file()
    assert json.loads(listed.output)["storages"][0]["name"] == "alpha"
    assert removed.exit_code == 0, removed.output
    assert json.loads(listed_after.output)["storages"] == []


def test_config_set_infers_storage_scope(tmp_path: Path) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = apprc_example_app_state(kit, storage_root)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)

    result = CliRunner().invoke(
        app,
        ["set", "app.profile", "storage-profile"],
        obj=state,
    )

    assert result.exit_code == 0, result.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="storage-profile"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")
    assert "storage_env:" in result.output


def test_config_set_requires_scope_when_app_and_storage_are_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    kit.spec.ensure_app_wide_env()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = apprc_example_app_state(kit, storage_root)
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    runner = CliRunner()

    ambiguous = runner.invoke(
        app,
        ["set", "app.profile", "ambiguous"],
        obj=state,
    )
    app_scoped = runner.invoke(
        app,
        ["set", "app.profile", "app-profile", "--scope", "app"],
        obj=state,
    )

    assert ambiguous.exit_code != 0
    assert "--scope app or --scope storage" in ambiguous.output
    assert app_scoped.exit_code == 0, app_scoped.output
    assert 'APPRC_EXAMPLE_APP_PROFILE="app-profile"\n' in (
        kit.spec.app_wide_env_path().read_text(encoding="utf-8")
    )


def test_config_setup_storage_only_writes_only_storage_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    app = kit.typer_app(state_type=ApprcExampleAppConfigState)
    storage_root = tmp_path / "storage"

    result = CliRunner().invoke(
        app,
        ["setup", "--yes", "--storage-root", str(storage_root)],
    )

    assert result.exit_code == 0, result.output
    assert (storage_root / ".env.apprc-storage").is_file()
    assert not kit.spec.app_wide_env_path().exists()
    assert not kit.spec.index_path().exists()


def test_disabled_capability_command_groups_are_absent() -> None:
    storage_free = build_storage_free_example_kit()
    storage_free_app = storage_free.typer_app(
        state_type=StorageFreeExampleConfigState,
    )
    app_disabled = AppConfigKit(
        app_name="env_app",
        display_name="Env App",
        config_package="apprc.runtime_config",
        envs=(StorageFreeExampleEnv,),
        app_wide_layer=CapabilityState.DISABLED,
        index_filename="env_app.apprc.toml",
    )
    app_disabled_cli = app_disabled.typer_app(
        state_type=StorageFreeExampleConfigState,
    )
    runner = CliRunner()

    storage_help = runner.invoke(storage_free_app, ["--help"])
    storage_command = runner.invoke(storage_free_app, ["storage", "list"])
    app_help = runner.invoke(app_disabled_cli, ["--help"])
    app_command = runner.invoke(app_disabled_cli, ["app", "init"])

    assert storage_help.exit_code == 0, storage_help.output
    assert "storage" not in storage_help.output
    assert storage_command.exit_code != 0
    assert app_help.exit_code == 0, app_help.output
    assert "app" not in app_help.output
    assert app_command.exit_code != 0


def test_config_edit_uses_root_storage_path_with_corrupt_optional_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    state = ApprcExampleAppConfigState(
        env_bootstrap=None,
        storage=str(storage_root),
    )
    CapturingConfigEditorApp.reset()
    app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        editor_app_cls=CapturingConfigEditorApp,
    )

    result = CliRunner().invoke(app, ["edit"], obj=state)

    assert result.exit_code == 0, result.output
    assert CapturingConfigEditorApp.run_count == 1
    assert CapturingConfigEditorApp.active_storage_root_seen == (
        storage_root.resolve()
    )
    assert CapturingConfigEditorApp.storage_registry_seen is None
    assert not (storage_root / ".env.apprc-storage").exists()


def test_config_edit_ignores_corrupt_optional_index_without_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")
    state = ApprcExampleAppConfigState(env_bootstrap=None, storage=None)
    CapturingConfigEditorApp.reset()
    app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        editor_app_cls=CapturingConfigEditorApp,
    )

    result = CliRunner().invoke(app, ["edit"], obj=state)

    assert result.exit_code == 0, result.output
    assert CapturingConfigEditorApp.run_count == 1
    assert CapturingConfigEditorApp.active_storage_root_seen is None
    assert CapturingConfigEditorApp.storage_registry_seen is None
    assert not kit.spec.app_wide_env_path().exists()


def test_storage_free_config_edit_accepts_state_without_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = build_storage_free_example_kit()
    state = StorageFreeExampleConfigStateWithoutStorage()
    CapturingConfigEditorApp.reset()
    app = kit.typer_app(
        state_type=StorageFreeExampleConfigStateWithoutStorage,
        editor_app_cls=CapturingConfigEditorApp,
    )

    result = CliRunner().invoke(app, ["edit"], obj=state)

    assert result.exit_code == 0, result.output
    assert CapturingConfigEditorApp.run_count == 1
    assert CapturingConfigEditorApp.initial_storage_seen is None
    assert CapturingConfigEditorApp.active_storage_root_seen is None
    assert CapturingConfigEditorApp.storage_registry_seen is None
