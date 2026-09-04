from __future__ import annotations

import json
import sys
from pathlib import Path, WindowsPath

import pytest

import apprc.user_files.storage_roots.paths as storage_paths
import apprc.user_files.storage_roots.registry as storage_registry_module
from apprc.user_files.storage_roots._loading import (
    MissingStorageRegistryError,
    load_existing_storage_registry,
)
from apprc.user_files.storage_roots.registry import (
    app_data_dir,
    load_storage_registry_or_empty,
    ordered_storage_names,
    prune_missing_archived_storages,
    record_archived_storage,
    register_storage,
    remove_archived_storage,
    suggested_storage_name,
    suggested_storage_root,
    unregister_storage,
    _update_storage,
)
from apprc.user_files.storage_roots.model import StorageRegistry
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
    windows_drive_path_to_posix,
)
from tests.support_config import build_apprc_example_app_kit


def test_storage_suggestion_uses_predictable_apprc_directory() -> None:
    assert app_data_dir("demo").name == "demo"
    assert suggested_storage_root("demo") == app_data_dir("demo") / "storage"


def test_suggested_storage_name_is_default() -> None:
    assert suggested_storage_name("demo") == "default"
    assert suggested_storage_name("my-app.rc") == "default"


def test_missing_existing_storage_registry_uses_custom_config_group_name(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    missing_index = tmp_path / "missing.apprc.toml"

    with pytest.raises(MissingStorageRegistryError) as exc_info:
        load_existing_storage_registry(
            kit.spec,
            proc_env={kit.spec.apprc_dir_env_key: str(missing_index.parent)},
            config_group_name="settings",
        )

    assert " settings storage add NAME ROOT`" in str(exc_info.value)
    assert " config storage add NAME ROOT`" not in str(exc_info.value)


def test_missing_registry_guidance_uses_custom_config_group_name(
    tmp_path: Path,
) -> None:
    kit = build_apprc_example_app_kit()
    with pytest.raises(MissingStorageRegistryError) as exc_info:
        load_existing_storage_registry(
            kit.spec,
            proc_env={kit.spec.apprc_dir_env_key: str(tmp_path)},
            config_group_name="settings",
        )

    message = str(exc_info.value)
    assert "settings storage add NAME ROOT" in message
    assert "config storage add NAME ROOT" not in message


def test_register_storage_writes_sorted_toml_and_storage_dotenv(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "config" / "demo.apprc.toml"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    register_storage(
        name="zeta",
        root=second_root,
        path=index_path,
        storage_dotenv_filename=".env.demo",
    )
    register_storage(
        name="alpha",
        root=first_root,
        path=index_path,
        storage_dotenv_filename=".env.demo",
    )

    assert (first_root / ".env.demo").is_file()
    assert index_path.read_text(encoding="utf-8") == (
        'selected_storage = "zeta"\n'
        "\n"
        "[storages.alpha]\n"
        f"root = {json.dumps(str(first_root.resolve()))}\n"
        "\n"
        "[storages.zeta]\n"
        f"root = {json.dumps(str(second_root.resolve()))}\n"
    )


def test_ordered_storage_names_are_sorted(tmp_path: Path) -> None:
    index_path = tmp_path / "config" / "demo.apprc.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
    )
    registry = register_storage(
        name="zeta",
        root=tmp_path / "zeta",
        path=index_path,
    )

    assert ordered_storage_names(registry) == ["alpha", "zeta"]


def test_load_storage_registry_or_empty_rejects_unknown_top_level_keys(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    index_path.write_text(
        'default_storage = "alpha"\n'
        "\n"
        "[storages.alpha]\n"
        f"root = {json.dumps(str(tmp_path / 'alpha'))}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported top-level registry key"):
        load_storage_registry_or_empty(index_path)


def test_archived_storage_records_round_trip_sorted_toml(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
        storage_dotenv_filename=".env.demo",
    )

    registry = record_archived_storage(
        name="zeta",
        archive=tmp_path / "zeta.apprc.tar.xz",
        source_root=tmp_path / "zeta",
        path=index_path,
    )

    assert registry.archived_storages["zeta"].archive == (
        tmp_path / "zeta.apprc.tar.xz"
    )
    assert load_storage_registry_or_empty(index_path).archived_storages[
        "zeta"
    ].source_root == (tmp_path / "zeta")
    assert "[archived_storages.zeta]" in index_path.read_text(encoding="utf-8")


def test_remove_and_prune_archived_storage_records(tmp_path: Path) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    existing_archive = tmp_path / "alpha.apprc.tar.xz"
    existing_archive.write_bytes(b"placeholder")
    record_archived_storage(
        name="alpha",
        archive=existing_archive,
        source_root=tmp_path / "alpha",
        path=index_path,
    )
    record_archived_storage(
        name="beta",
        archive=tmp_path / "missing.apprc.tar.xz",
        source_root=tmp_path / "beta",
        path=index_path,
    )

    registry = prune_missing_archived_storages(path=index_path)
    registry = remove_archived_storage(name="alpha", path=index_path)

    assert sorted(registry.archived_storages) == []
    assert (
        "beta"
        not in load_storage_registry_or_empty(index_path).archived_storages
    )


def test_unregister_storage_removes_rows_without_default_repair(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
    )
    register_storage(
        name="beta",
        root=tmp_path / "beta",
        path=index_path,
    )

    registry = unregister_storage(
        name="alpha",
        path=index_path,
    )
    registry = unregister_storage(name="beta", path=index_path)

    assert registry.storages == {}


def test_unregister_storage_requires_existing_name(tmp_path: Path) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    register_storage(
        name="alpha",
        root=tmp_path / "alpha",
        path=index_path,
    )

    with pytest.raises(ValueError, match="Unknown storage 'beta'"):
        unregister_storage(name="beta", path=index_path)


def test_internal_update_storage_renames_matching_archive_with_one_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    target_root = tmp_path / "beta"
    archive_path = tmp_path / "alpha.apprc.tar.xz"
    register_storage(name="alpha", root=source_root, path=index_path)
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    record_archived_storage(
        name="alpha",
        archive=archive_path,
        source_root=source_root,
        path=index_path,
    )
    write_calls: list[StorageRegistry] = []
    original_write = storage_registry_module.write_storage_registry

    def record_write(registry: StorageRegistry) -> Path:
        write_calls.append(registry)
        return original_write(registry)

    monkeypatch.setattr(
        storage_registry_module,
        "write_storage_registry",
        record_write,
    )

    registry = _update_storage(
        current_name="alpha",
        name="beta",
        root=target_root,
        path=index_path,
    )

    assert write_calls == [registry]
    assert set(registry.storages) == {"beta"}
    assert registry.selected("beta").root == target_root.resolve()
    assert set(registry.archived_storages) == {"beta"}
    archived = registry.archived_storages["beta"]
    assert archived.name == "beta"
    assert archived.archive == archive_path
    assert archived.source_root == source_root
    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert not target_root.exists()
    assert not (target_root / "apprc.storage.env").exists()

    persisted = load_storage_registry_or_empty(index_path)
    assert persisted.selected("beta").root == target_root.resolve()
    assert persisted.archived_storages["beta"] == archived


def test_internal_update_storage_rename_keeps_relative_root_resolution(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    stored_root = Path("relative-alpha")
    index_path.write_text(
        f"[storages.alpha]\nroot = {json.dumps(str(stored_root))}\n",
        encoding="utf-8",
    )

    registry = _update_storage(
        current_name="alpha",
        name="beta",
        root=None,
        path=index_path,
    )

    resolved_root = (index_path.parent / stored_root).absolute()
    assert registry.selected("beta").root == resolved_root
    persisted = load_storage_registry_or_empty(index_path)
    assert persisted.selected("beta").root == resolved_root
    assert f"root = {json.dumps(str(stored_root))}" in index_path.read_text(
        encoding="utf-8"
    )


def test_internal_update_storage_rename_preserves_symlink_root_spelling(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    target_root = tmp_path / "alpha-target"
    target_root.mkdir()
    stored_root = tmp_path / "alpha-link"
    try:
        stored_root.symlink_to(target_root, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable in this test environment.")
    index_path.write_text(
        f"[storages.alpha]\nroot = {json.dumps(str(stored_root))}\n",
        encoding="utf-8",
    )

    registry = _update_storage(
        current_name="alpha",
        name="beta",
        root=None,
        path=index_path,
    )

    assert registry.selected("beta").root == stored_root
    assert registry.selected("beta").root != target_root
    persisted = load_storage_registry_or_empty(index_path)
    assert persisted.selected("beta").root == stored_root


def test_internal_update_storage_repoints_only_the_registry_root(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    source_root = tmp_path / "alpha"
    target_root = tmp_path / "moved-alpha"
    archive_path = tmp_path / "alpha.apprc.tar.xz"
    register_storage(name="alpha", root=source_root, path=index_path)
    (source_root / "payload.txt").write_text("keep", encoding="utf-8")
    record_archived_storage(
        name="alpha",
        archive=archive_path,
        source_root=source_root,
        path=index_path,
    )

    registry = _update_storage(
        current_name="alpha",
        name="alpha",
        root=target_root,
        path=index_path,
    )

    assert registry.selected("alpha").root == target_root.resolve()
    archived = registry.archived_storages["alpha"]
    assert archived.name == "alpha"
    assert archived.source_root == source_root
    assert (source_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert not target_root.exists()
    assert not (target_root / "apprc.storage.env").exists()


@pytest.mark.parametrize("conflict_kind", ("live", "archived"))
def test_internal_update_storage_rejects_other_live_or_archived_target_names(
    conflict_kind: str,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    register_storage(name="alpha", root=tmp_path / "alpha", path=index_path)
    if conflict_kind == "live":
        register_storage(name="beta", root=tmp_path / "beta", path=index_path)
    else:
        record_archived_storage(
            name="beta",
            archive=tmp_path / "beta.apprc.tar.xz",
            source_root=tmp_path / "beta",
            path=index_path,
        )
    original_contents = index_path.read_text(encoding="utf-8")
    target_root = tmp_path / "new-root"

    with pytest.raises(ValueError, match="already used"):
        _update_storage(
            current_name="alpha",
            name="beta",
            root=target_root,
            path=index_path,
        )

    assert index_path.read_text(encoding="utf-8") == original_contents
    assert not target_root.exists()


def test_internal_update_storage_requires_a_live_source_and_valid_target_values(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"

    with pytest.raises(ValueError, match="Unknown storage 'alpha'"):
        _update_storage(
            current_name="alpha",
            name="beta",
            root=tmp_path / "beta",
            path=index_path,
        )

    register_storage(name="alpha", root=tmp_path / "alpha", path=index_path)
    with pytest.raises(ValueError, match="Storage names may contain"):
        _update_storage(
            current_name="alpha",
            name="not valid",
            root=tmp_path / "beta",
            path=index_path,
        )
    with pytest.raises(StorageRootPathError, match="must not be empty"):
        _update_storage(
            current_name="alpha",
            name="beta",
            root=Path(" "),
            path=index_path,
        )


def test_register_storage_normalizes_windows_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "config" / "demo.apprc.toml"
    normalized_root = tmp_path / "demo-storage"

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.paths.normalize_storage_root_path",
        lambda path: normalized_root,
    )

    registry = register_storage(
        name="demo",
        root=Path(r"D:\Training\demo-project"),
        path=index_path,
        storage_dotenv_filename=".env.demo",
    )

    assert registry.selected("demo").root == normalized_root.resolve()
    assert (normalized_root / ".env.demo").is_file()


def test_windows_drive_path_to_posix_falls_back_to_mnt_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda command: None)

    assert windows_drive_path_to_posix(r"D:\Training\demo-project") == Path(
        "/mnt/d/Training/demo-project"
    )


def test_normalize_storage_root_path_accepts_windows_drive_spellings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_paths, "_IS_NATIVE_WINDOWS", False)
    monkeypatch.setattr("shutil.which", lambda command: None)

    assert normalize_storage_root_path(r"C:\Projects\demo-storage") == Path(
        "/mnt/c/Projects/demo-storage"
    )
    assert normalize_storage_root_path("C:/Projects/demo-storage") == Path(
        "/mnt/c/Projects/demo-storage"
    )


def test_normalize_storage_root_path_preserves_native_windows_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_paths, "_IS_NATIVE_WINDOWS", True)

    assert normalize_storage_root_path(r"C:\Projects\demo-storage") == Path(
        r"C:\Projects\demo-storage"
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="requires native Windows pathlib semantics",
)
@pytest.mark.parametrize(
    "raw_path",
    [r"C:\Projects\demo-storage", "C:/Projects/demo-storage"],
)
def test_normalize_storage_root_path_uses_native_windows_path_semantics(
    raw_path: str,
) -> None:
    normalized = normalize_storage_root_path(raw_path)

    assert isinstance(normalized, WindowsPath)
    assert normalized == Path("C:/Projects/demo-storage")
    assert normalized.drive == "C:"
    assert normalized.is_absolute()


def test_normalize_storage_root_path_rejects_blank_text() -> None:
    for raw_path in ("", "   ", "\t"):
        with pytest.raises(StorageRootPathError, match="must not be empty"):
            normalize_storage_root_path(raw_path)


def test_normalize_storage_root_path_rejects_damaged_windows_path() -> None:
    with pytest.raises(StorageRootPathError) as exc_info:
        normalize_storage_root_path("C:Projectsdemo-storage")

    message = str(exc_info.value)
    assert "unquoted backslashes are consumed" in message
    assert "`C:/Projects/demo-storage`" in message
    assert "`/mnt/c/Projects/demo-storage`" in message
    assert normalize_storage_root_path("./C:Projectsdemo-storage") == Path(
        "./C:Projectsdemo-storage"
    )


def test_load_storage_registry_or_empty_rejects_invalid_storage_tables(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    index_path.write_text('storages = "alpha"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="storages must be a table"):
        load_storage_registry_or_empty(index_path)

    index_path.write_text(
        "[storages.alpha]\nroot = []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"storages\.alpha\.root"):
        load_storage_registry_or_empty(index_path)


def test_load_storage_registry_or_empty_rejects_invalid_archived_storage_tables(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    index_path.write_text(
        "[archived_storages.alpha]\n"
        f"archive = {json.dumps(str(tmp_path / 'alpha.apprc.tar.xz'))}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"archived_storages\.alpha\.source_root",
    ):
        load_storage_registry_or_empty(index_path)


def test_register_storage_rejects_names_that_cannot_be_toml_keys(
    tmp_path: Path,
) -> None:
    for name in ("not valid", "path/like", r"path\like"):
        with pytest.raises(
            ValueError,
            match=r"must not include `/` or `\\`",
        ):
            register_storage(
                name=name,
                root=tmp_path / "storage",
                path=tmp_path / "demo.apprc.toml",
            )


def test_register_storage_validates_existing_registry_before_creating_files(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    index_path.write_text("[invalid", encoding="utf-8")
    storage_root = tmp_path / "alpha"

    with pytest.raises(ValueError):
        register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
        )

    assert not storage_root.exists()
    assert not (storage_root / "apprc.storage.env").exists()


def test_register_storage_rolls_back_new_empty_artifacts_on_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"

    def fail_write(_: object) -> None:
        raise OSError("blocked")

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.registry.write_storage_registry",
        fail_write,
    )

    with pytest.raises(OSError, match="blocked"):
        register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
        )

    assert not storage_root.exists()
    assert not (storage_root / "apprc.storage.env").exists()


def test_register_storage_warns_when_storage_env_rollback_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    original_unlink = Path.unlink

    def fail_write(_: object) -> None:
        raise OSError("blocked")

    def fail_storage_env_unlink(
        self: Path,
        missing_ok: bool = False,
    ) -> None:
        if self.name == "apprc.storage.env":
            raise OSError("unlink blocked")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.registry.write_storage_registry",
        fail_write,
    )
    monkeypatch.setattr(Path, "unlink", fail_storage_env_unlink)
    caplog.set_level(
        "WARNING",
        logger="apprc.user_files.storage_roots.registry",
    )

    with pytest.raises(OSError, match="blocked") as exc_info:
        register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
        )

    notes = getattr(exc_info.value, "__notes__", ())
    assert any("remove empty storage env file" in note for note in notes)
    assert any("unlink blocked" in message for message in caplog.messages)
    assert storage_root.exists()
    assert (storage_root / "apprc.storage.env").exists()


def test_register_storage_warns_when_root_rollback_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    original_rmdir = Path.rmdir

    def fail_write(_: object) -> None:
        raise OSError("blocked")

    def fail_created_root_rmdir(self: Path) -> None:
        if self == storage_root.resolve():
            raise OSError("rmdir blocked")
        original_rmdir(self)

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.registry.write_storage_registry",
        fail_write,
    )
    monkeypatch.setattr(Path, "rmdir", fail_created_root_rmdir)
    caplog.set_level(
        "WARNING",
        logger="apprc.user_files.storage_roots.registry",
    )

    with pytest.raises(OSError, match="blocked") as exc_info:
        register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
        )

    notes = getattr(exc_info.value, "__notes__", ())
    assert any("remove created storage root" in note for note in notes)
    assert any("rmdir blocked" in message for message in caplog.messages)
    assert storage_root.exists()
    assert not (storage_root / "apprc.storage.env").exists()


def test_register_storage_keeps_existing_non_empty_root_on_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "demo.apprc.toml"
    storage_root = tmp_path / "alpha"
    storage_root.mkdir()
    (storage_root / "payload.txt").write_text("keep", encoding="utf-8")

    def fail_write(_: object) -> None:
        raise OSError("blocked")

    monkeypatch.setattr(
        "apprc.user_files.storage_roots.registry.write_storage_registry",
        fail_write,
    )

    with pytest.raises(OSError, match="blocked"):
        register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
        )

    assert (storage_root / "payload.txt").read_text(encoding="utf-8") == "keep"
    assert not (storage_root / "apprc.storage.env").exists()
