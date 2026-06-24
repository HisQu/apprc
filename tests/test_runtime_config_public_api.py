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


def test_schema_types_are_not_public_facade_exports() -> None:
    assert not hasattr(apprc, "ConfigOwner")
    assert not hasattr(apprc, "ConfigField")
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


def test_old_contract_app_spec_module_is_removed() -> None:
    removed_module = "apprc.runtime_config.contract.app_spec"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_contract_modules_do_not_import_fields_layer() -> None:
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
            assert not node.module.startswith("apprc.runtime_config.fields"), (
                f"{path} imports {node.module}"
            )
