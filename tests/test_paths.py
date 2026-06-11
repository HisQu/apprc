from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest

import apprc.paths as legacy_paths


def test_legacy_paths_import_does_not_resolve_root_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(legacy_paths.__dict__, "ROOT_STORAGE", raising=False)

    def fail_root_lookup(*args: object, **kwargs: object) -> Path:
        raise AssertionError("ROOT_STORAGE should be lazy")

    monkeypatch.setattr(
        legacy_paths.ut,
        "get_local_dir_from_env",
        fail_root_lookup,
    )

    paths = reload(legacy_paths)

    assert paths.ROOT_PKG.name == "apprc"
    with pytest.raises(AssertionError, match="ROOT_STORAGE should be lazy"):
        _ = paths.ROOT_STORAGE


def test_legacy_root_storage_uses_quarantined_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_root_lookup(*args: object, **kwargs: object) -> Path:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Path("/tmp/apprc-legacy-storage")

    monkeypatch.setattr(
        legacy_paths.ut,
        "get_local_dir_from_env",
        fake_root_lookup,
    )

    assert legacy_paths.root_storage() == Path("/tmp/apprc-legacy-storage")
    assert captured["kwargs"] == {
        "env_var": "APPRC_LEGACY_STORAGE",
        "env_file": ".env.template",
    }
