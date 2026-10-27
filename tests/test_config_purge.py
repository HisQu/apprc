from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths, Layout, Paths
from apprc.user_files.app_home.ownership import ensure_owned_path
from apprc.user_files.env_files.secrets import secret_companion_path
from apprc.user_files.purge import apply_config_purge, plan_config_purge


def _config_paths(root: Path) -> AppPaths:
    return AppPaths(
        layout=Layout.single_root(root),
        source="invocation",
        config_dir=root / "config",
        appdata_dir=None,
        cache_dir=None,
        state_dir=None,
        logs_dir=None,
    )


def _config_spec() -> AppConfigSpec:
    return AppConfigSpec(
        app_id="purge-test", display_name="Purge test", paths=Paths(config=True)
    )


def test_config_purge_removes_only_known_files(tmp_path: Path) -> None:
    spec = _config_spec()
    paths = _config_paths(tmp_path)
    root = ensure_owned_path(spec, paths, "config")
    dotenv = root / spec.user_dotenv_filename
    dotenv.write_text("PREFERENCE=1\n", encoding="utf-8")
    secret = secret_companion_path(dotenv)
    secret.write_text("SECRET=hidden\n", encoding="utf-8")
    registry = root / spec.apprc_toml_filename
    registry.write_text("schema_version = 1\n", encoding="utf-8")
    unknown = root / "manual-notes.txt"
    unknown.write_text("keep", encoding="utf-8")
    result = apply_config_purge(plan_config_purge(spec, paths), spec, paths)

    assert dotenv in result.removed
    assert secret in result.removed
    assert registry in result.removed
    assert unknown.read_text(encoding="utf-8") == "keep"
    assert root.is_dir()


def test_config_purge_refuses_unowned_and_stale_roots(tmp_path: Path) -> None:
    spec = _config_spec()
    paths = _config_paths(tmp_path)
    root = paths.require("config")
    root.mkdir(parents=True)
    (root / "unowned.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        plan_config_purge(spec, paths)
    (root / ".apprc-owner.json").write_text(
        '{"schema_version":1,"app_id":"purge-test","category":"config"}',
        encoding="utf-8",
    )
    managed = root / spec.user_dotenv_filename
    managed.write_text("VALUE=old\n", encoding="utf-8")
    plan = plan_config_purge(spec, paths)
    managed.write_text("VALUE=new\n", encoding="utf-8")
    unknown = root / "changed.txt"
    unknown.write_text("new", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        apply_config_purge(plan, spec, paths)
    assert unknown.read_text(encoding="utf-8") == "new"


def test_config_purge_rejects_linked_managed_file(tmp_path: Path) -> None:
    spec = _config_spec()
    paths = _config_paths(tmp_path)
    root = ensure_owned_path(spec, paths, "config")
    external = tmp_path / "external.txt"
    external.write_text("keep", encoding="utf-8")
    (root / spec.user_dotenv_filename).symlink_to(external)
    with pytest.raises(ValueError):
        plan_config_purge(spec, paths)
    assert external.read_text(encoding="utf-8") == "keep"
