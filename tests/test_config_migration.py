from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.storage import Storage
from apprc.user_files.migration import (
    ConfigMigrationError,
    apply_config_migration,
    build_config_migration_plan,
)
from apprc.user_files.storage_roots.registry import register_storage


def _kit() -> AppConfigKit:
    """Return a direct storage declaration for migration tests."""
    return AppConfigKit(
        app_name="migration_demo",
        display_name="Migration Demo",
        config_package="storage_only.config",
        storage=Storage(env_key="MIGRATION_DEMO_STORAGE"),
    )


def test_migration_moves_all_known_legacy_files_and_is_rerunnable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Move app, TOML, and known storage files without copying contents."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    legacy_app = kit.spec.config_home() / ".env.apprc-app"
    legacy_toml = kit.spec.config_home() / "migration_demo.apprc.toml"
    legacy_app.parent.mkdir(parents=True)
    legacy_app.write_text("APP_VALUE=legacy\n", encoding="utf-8")
    legacy_toml.write_text("[storages]\n", encoding="utf-8")
    (first_root / ".env.apprc-storage").write_text(
        "FIRST=legacy\n",
        encoding="utf-8",
    )
    (second_root / ".env.local").write_text(
        "SECOND=legacy\n",
        encoding="utf-8",
    )

    plan = build_config_migration_plan(
        kit.spec,
        storage_roots=(first_root, second_root, first_root),
    )

    assert plan.conflicts == ()
    assert len(plan.moves) == 4
    result = apply_config_migration(plan)
    assert result.moved == plan.moves
    assert kit.spec.preferred_app_env_path().read_text(encoding="utf-8") == (
        "APP_VALUE=legacy\n"
    )
    assert (
        kit.spec.preferred_apprc_toml_path().read_text(encoding="utf-8")
        == "[storages]\n"
    )
    assert (first_root / "apprc.storage.env").read_text(
        encoding="utf-8"
    ) == "FIRST=legacy\n"
    assert (second_root / "apprc.storage.env").read_text(
        encoding="utf-8"
    ) == "SECOND=legacy\n"
    assert not legacy_app.exists()
    assert not legacy_toml.exists()
    assert (
        build_config_migration_plan(
            kit.spec,
            storage_roots=(first_root, second_root),
        ).moves
        == ()
    )


def test_migration_preflights_conflicts_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Current and legacy files require manual conflict resolution."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    current = kit.spec.preferred_app_env_path()
    legacy = current.with_name(".env.apprc-app")
    current.parent.mkdir(parents=True)
    current.write_text("VALUE=current\n", encoding="utf-8")
    legacy.write_text("VALUE=legacy\n", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="current and legacy"):
        plan = build_config_migration_plan(kit.spec)

    assert len(plan.conflicts) == 1
    with pytest.raises(ConfigMigrationError, match="No files were moved"):
        apply_config_migration(plan)
    assert current.read_text(encoding="utf-8") == "VALUE=current\n"
    assert legacy.read_text(encoding="utf-8") == "VALUE=legacy\n"


def test_migration_does_not_replace_destination_created_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A destination created after planning remains untouched."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    preferred = kit.spec.preferred_app_env_path()
    legacy = preferred.with_name(".env.apprc-app")
    legacy.parent.mkdir(parents=True)
    legacy.write_text("VALUE=legacy\n", encoding="utf-8")
    plan = build_config_migration_plan(kit.spec)
    preferred.write_text("VALUE=current\n", encoding="utf-8")

    with pytest.raises(ConfigMigrationError, match="Could not move") as raised:
        apply_config_migration(plan)

    assert raised.value.completed == ()
    assert preferred.read_text(encoding="utf-8") == "VALUE=current\n"
    assert legacy.read_text(encoding="utf-8") == "VALUE=legacy\n"


def test_managed_directory_blocks_legacy_fallback_and_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A directory at the current path is surfaced instead of bypassed."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    preferred = kit.spec.preferred_app_env_path()
    legacy = preferred.with_name(".env.apprc-app")
    preferred.mkdir(parents=True)
    legacy.write_text("VALUE=legacy\n", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="current and legacy"):
        resolution = kit.spec.app_env_resolution()
    with pytest.warns(RuntimeWarning, match="current and legacy"):
        plan = build_config_migration_plan(kit.spec)

    assert resolution.selected == preferred
    assert resolution.conflicts == (legacy,)
    assert plan.moves == ()
    assert len(plan.conflicts) == 1


def test_legacy_only_file_remains_the_read_write_target_before_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Compatibility fallback does not create a competing current file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    kit = _kit()
    preferred = kit.spec.preferred_app_env_path()
    legacy = preferred.with_name(".env.apprc-app")
    legacy.parent.mkdir(parents=True)
    legacy.write_text("VALUE=legacy\n", encoding="utf-8")

    assert kit.spec.app_env_path() == legacy
    assert kit.spec.ensure_app_env() == legacy.resolve()
    assert not preferred.exists()


def test_custom_names_and_explicit_toml_path_disable_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Explicit integration choices never activate conventional legacy files."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    explicit_toml = tmp_path / "custom" / "registry.toml"
    monkeypatch.setenv("CUSTOM_APP_APPRC_TOML", str(explicit_toml))
    kit = AppConfigKit(
        app_name="custom_app",
        display_name="Custom App",
        config_package="apprc",
        app_env_filename="custom.app.env",
        apprc_toml_filename="custom.toml",
        storage=Storage(env_filename="custom.storage.env"),
    )
    config_home = kit.spec.config_home()
    config_home.mkdir(parents=True)
    (config_home / ".env.apprc-app").write_text("OLD=1\n", encoding="utf-8")
    (config_home / "custom_app.apprc.toml").write_text(
        "[storages]\n",
        encoding="utf-8",
    )

    assert kit.spec.app_env_path() == config_home / "custom.app.env"
    assert kit.spec.apprc_toml_path() == explicit_toml
    assert build_config_migration_plan(kit.spec).moves == ()


def test_config_migrate_dry_run_then_moves_registered_storage_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CLI discovers roots in legacy AppRC TOML before moving it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("MIGRATION_DEMO_STORAGE", raising=False)
    kit = _kit()
    legacy_toml = kit.spec.config_home() / "migration_demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=storage_root,
        path=legacy_toml,
        storage_env_filename=".env.apprc-storage",
    )
    legacy_app = kit.spec.config_home() / ".env.apprc-app"
    legacy_app.write_text(
        "MIGRATION_DEMO_STORAGE=alpha\n",
        encoding="utf-8",
    )
    app = kit.typer_app()
    runner = CliRunner()

    dry_run = runner.invoke(app, ["migrate", "--dry-run"])

    assert dry_run.exit_code == 0, dry_run.output
    assert "would_move:" in dry_run.output
    assert legacy_toml.is_file()
    assert (storage_root / ".env.apprc-storage").is_file()

    migrated = runner.invoke(app, ["migrate", "--yes"])

    assert migrated.exit_code == 0, migrated.output
    assert "migrated_files: 3" in migrated.output
    assert kit.spec.preferred_app_env_path().is_file()
    assert kit.spec.preferred_apprc_toml_path().is_file()
    assert (storage_root / "apprc.storage.env").is_file()
