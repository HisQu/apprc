from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import apprc
import apprc.definition as definition_api
import apprc.definition.env_config as contract_api
import apprc.files as files_api
import apprc.provenance as provenance_api
import apprc.runtime as runtime_api
import apprc.schema as schema_api
import apprc.storage as storage_api
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.public.app_rc import AppRC
from apprc.public.config import Config, ConfigBase
from apprc.runtime.result import EnvBootstrapResult
from apprc.user_files.env_files.updates import EnvFileUpdate
from apprc.user_files.storage_roots.model import StorageRegistry
from apprc.interfaces.tui.editor.storage_base import StorageWorkflowBase


def test_root_facade_exports_public_config_api() -> None:
    assert apprc.AppRC is AppRC
    assert apprc.Config is Config
    assert apprc.ConfigBase is ConfigBase
    assert hasattr(apprc, "field")
    assert not hasattr(apprc, "EnvConfig")
    assert not hasattr(apprc, "AppConfigSpec")
    assert AppConfigSpec.__name__ == "AppConfigSpec"
    assert EnvBootstrapResult.__name__ == "EnvBootstrapResult"
    assert not hasattr(apprc, "BaseEnv")
    assert not hasattr(definition_api, "BaseEnv")


def test_old_provenance_names_are_not_public_api() -> None:
    assert not hasattr(apprc, "ConfigFieldSource")
    assert not hasattr(runtime_api, "ConfigFieldSource")
    assert not hasattr(apprc, "owner_default")
    assert not hasattr(runtime_api, "owner_default")


def test_top_level_facade_exports_stable_config_interfaces() -> None:
    assert schema_api.ConfigOwner is ConfigOwner
    assert schema_api.ConfigField is ConfigField
    assert files_api.EnvFileUpdate is EnvFileUpdate
    assert storage_api.StorageRegistry is StorageRegistry
    assert callable(files_api.resolve_package_root)
    assert callable(storage_api.register_storage)
    assert callable(files_api.set_storage_env_value)
    assert callable(provenance_api.provenance_of)


def test_definition_and_runtime_facades_stay_owned() -> None:
    assert not hasattr(definition_api, "ConfigOwner")
    assert not hasattr(definition_api, "ConfigField")
    assert not hasattr(definition_api, "AppConfigKit")
    assert not hasattr(runtime_api, "StorageRegistry")
    assert not hasattr(runtime_api, "EnvFileUpdate")
    assert not hasattr(runtime_api, "EnvBootstrapResult")
    assert not hasattr(contract_api, "AppConfigSpec")


def test_supported_helper_namespaces_are_lazy_boundaries() -> None:
    """Supported helper namespaces own lazy public exports."""
    assert importlib.import_module("apprc.files").__all__
    assert importlib.import_module("apprc.storage").__all__
    assert not hasattr(importlib.import_module("apprc.runtime"), "__all__")
    assert not hasattr(importlib.import_module("apprc.user_files"), "__all__")
    assert not hasattr(
        importlib.import_module("apprc.user_files.storage_roots"),
        "__all__",
    )


def test_storage_workflow_base_does_not_define_cross_workflow_stubs() -> None:
    """Storage leaf workflows must not inherit placeholder cross-actions."""
    assert not hasattr(StorageWorkflowBase, "register_storage_directory_flow")
    assert not hasattr(StorageWorkflowBase, "remove_live_storage")


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
