"""Pytest bootstrap helpers for repository-local example imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Expose the example package for repository-local tests."""
    del config
    example_src = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "example_apps"
        / "src"
    )
    example_src_text = str(example_src)
    if example_src_text not in sys.path:
        sys.path.insert(0, example_src_text)


@pytest.fixture(autouse=True)
def _isolate_native_app_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep platform-native AppRC locations inside each test's temporary home."""
    test_home = tmp_path / "data-home"
    monkeypatch.setenv("HOME", str(test_home / "home"))
    monkeypatch.setenv("USERPROFILE", str(test_home / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(test_home / "data"))
    monkeypatch.setenv("APPDATA", str(test_home / "config"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(test_home / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(test_home / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(test_home / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(test_home / "state"))
