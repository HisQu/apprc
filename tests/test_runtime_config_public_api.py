from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import apprc
import apprc.definition as definition_api
import apprc.definition.env_config as contract_api
import apprc.runtime as runtime_api
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.user_files.env_files.updates import EnvFileUpdate
from apprc.user_files.storage_roots.model import StorageRegistry


def test_root_facade_exports_public_config_api() -> None:
    assert apprc.EnvConfig is EnvConfig
    assert apprc.AppConfigSpec is AppConfigSpec
    assert definition_api.AppConfigSpec is AppConfigSpec
    assert apprc.EnvBootstrapResult is runtime_api.EnvBootstrapResult
    assert not hasattr(apprc, "BaseEnv")
    assert not hasattr(definition_api, "BaseEnv")


def test_old_provenance_names_are_not_public_api() -> None:
    assert not hasattr(apprc, "ConfigFieldSource")
    assert not hasattr(runtime_api, "ConfigFieldSource")
    assert not hasattr(apprc, "owner_default")
    assert not hasattr(runtime_api, "owner_default")


def test_top_level_facade_exports_stable_config_interfaces() -> None:
    assert apprc.ConfigOwner is ConfigOwner
    assert apprc.ConfigField is ConfigField
    assert apprc.EnvFileUpdate is EnvFileUpdate
    assert apprc.StorageRegistry is StorageRegistry
    assert callable(apprc.iter_config_fields)
    assert callable(apprc.resolve_package_root)
    assert callable(apprc.register_storage)
    assert callable(apprc.set_storage_env_value)
    assert apprc.ConfigEditorApp is not None


def test_definition_and_runtime_facades_stay_owned() -> None:
    assert definition_api.ConfigOwner is ConfigOwner
    assert definition_api.ConfigField is ConfigField
    assert not hasattr(runtime_api, "StorageRegistry")
    assert not hasattr(runtime_api, "EnvFileUpdate")
    assert not hasattr(contract_api, "AppConfigSpec")


def test_old_config_package_is_removed() -> None:
    removed_module = ".".join(("apprc", "config"))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_old_runtime_config_fields_package_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.runtime_config.fields")


def test_old_runtime_config_package_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.runtime_config")


def test_logging_package_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.logging")


def test_logging_symbols_are_not_root_exports() -> None:
    removed_names = {
        "AppLogger",
        "LoggingConfig",
        "LoggingRenderer",
        "get_logger",
        "setup_logging",
    }

    assert removed_names.isdisjoint(apprc.__all__)
    for name in removed_names:
        assert not hasattr(apprc, name)


def test_old_contract_app_spec_module_is_removed() -> None:
    removed_module = "apprc.definition.env_config.app_spec"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_env_config_modules_do_not_import_app_config_layer() -> None:
    env_config_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "apprc"
        / "definition"
        / "env_config"
    )
    for path in env_config_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            assert not node.module.startswith("apprc.definition.app_config"), (
                f"{path} imports {node.module}"
            )
