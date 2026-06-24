from __future__ import annotations

import importlib

import pytest

import apprc
import apprc.runtime_config as config_api
from apprc.runtime_config import EnvConfig


def test_top_level_runtime_config_exports_are_public_api() -> None:
    assert apprc.EnvConfig is EnvConfig
    assert apprc.EnvBootstrapResult is config_api.EnvBootstrapResult
    assert not hasattr(apprc, "BaseEnv")
    assert not hasattr(config_api, "BaseEnv")


def test_old_provenance_names_are_not_public_api() -> None:
    assert not hasattr(apprc, "ConfigFieldSource")
    assert not hasattr(config_api, "ConfigFieldSource")
    assert not hasattr(apprc, "owner_default")
    assert not hasattr(config_api, "owner_default")


def test_schema_types_are_not_public_facade_exports() -> None:
    assert not hasattr(apprc, "ConfigOwner")
    assert not hasattr(apprc, "ConfigField")
    assert not hasattr(config_api, "ConfigOwner")
    assert not hasattr(config_api, "ConfigField")


def test_old_config_package_is_removed() -> None:
    removed_module = ".".join(("apprc", "config"))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)
