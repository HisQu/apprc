"""Independent AppRC path capabilities resolve without filesystem effects."""

from __future__ import annotations

import os
import sys
from itertools import product
from pathlib import Path

import pytest
from platformdirs import PlatformDirs

import apprc as rc
from apprc.definition.paths import Layout, PathKind, Paths
from apprc.definition.resolution import ResolveOptions

_CAPABILITIES = ("config", "appdata", "cache", "state")


def _app(capabilities: tuple[bool, bool, bool, bool]) -> rc.AppRC:
    """Build a fresh app with only the selected filesystem capabilities."""
    return rc.AppRC(
        app_id="path-matrix-test",
        paths=Paths(**dict(zip(_CAPABILITIES, capabilities, strict=True))),
    )


@pytest.mark.parametrize("mode", ("native", "single-root"))
@pytest.mark.parametrize("capabilities", product((False, True), repeat=4))
def test_paths_capture_only_enabled_components(
    tmp_path: Path,
    mode: str,
    capabilities: tuple[bool, bool, bool, bool],
) -> None:
    app = _app(capabilities)
    layout = (
        Layout.native()
        if mode == "native"
        else Layout.single_root(tmp_path / "root")
    )
    paths = app.paths(
        ResolveOptions(layout=layout), environment=dict(os.environ)
    )
    root = tmp_path / "root"
    native = PlatformDirs(
        appname=app.schema.app_id,
        appauthor=False,
        roaming=False,
        ensure_exists=False,
    )
    assert paths.layout == layout
    assert paths.source == "invocation"
    native_paths = {
        "config": Path(native.user_config_path) / "config"
        if sys.platform in {"win32", "darwin"}
        else Path(native.user_config_path),
        "appdata": Path(native.user_data_path) / "appdata",
        "cache": Path(native.user_cache_path),
        "state": Path(native.user_state_path) / "state"
        if sys.platform in {"win32", "darwin"}
        else Path(native.user_state_path),
    }
    for kind, enabled in zip(_CAPABILITIES, capabilities, strict=True):
        actual = getattr(paths, f"{kind}_dir")
        if not enabled:
            assert actual is None
            continue
        expected = root / kind if mode == "single-root" else native_paths[kind]
        assert actual == expected
    expected_logs = (
        root / "state" / "logs"
        if mode == "single-root" and capabilities[3]
        else (
            Path(native.user_log_path)
            if mode == "native" and capabilities[3]
            else None
        )
    )
    assert paths.logs_dir == expected_logs
    assert not root.exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux native appdata layout."
)
def test_native_installation_reuses_owned_appdata_with_persistent_lock(
    tmp_path: Path,
) -> None:
    from apprc.definition.installation import (
        InstallationIdentity,
        InstallationPlacement,
        InstallationSource,
        UvToolTarget,
    )
    from apprc.user_files.app_home.writes import managed_lock_path
    from apprc.user_files.installation.operations import (
        begin_operation,
        plan_install,
    )

    app = _app((False, True, False, False))
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "native-data"),
    }
    data = app.ensure_path("appdata", environment=environment)
    retained = data / "user-work.db"
    retained.write_bytes(b"retained work")
    lock = managed_lock_path(data)
    original_lock = lock.stat()
    placement = InstallationPlacement(
        Layout.native(), appdata_dir=data, capabilities=frozenset({"appdata"})
    )
    plan = plan_install(
        InstallationIdentity(
            app.schema.app_id,
            "path-matrix-test",
            "path_matrix_test",
            None,
            ("path-matrix-test",),
        ),
        InstallationSource("index", "path-matrix-test==1.0"),
        placement,
        UvToolTarget(tmp_path / "uv", tmp_path / "tools", tmp_path / "bin"),
        inspection=app.installation(environment=environment).inspect(),
    )
    pending = begin_operation(plan)
    assert pending.record is not None and pending.record.operation is not None
    assert pending.record.placement.appdata_dir == data
    assert retained.read_bytes() == b"retained work"
    assert lock.stat().st_ino == original_lock.st_ino


def test_path_bootstrap_environment_uses_one_layer_for_layout_and_root(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(app_id="bootstrap-test", paths=Paths(config=True))
    lower = tmp_path / "lower.env"
    lower.write_text(
        "BOOTSTRAP_TEST_LAYOUT=single-root\n"
        f"BOOTSTRAP_TEST_ROOT={tmp_path / 'lower-root'}\n",
        encoding="utf-8",
    )
    options = ResolveOptions(
        env_files=(lower,),
        env_file_overrides_os_environ=True,
    )

    paths = app.paths(
        options,
        environment={"BOOTSTRAP_TEST_ROOT": str(tmp_path / "process-root")},
    )

    assert paths.source == "environment"
    assert paths.layout == Layout.single_root(tmp_path / "lower-root")
    assert paths.config_dir == tmp_path / "lower-root" / "config"


def test_path_snapshot_is_independent_of_later_environment_changes(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(app_id="snapshot-test", paths=Paths(config=True))
    original_root = tmp_path / "original"
    environment = {
        "SNAPSHOT_TEST_ROOT": str(original_root),
        "SNAPSHOT_TEST_LAYOUT": "single-root",
    }

    paths = app.paths(environment=environment)
    environment["SNAPSHOT_TEST_ROOT"] = str(tmp_path / "later")

    assert paths.config_dir == original_root / "config"


@pytest.mark.parametrize(
    "kind", ("config", "appdata", "cache", "state", "logs")
)
def test_disabled_path_component_reports_exact_error(kind: PathKind) -> None:
    paths = _app((False, False, False, False)).paths(environment={})

    with pytest.raises(
        ValueError,
        match=f"^AppRC path component '{kind}' is not enabled\\.$",
    ):
        paths.require(kind)


def test_cache_only_path_resolution_does_not_read_or_write_managed_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "isolated"
    app = rc.AppRC(
        app_id="cache-only-test",
        paths=Paths(cache=True),
        layout=Layout.single_root(root),
    )

    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "apprc.toml"
    config_file.write_text("not = [ valid", encoding="utf-8")
    before = config_file.read_bytes()

    paths = app.paths(environment={})

    assert config_file.read_bytes() == before
    assert paths.cache_dir == root / "cache"
    assert paths.config_dir is None
    assert paths.appdata_dir is None
    assert paths.state_dir is None
    assert paths.logs_dir is None
    assert not (root / "cache").exists()


def test_relative_single_root_captures_normalized_invocation_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    app = rc.AppRC(
        app_id="relative-root-test",
        paths=Paths(cache=True),
    )

    paths = app.paths(
        ResolveOptions(layout=Layout.single_root(Path("nested/../root"))),
        environment={},
    )
    monkeypatch.chdir(tmp_path)

    assert paths.cache_dir == tmp_path / "working" / "root" / "cache"
    assert paths.layout.root == tmp_path / "working" / "root"
