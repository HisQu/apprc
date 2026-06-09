from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest

import apprc.paths as legacy_paths


def test_legacy_paths_import_does_not_resolve_root_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(legacy_paths, "ROOT_STORAGE", raising=False)

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
