from __future__ import annotations

import builtins
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
import typer
from typer.testing import CliRunner

from apprc.definition.app_config.capabilities import CapabilityState
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli.config_command import ConfigSelectorContext
from apprc.interfaces.tui.editor import ConfigEditorApp
from apprc.user_files.storage_roots.registry import StorageRegistry
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


def root_app_with_config(
    config_app: typer.Typer,
    *,
    state: ApprcExampleAppConfigState,
) -> typer.Typer:
    """Mount a config app below host-level options used by selector tests."""
    app = typer.Typer()

    @app.callback()
    def root_cmd(
        ctx: typer.Context,
        env_files: list[Path] | None = typer.Option(None, "--env-file"),
        env_file_overrides_os_environ: bool = typer.Option(
            False,
            "--env-file-overrides-os-environ",
        ),
    ) -> None:
        """Store root params and the test state for child commands."""
        ctx.obj = state

    app.add_typer(config_app, name="config")
    return app


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


def test_context_aware_active_storage_hook_receives_selector_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("APPRC_EXAMPLE_APP_STORAGE", raising=False)
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "selected-storage"
    storage_root.mkdir()
    selector_env = tmp_path / "selector.env"
    selector_env.write_text(
        f"APPRC_EXAMPLE_APP_STORAGE={storage_root}\n",
        encoding="utf-8",
    )
    seen_contexts: list[ConfigSelectorContext] = []

    def active_storage_root_with_context(
        state: ApprcExampleAppConfigState,
        selector_context: ConfigSelectorContext,
    ) -> Path | None:
        seen_contexts.append(selector_context)
        return Path(
            selector_context.explicit_values["APPRC_EXAMPLE_APP_STORAGE"]
        )

    config_app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        active_storage_root_with_context=active_storage_root_with_context,
    )
    app = root_app_with_config(
        config_app,
        state=ApprcExampleAppConfigState(env_bootstrap=None),
    )

    result = CliRunner().invoke(
        app,
        [
            "--env-file",
            str(selector_env),
            "config",
            "set",
            "access_token",
            "secret",
            "--scope",
            "storage",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen_contexts
    assert seen_contexts[-1].explicit_values["APPRC_EXAMPLE_APP_STORAGE"] == (
        str(storage_root)
    )
    assert seen_contexts[-1].proc_env["APPRC_EXAMPLE_APP_STORAGE"] == str(
        storage_root
    )
    assert 'APPRC_EXAMPLE_APP_ACCESS_TOKEN="secret"\n' in (
        storage_root / ".env.apprc-storage"
    ).read_text(encoding="utf-8")


def test_context_aware_initial_storage_hook_receives_selector_context(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    storage_root = tmp_path / "selected-storage"
    storage_root.mkdir()
    selector_env = tmp_path / "selector.env"
    selector_env.write_text(
        f"APPRC_EXAMPLE_APP_STORAGE={storage_root}\n"
        "APPRC_EXAMPLE_APP_STORAGE_NAME=alpha\n",
        encoding="utf-8",
    )
    seen_contexts: list[ConfigSelectorContext] = []

    def active_storage_root_with_context(
        state: ApprcExampleAppConfigState,
        selector_context: ConfigSelectorContext,
    ) -> Path | None:
        return Path(
            selector_context.explicit_values["APPRC_EXAMPLE_APP_STORAGE"]
        )

    def initial_storage_with_context(
        state: ApprcExampleAppConfigState,
        selector_context: ConfigSelectorContext,
    ) -> str | None:
        seen_contexts.append(selector_context)
        return selector_context.explicit_values[
            "APPRC_EXAMPLE_APP_STORAGE_NAME"
        ]

    CapturingConfigEditorApp.reset()
    config_app = kit.typer_app(
        state_type=ApprcExampleAppConfigState,
        active_storage_root_with_context=active_storage_root_with_context,
        initial_storage_with_context=initial_storage_with_context,
        editor_app_cls=CapturingConfigEditorApp,
    )
    app = root_app_with_config(
        config_app,
        state=ApprcExampleAppConfigState(env_bootstrap=None),
    )

    result = CliRunner().invoke(
        app,
        [
            "--env-file",
            str(selector_env),
            "--env-file-overrides-os-environ",
            "config",
            "edit",
        ],
    )

    assert result.exit_code == 0, result.output
    assert CapturingConfigEditorApp.run_count == 1
    assert CapturingConfigEditorApp.initial_storage_seen == "alpha"
    assert seen_contexts[-1].env_file_overrides_os_environ is True
    assert CapturingConfigEditorApp.active_storage_root_seen == storage_root


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
        config_package="apprc",
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


def test_config_edit_without_tui_extra_reports_install_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Default editor launch explains how to install the optional TUI."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    original_import = builtins.__import__

    def import_without_textual(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: Mapping[str, Any] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> Any:
        """Raise the same missing-module error as a no-extra install."""
        if name == "apprc.interfaces.tui":
            raise ModuleNotFoundError(
                "No module named 'textual'",
                name="textual",
            )
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_textual)
    kit = build_storage_free_example_kit()
    state = StorageFreeExampleConfigStateWithoutStorage()
    app = kit.typer_app(state_type=StorageFreeExampleConfigStateWithoutStorage)

    result = CliRunner().invoke(
        app,
        ["edit"],
        obj=state,
        terminal_width=200,
    )

    assert result.exit_code != 0
    normalized_output = " ".join(result.output.split())
    assert "The Textual config editor requires" in normalized_output
    assert 'python -m pip install "apprc[tui]"' in normalized_output
