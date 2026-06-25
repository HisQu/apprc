from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import apprc
import apprc.runtime_config.contract as contract_api
import apprc.runtime_config as config_api
from apprc.runtime_config import EnvConfig
from apprc.runtime_config.app_spec import AppConfigSpec
from apprc.runtime_config.contract.schema import ConfigField, ConfigOwner
from apprc.runtime_config.storage.local_env import LocalEnvUpdate
from apprc.runtime_config.storage.registry import StorageRegistry


def test_top_level_runtime_config_exports_are_public_api() -> None:
    assert apprc.EnvConfig is EnvConfig
    assert apprc.AppConfigSpec is AppConfigSpec
    assert config_api.AppConfigSpec is AppConfigSpec
    assert apprc.EnvBootstrapResult is config_api.EnvBootstrapResult
    assert not hasattr(apprc, "BaseEnv")
    assert not hasattr(config_api, "BaseEnv")


def test_old_provenance_names_are_not_public_api() -> None:
    assert not hasattr(apprc, "ConfigFieldSource")
    assert not hasattr(config_api, "ConfigFieldSource")
    assert not hasattr(apprc, "owner_default")
    assert not hasattr(config_api, "owner_default")


def test_top_level_facade_exports_stable_config_interfaces() -> None:
    assert apprc.ConfigOwner is ConfigOwner
    assert apprc.ConfigField is ConfigField
    assert apprc.LocalEnvUpdate is LocalEnvUpdate
    assert apprc.StorageRegistry is StorageRegistry
    assert callable(apprc.iter_config_fields)
    assert callable(apprc.resolve_package_root)
    assert callable(apprc.register_storage)
    assert callable(apprc.set_local_env_value)
    assert not hasattr(apprc, "ConfigEditorApp")


def test_runtime_config_facade_stays_narrow() -> None:
    assert not hasattr(config_api, "ConfigOwner")
    assert not hasattr(config_api, "ConfigField")
    assert not hasattr(config_api, "ConfigDoctorPayload")
    assert not hasattr(config_api, "StorageRegistry")
    assert not hasattr(config_api, "LocalEnvUpdate")
    assert not hasattr(contract_api, "AppConfigSpec")


def test_old_config_package_is_removed() -> None:
    removed_module = ".".join(("apprc", "config"))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_old_runtime_config_fields_package_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.runtime_config.fields")


def test_old_contract_app_spec_module_is_removed() -> None:
    removed_module = "apprc.runtime_config.contract.app_spec"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_contract_modules_do_not_import_config_objects_layer() -> None:
    contract_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "apprc"
        / "runtime_config"
        / "contract"
    )
    for path in contract_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            assert not node.module.startswith(
                "apprc.runtime_config.config_objects"
            ), f"{path} imports {node.module}"
