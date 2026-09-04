from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.purge import (
    ConfigPurgeError,
    apply_config_purge,
    build_config_purge_plan,
)
from apprc.user_files.storage_roots.model import StorageRecord, StorageRegistry
from apprc.user_files.storage_roots.registry import (
    register_storage,
    write_storage_registry,
)
from tests.support_config import (
    build_apprc_example_app_kit,
    build_storage_free_example_kit,
)


def test_purge_removes_only_managed_files_and_registered_internal_roots(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    spec = kit.spec
    spec.ensure_user_dotenv()
    internal_root = spec.apprc_dir() / "storage"
    external_root = tmp_path / "external"
    register_storage(
        name="default",
        root=internal_root,
        path=spec.preferred_apprc_toml_path(),
    )
    register_storage(
        name="external",
        root=external_root,
        path=spec.preferred_apprc_toml_path(),
    )
    (internal_root / "payload.txt").write_text("internal", encoding="utf-8")
    (external_root / "payload.txt").write_text("external", encoding="utf-8")
    unrelated = spec.apprc_dir() / "user-owned.txt"
    unrelated.write_text("keep", encoding="utf-8")

    plan = build_config_purge_plan(spec)
    result = apply_config_purge(plan)

    assert internal_root in plan.internal_storage_roots
    assert external_root in plan.external_storage_roots
    assert not internal_root.exists()
    assert not spec.user_dotenv_path().exists()
    assert not spec.preferred_apprc_toml_path().exists()
    assert not (external_root / "apprc.storage.env").exists()
    assert (external_root / "payload.txt").read_text(encoding="utf-8") == (
        "external"
    )
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert spec.apprc_dir().is_dir()
    assert result.skipped == ()


def test_purge_preflight_rejects_malformed_registry_without_deleting(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    spec = kit.spec
    user_dotenv = spec.ensure_user_dotenv()
    user_dotenv.write_text("KEEP=1\n", encoding="utf-8")
    spec.preferred_apprc_toml_path().write_text("[invalid", encoding="utf-8")

    with pytest.raises(ConfigPurgeError, match="before deleting"):
        build_config_purge_plan(spec)

    assert user_dotenv.read_text(encoding="utf-8") == "KEEP=1\n"


def test_purge_does_not_follow_registered_storage_symlink(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    spec = kit.spec
    spec.ensure_user_dotenv()
    target = tmp_path / "target"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_text("keep", encoding="utf-8")
    link = spec.apprc_dir() / "storage"
    link.symlink_to(target, target_is_directory=True)
    registry_path = spec.preferred_apprc_toml_path()
    write_storage_registry(
        StorageRegistry(
            path=registry_path,
            storages={
                "default": StorageRecord(name="default", root=link),
            },
            selected_storage="default",
        )
    )

    result = apply_config_purge(build_config_purge_plan(spec))

    assert link in result.skipped
    assert link.is_symlink()
    assert payload.read_text(encoding="utf-8") == "keep"


def test_purge_rejects_apprc_directory_below_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    kit = AppConfigKit(
        app_id="symlinked",
        display_name="Symlinked",
        config_package="config_only.config",
        apprc_dir=link / "apprc",
    )

    with pytest.raises(ConfigPurgeError, match="symbolic-link component"):
        build_config_purge_plan(kit.spec)


def test_storage_free_purge_marks_stale_registry_as_removable() -> None:
    kit = build_storage_free_example_kit()
    spec = kit.spec
    spec.ensure_user_dotenv()
    root = spec.apprc_dir() / "storage"
    root.mkdir()
    registry_path = spec.preferred_apprc_toml_path()
    write_storage_registry(
        StorageRegistry(
            path=registry_path,
            storages={
                "old": StorageRecord(name="old", root=root),
            },
            selected_storage="old",
        )
    )

    plan = build_config_purge_plan(spec)

    assert plan.stale_storage is True
    assert root in plan.internal_storage_roots
