"""Explicit configuration sessions must remain independent of process state."""

import copy
import os
import sys
import zipfile
from collections.abc import MutableMapping
from typing import cast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typed_settings.exceptions import InvalidSettingsError

import apprc as rc
from apprc.user_files.storage_roots.selector import StorageSelectorError


def declare_settings(**kwargs):
    """Create a fresh declaration so tests cannot share registration state."""
    app = rc.AppRC(app_id="resolution-test", **kwargs)

    @app.config("settings", prefix="RESOLVE_")
    class Settings(rc.Config):
        value: str = rc.field("RESOLVE_VALUE", default="fallback")
        count: int = rc.field("RESOLVE_COUNT", default=3)

    return app, Settings


def test_empty_environment_and_late_registration(monkeypatch):
    monkeypatch.setenv("RESOLVE_VALUE", "ambient")
    app, Settings = declare_settings()
    empty = app.resolve(environment={})
    captured = app.resolve()
    monkeypatch.setenv("RESOLVE_VALUE", "changed")
    assert empty.build(Settings).value == "fallback"
    assert captured.build(Settings).value == "ambient"
    assert Settings().value == "changed"

    @app.config("later", prefix="LATER_")
    class Later(rc.Config):
        value: int = rc.field("LATER_VALUE", default=1)

    with pytest.raises(ValueError, match="resolve again"):
        empty.build(Later)
    assert app.resolve(environment={}).build(Later).value == 1


def test_independent_storage_sessions_and_provenance(tmp_path, monkeypatch):
    app, Settings = declare_settings(
        storage=rc.Storage(), apprc_dir=tmp_path / "managed"
    )
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "apprc.storage.env").write_text("RESOLVE_VALUE=${CAPTURED}\n")
    monkeypatch.setenv("CAPTURED", "ambient")
    before = dict(os.environ)

    def build(index):
        resolved = app.resolve(
            rc.ResolveOptions(storage=str(roots[index])),
            environment={"CAPTURED": str(index)},
        )
        config = resolved.build(Settings)
        return resolved, config

    with ThreadPoolExecutor() as pool:
        pairs = list(pool.map(build, [0, 1]))
    for index, (resolved, config) in enumerate(pairs):
        assert config.value == str(index)
        assert (
            config.provenance_of("value").path
            == roots[index] / "apprc.storage.env"
        )
        assert config.provenance_of("value").origin == "shell_dotenv_storage"
        with pytest.raises(TypeError):
            cast(MutableMapping[str, str], resolved.values)["RESOLVE_VALUE"] = (
                "mutation"
            )
        assert copy.deepcopy(config).value == str(index)
    assert dict(os.environ) == before
    assert not (tmp_path / "managed").exists()


@pytest.mark.parametrize("override", [False, True])
def test_precedence_interpolation_and_explicit_export(
    tmp_path, monkeypatch, override
):
    app, Settings = declare_settings()
    dotenv = tmp_path / "run.env"
    dotenv.write_text("RESOLVE_VALUE=${INPUT}\nDEPENDENCY=value\n")
    monkeypatch.setenv("RESOLVE_VALUE", "untouched")
    monkeypatch.setenv("UNRELATED", "untouched")
    monkeypatch.delenv("DEPENDENCY", raising=False)
    resolved = app.resolve(
        rc.ResolveOptions(
            env_files=(dotenv,), env_file_overrides_os_environ=override
        ),
        environment={
            "INPUT": "file",
            "RESOLVE_VALUE": "captured",
            "UNRELATED": "old",
        },
    )
    expected = "file" if override else "captured"
    assert resolved.build(Settings).value == expected
    assert os.environ["RESOLVE_VALUE"] == "untouched"
    resolved.export_environment()
    assert os.environ["RESOLVE_VALUE"] == expected
    assert os.environ["DEPENDENCY"] == "value"
    assert os.environ["UNRELATED"] == "untouched"


def test_atomic_reload_resets_missing_values_and_protects_python():
    app, Settings = declare_settings()
    first = app.resolve(
        environment={"RESOLVE_VALUE": "first", "RESOLVE_COUNT": "4"}
    )
    config = first.build(Settings)
    bad = app.resolve(
        environment={"RESOLVE_VALUE": "changed", "RESOLVE_COUNT": "invalid"}
    )
    with pytest.raises(InvalidSettingsError):
        config.reload_from(bad)
    assert config.value == "first"
    assert config.count == 4
    assert config.provenance_of("value").origin == "shell_export_variable"
    config.value = "python"
    config.reload_from(app.resolve(environment={}))
    assert config.value == "python"
    assert config.count == 3
    config.reload_from(app.resolve(environment={}), override_python_values=True)
    assert config.value == "fallback"
    assert config.provenance_of("value").origin == "python_config_default"


def test_bundle_injection_factories_and_post_init():
    app = rc.AppRC(app_id="bundle-test")

    @app.config("settings", prefix="RESOLVE_")
    class Settings(rc.Config):
        value: str = rc.field("RESOLVE_VALUE", default="fallback")

    calls = []

    @app.config("python")
    class Python(rc.ConfigBase):
        count: int = 1

    @app.bundle
    @dataclass(kw_only=True)
    class Bundle:
        settings: Settings = field(default_factory=Settings)
        python: Python = field(default_factory=lambda: Python(count=2))

        def __post_init__(self):
            calls.append(self.settings.value)

    resolved = app.resolve(environment={"RESOLVE_VALUE": "resolved"})
    config = resolved.build(Bundle)
    assert config.settings.value == "resolved"
    assert config.python.count == 2
    assert calls == ["resolved"]

    @app.bundle
    @dataclass(kw_only=True)
    class Custom:
        settings: Settings = field(
            default_factory=lambda: Settings(value="custom")
        )

    resolved = app.resolve(environment={"RESOLVE_VALUE": "resolved"})
    with pytest.raises(TypeError, match="Inject 'settings' explicitly"):
        resolved.build(Custom)
    injected = resolved.build(Settings, value="injected")
    assert resolved.build(Custom, settings=injected).settings is injected


def test_optional_storage_does_not_suppress_invalid_selection(tmp_path):
    app, _ = declare_settings(
        storage=rc.Storage(), apprc_dir=tmp_path / "managed"
    )
    assert app.resolve(environment={}).selection is None
    with pytest.raises(StorageSelectorError):
        app.resolve(rc.ResolveOptions(storage_required=True), environment={})
    with pytest.raises(StorageSelectorError):
        app.resolve(
            rc.ResolveOptions(storage=str(tmp_path / "missing")), environment={}
        )
    assert list(tmp_path.iterdir()) == []


def test_zip_resource_retains_resource_identity(tmp_path, monkeypatch):
    archive = tmp_path / "defaults.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("resolution_resources/__init__.py", "")
        output.writestr(
            "resolution_resources/apprc.defaults.env",
            "RESOLVE_VALUE=packaged\n",
        )
    monkeypatch.syspath_prepend(str(archive))
    try:
        app, Settings = declare_settings(config_package="resolution_resources")
        resolved = app.resolve(environment={})
        config = resolved.build(Settings)
        assert config.value == "packaged"
        provenance = config.provenance_of("value")
        assert provenance.path is None
        assert provenance.resource == (
            "resolution_resources",
            "apprc.defaults.env",
        )
    finally:
        sys.modules.pop("resolution_resources", None)


def test_resolution_repr_never_prints_raw_values(tmp_path: Path):
    app, _ = declare_settings()
    resolved = app.resolve(environment={"RESOLVE_VALUE": "private-value"})
    assert "private-value" not in repr(resolved)
    assert "private-value" not in repr(resolved.layers)
    assert "private-value" not in repr(resolved.source)
