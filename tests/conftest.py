"""Pytest bootstrap helpers for repository-local example imports."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _required_apprc_prefixes(item: pytest.Item) -> list[str]:
    """Collect required bootstrap prefixes requested by test markers."""
    prefixes: set[str] = set()
    for marker in item.iter_markers(name="requires_apprc_env"):
        prefixes.update(marker.args)
    return sorted(prefixes)


def _bootstrap_env_keys_for(prefix: str) -> tuple[str, str]:
    """Return the optional registry key and required storage key."""
    return f"{prefix}_APPRC_TOML", f"{prefix}_STORAGE"


def _format_bootstrap_usage(prefix: str) -> str:
    """Build concise guidance for one required bootstrap prefix."""
    config_key, storage_key = _bootstrap_env_keys_for(prefix)
    apprc_toml_name = f"{prefix.lower()}.apprc.toml"
    return (
        f"{prefix}: set the storage variable in your shell startup (or env):\n"
        f'  export {storage_key}="/path/to/{prefix.lower()}-storage"\n'
        f"Optional multi-storage registry:\n"
        f'  export {config_key}="/absolute/path/to/{apprc_toml_name}"\n'
    )


def _bootstrap_contract_is_complete(prefix: str) -> bool:
    """Return whether required AppRC bootstrap variables are present."""
    _, storage_key = _bootstrap_env_keys_for(prefix)
    return bool(os.environ.get(storage_key))


def pytest_configure(config: pytest.Config) -> None:
    """Expose the example package and register AppRC test markers."""
    config.addinivalue_line(
        "markers",
        "requires_apprc_env(prefix): requires APP_STORAGE "
        "to be available before the test body runs.",
    )
    config.addinivalue_line(
        "markers",
        "allow_missing_apprc_env: skip AppRC bootstrap env enforcement for this "
        "test.",
    )
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
def _set_default_apprc_example_app_bootstrap(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Provide the common Example App bootstrap env for marked tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    if request.node.get_closest_marker("allow_missing_apprc_env") is not None:
        return
    if "APPRC_EXAMPLE_APP" not in _required_apprc_prefixes(request.node):
        return

    from tests.support_config import set_apprc_example_app_bootstrap

    set_apprc_example_app_bootstrap(monkeypatch, tmp_path)


def pytest_runtest_call(item: pytest.Item) -> None:
    """Fail fast when test-body AppRC bootstrap environment is missing."""
    if item.get_closest_marker("allow_missing_apprc_env") is not None:
        return
    prefixes = _required_apprc_prefixes(item)
    if not prefixes:
        return

    missing_messages: list[str] = []
    for prefix in prefixes:
        if _bootstrap_contract_is_complete(prefix):
            continue
        missing_messages.append(_format_bootstrap_usage(prefix))

    if not missing_messages:
        return

    raise pytest.UsageError(
        "AppRC bootstrap contract is incomplete:\n\n"
        + "\n".join(missing_messages)
    )
