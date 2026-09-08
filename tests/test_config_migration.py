from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.storage import Storage
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.user_files.migration import (
    ConfigMigrationError,
    StorageMigrationResolution,
    UnresolvedStorageMigrationError,
    apply_config_migration,
    build_config_migration_plan,
    legacy_platform_config_dir,
)
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
    register_storage,
)


def _spec(
    tmp_path: Path, *, legacy_app_ids: tuple[str, ...] = ()
) -> AppConfigSpec:
    """Return a storage declaration with an isolated new AppRC directory."""
    return AppConfigSpec(
        app_id="migration_demo",
        display_name="Migration Demo",
        config_package="apprc",
        user_dotenv=UserDotenv(),
        storage=Storage(selector_env_key="MIGRATION_DEMO_STORAGE"),
        apprc_dir=tmp_path / "new-apprc",
        legacy_app_ids=legacy_app_ids,
    )


def _legacy_environment(tmp_path: Path) -> dict[str, str]:
    """Return platform base-directory overrides below a temporary directory.

    :param tmp_path: Temporary directory owned by the test.
    :return: Linux, macOS, and Windows base-directory environment values.
    """
    return {
        "APPDATA": str(tmp_path / "legacy-config"),
        "HOME": str(tmp_path / "legacy-home"),
        "XDG_CONFIG_HOME": str(tmp_path / "legacy-config"),
    }


def test_migration_converts_released_path_selector_to_default_storage(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    proc_env = _legacy_environment(tmp_path)
    legacy_dir = legacy_platform_config_dir(
        "migration_demo",
        proc_env=proc_env,
    )
    legacy_dir.mkdir(parents=True)
    storage_root = tmp_path / "old-storage"
    storage_root.mkdir()
    (storage_root / ".env.apprc-storage").write_text(
        "LOCAL=1\n", encoding="utf-8"
    )
    (legacy_dir / ".env.apprc-app").write_text(
        f"KEEP=1\nMIGRATION_DEMO_STORAGE={storage_root.as_posix()}\n",
        encoding="utf-8",
    )

    plan = build_config_migration_plan(spec, proc_env=proc_env)
    result = apply_config_migration(plan)

    assert not plan.conflicts
    assert result.written
    assert spec.user_dotenv_path().read_text(encoding="utf-8") == "KEEP=1\n"
    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert registry.selected_storage == "default"
    assert registry.selected("default").root == storage_root.resolve()
    assert (storage_root / "apprc.storage.env").read_text(encoding="utf-8") == (
        "LOCAL=1\n"
    )
    assert not (storage_root / ".env.apprc-storage").exists()


def test_storage_only_migration_converts_selector_without_creating_user_dotenv(
    tmp_path: Path,
) -> None:
    spec = AppConfigSpec(
        app_id="migration_demo",
        display_name="Migration Demo",
        config_package="storage.config",
        storage=Storage(selector_env_key="MIGRATION_DEMO_STORAGE"),
        apprc_dir=tmp_path / "new-apprc",
    )
    proc_env = _legacy_environment(tmp_path)
    legacy_dir = legacy_platform_config_dir(
        "migration_demo",
        proc_env=proc_env,
    )
    legacy_dir.mkdir(parents=True)
    storage_root = tmp_path / "old-storage"
    storage_root.mkdir()
    (legacy_dir / ".env.apprc-app").write_text(
        f"MIGRATION_DEMO_STORAGE={storage_root}\n",
        encoding="utf-8",
    )

    apply_config_migration(build_config_migration_plan(spec, proc_env=proc_env))

    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert registry.selected_storage == "default"
    assert registry.selected("default").root == storage_root
    assert not spec.user_dotenv_path().exists()


def test_migration_resolves_relative_path_selector_from_new_apprc_toml(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)

    plan = build_config_migration_plan(
        spec,
        proc_env={"MIGRATION_DEMO_STORAGE": "./relative-storage"},
    )
    apply_config_migration(plan)

    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert registry.selected_storage == "default"
    assert registry.selected("default").root == (
        spec.preferred_apprc_toml_path().parent / "relative-storage"
    )


def test_migration_reads_custom_legacy_toml_and_resolves_relative_roots(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    legacy_toml = tmp_path / "custom" / "migration_demo.apprc.toml"
    legacy_toml.parent.mkdir()
    legacy_toml.write_text(
        '[storages.alpha]\nroot = "../alpha"\n',
        encoding="utf-8",
    )

    plan = build_config_migration_plan(
        spec,
        proc_env={
            "MIGRATION_DEMO_APPRC_TOML": str(legacy_toml),
            "MIGRATION_DEMO_STORAGE": "alpha",
        },
    )
    apply_config_migration(plan)

    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert registry.selected_storage == "alpha"
    assert registry.selected("alpha").root == (tmp_path / "alpha").resolve()
    assert any("MIGRATION_DEMO_APPRC_TOML" in item for item in plan.warnings)


def test_migration_conflict_preflight_makes_no_changes(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    proc_env = _legacy_environment(tmp_path)
    legacy_dir = legacy_platform_config_dir(
        "migration_demo",
        proc_env=proc_env,
    )
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / ".env.apprc-app"
    legacy.write_text("OLD=1\n", encoding="utf-8")
    spec.ensure_user_dotenv().write_text("NEW=1\n", encoding="utf-8")

    plan = build_config_migration_plan(spec, proc_env=proc_env)

    assert plan.conflicts
    with pytest.raises(ConfigMigrationError, match="No files were changed"):
        apply_config_migration(plan)
    assert legacy.read_text(encoding="utf-8") == "OLD=1\n"
    assert spec.user_dotenv_path().read_text(encoding="utf-8") == "NEW=1\n"


def test_migration_does_not_replace_late_destination(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    legacy = storage_root / ".env.apprc-storage"
    legacy.write_text("OLD=1\n", encoding="utf-8")
    plan = build_config_migration_plan(
        spec,
        storage_roots=(storage_root,),
        proc_env={"MIGRATION_DEMO_STORAGE": str(storage_root)},
    )
    destination = storage_root / "apprc.storage.env"
    destination.write_text("LATE=1\n", encoding="utf-8")

    with pytest.raises(ConfigMigrationError, match="filesystem error"):
        apply_config_migration(plan)

    assert legacy.is_file()
    assert destination.read_text(encoding="utf-8") == "LATE=1\n"


def test_migration_ignores_unreleased_apprc_app_env(tmp_path: Path) -> None:
    spec = AppConfigSpec(
        app_id="migration_demo",
        display_name="Migration Demo",
        config_package="apprc",
        user_dotenv=UserDotenv(),
        apprc_dir=tmp_path / "apprc",
    )
    unreleased = spec.apprc_dir() / "apprc.app.env"
    unreleased.parent.mkdir(parents=True)
    unreleased.write_text("IGNORE=1\n", encoding="utf-8")

    plan = build_config_migration_plan(spec)

    assert plan.moves == ()
    assert plan.writes == ()
    assert plan.conflicts == ()


def test_migration_scans_declared_legacy_app_ids(tmp_path: Path) -> None:
    spec = _spec(tmp_path, legacy_app_ids=("pdb",))
    proc_env = _legacy_environment(tmp_path)
    legacy_dir = legacy_platform_config_dir("pdb", proc_env=proc_env)
    legacy_dir.mkdir(parents=True)
    (legacy_dir / ".env.apprc-app").write_text("KEEP=1\n", encoding="utf-8")

    plan = build_config_migration_plan(spec, proc_env=proc_env)
    apply_config_migration(plan)

    assert spec.user_dotenv_path().read_text(encoding="utf-8") == "KEEP=1\n"


def test_migration_requires_mapping_for_unregistered_bare_selector(
    tmp_path: Path,
) -> None:
    """Migration must not guess which existing storage a name replaces.

    :param tmp_path: Isolated AppRC and storage parent.
    """
    spec = _spec(tmp_path)
    register_storage(
        name="opa",
        root=tmp_path / "opa",
        path=spec.preferred_apprc_toml_path(),
    )

    with pytest.raises(UnresolvedStorageMigrationError) as caught:
        build_config_migration_plan(
            spec,
            proc_env={"MIGRATION_DEMO_STORAGE": "ontology"},
        )

    assert caught.value.selector_name == "ontology"
    assert tuple(caught.value.registry.storages) == ("opa",)


def test_migration_registers_explicit_root_for_bare_selector(
    tmp_path: Path,
) -> None:
    """An explicit mapping adds the requested name and marker file.

    :param tmp_path: Isolated AppRC and storage parent.
    """
    spec = _spec(tmp_path)
    old_root = tmp_path / "opa"
    register_storage(
        name="opa",
        root=old_root,
        path=spec.preferred_apprc_toml_path(),
    )
    ontology_root = tmp_path / "ontology"
    ontology_root.mkdir()

    plan = build_config_migration_plan(
        spec,
        proc_env={"MIGRATION_DEMO_STORAGE": "ontology"},
        storage_resolution=StorageMigrationResolution(root=ontology_root),
    )
    result = apply_config_migration(plan)

    assert plan.storage_mapping is not None
    assert plan.storage_mapping.selector_name == "ontology"
    assert plan.storage_mapping.replaced_storage is None
    assert result.written
    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert set(registry.storages) == {"opa", "ontology"}
    assert registry.selected_storage == "ontology"
    assert registry.selected("ontology").root == ontology_root.resolve()
    assert (ontology_root / "apprc.storage.env").is_file()
    assert old_root.is_dir()


def test_migration_replaces_stale_entry_after_manual_directory_move(
    tmp_path: Path,
) -> None:
    """Replacement updates registry metadata without moving application data.

    :param tmp_path: Isolated AppRC and storage parent.
    """
    spec = _spec(tmp_path)
    old_root = tmp_path / "opa"
    register_storage(
        name="opa",
        root=old_root,
        path=spec.preferred_apprc_toml_path(),
    )
    payload = old_root / "payload.txt"
    payload.write_text("keep", encoding="utf-8")
    ontology_root = tmp_path / "ontology"
    old_root.rename(ontology_root)

    plan = build_config_migration_plan(
        spec,
        proc_env={"MIGRATION_DEMO_STORAGE": "ontology"},
        storage_resolution=StorageMigrationResolution(
            root=ontology_root,
            replace_storage="opa",
        ),
    )
    apply_config_migration(plan)

    assert plan.storage_mapping is not None
    assert plan.storage_mapping.replaced_storage == "opa"
    registry = load_storage_registry_or_empty(spec.preferred_apprc_toml_path())
    assert tuple(registry.storages) == ("ontology",)
    assert registry.selected_storage == "ontology"
    assert registry.selected("ontology").root == ontology_root.resolve()
    assert (ontology_root / "payload.txt").read_text(encoding="utf-8") == (
        "keep"
    )


def test_migration_rejects_duplicate_root_without_explicit_replacement(
    tmp_path: Path,
) -> None:
    """A root cannot silently acquire a second registered name.

    :param tmp_path: Isolated AppRC and storage parent.
    """
    spec = _spec(tmp_path)
    root = tmp_path / "opa"
    register_storage(
        name="opa",
        root=root,
        path=spec.preferred_apprc_toml_path(),
    )

    with pytest.raises(ConfigMigrationError, match="--replace-storage opa"):
        build_config_migration_plan(
            spec,
            proc_env={"MIGRATION_DEMO_STORAGE": "ontology"},
            storage_resolution=StorageMigrationResolution(root=root),
        )
