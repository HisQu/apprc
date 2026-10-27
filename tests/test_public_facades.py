"""Public facade and namespace surface tests."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import apprc
import apprc.cli as apprc_cli
import apprc.definition.env_config as config_models
import apprc.files as apprc_files
import apprc.provenance as apprc_provenance
import apprc.tui as apprc_tui
import apprc.workspaces as apprc_workspaces
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.interfaces.cli._resolution import resolve_cli_config
from apprc.interfaces.cli.config_command import (
    ConfigSelectorContext,
    DefaultConfigCliState,
    config_request_skips_runtime,
)
from apprc.interfaces.cli.context import CliRuntimeOptions, cli_options_from
from apprc.interfaces.cli.mount import CliArgvProvider, mount_app_cli
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.interfaces.cli.runtime import (
    CliRuntime,
    CliRuntimePolicy,
    CliRuntimeSession,
    CliRuntimeStateFactory,
    MountCliRuntimeStateFactory,
    RuntimeIndependentCommand,
)
from apprc.public.app_rc import AppRC
from apprc.public.config import Config, ConfigBase
from apprc.public.field import field
from apprc.runtime.provenance import ConfigProvenance, provenance_of
from apprc.user_files.workspace_roots.model import WorkspaceRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_root_facade_exports_clean_public_api() -> None:
    """Root exposes only the clean public API and namespace modules."""
    assert apprc.AppRC is AppRC
    assert apprc.Config is Config
    assert apprc.ConfigBase is ConfigBase
    assert apprc.UserDotenv is UserDotenv
    assert apprc.field is field
    assert apprc.cli is apprc_cli
    assert apprc.files is apprc_files
    assert apprc.provenance is apprc_provenance
    assert apprc.workspaces is apprc_workspaces

    assert not hasattr(apprc, "AppConfigKit")
    assert not hasattr(apprc, "EnvConfig")
    assert not hasattr(apprc, "env_field")
    assert not hasattr(apprc, "env_owner")
    assert not hasattr(apprc, "mount_app_cli")


def test_cli_namespace_exports_advanced_cli_symbols() -> None:
    """Advanced CLI APIs live under ``apprc.cli``."""
    assert apprc_cli.resolve_cli_config is resolve_cli_config
    assert apprc_cli.CliRuntimeOptions is CliRuntimeOptions
    assert apprc_cli.cli_options_from is cli_options_from
    assert apprc_cli.CliArgvProvider is CliArgvProvider
    assert apprc_cli.MountCliRuntimeStateFactory is MountCliRuntimeStateFactory
    assert apprc_cli.CliRuntime is CliRuntime
    assert apprc_cli.CliRuntimeSession is CliRuntimeSession
    assert apprc_cli.CliRuntimeStateFactory is CliRuntimeStateFactory
    assert apprc_cli.RuntimeIndependentCommand is RuntimeIndependentCommand
    assert apprc_cli.CliRuntimePolicy is CliRuntimePolicy
    assert apprc_cli.ConfigSelectorContext is ConfigSelectorContext
    assert apprc_cli.DefaultConfigCliState is DefaultConfigCliState
    assert apprc_cli.mount_app_cli is mount_app_cli
    assert apprc_cli.COMMON_CLI_FLAG_OPTIONS is COMMON_CLI_FLAG_OPTIONS
    assert apprc_cli.COMMON_CLI_VALUE_OPTIONS is COMMON_CLI_VALUE_OPTIONS
    assert (
        apprc_cli.config_request_skips_runtime is config_request_skips_runtime
    )

    assert "EnvFilesOption" in apprc_cli.__all__
    assert "EnvFileOverridesOption" in apprc_cli.__all__
    assert "SkipDotenvLayersOption" in apprc_cli.__all__
    assert "WorkspaceOption" in apprc_cli.__all__
    assert "LayoutOption" in apprc_cli.__all__
    assert "AppRootOption" in apprc_cli.__all__
    assert "StorageOption" not in apprc_cli.__all__
    assert "LogLevelOption" in apprc_cli.__all__
    assert "cli_runtime_options_to_args" in apprc_cli.__all__
    assert "cli_options_from" in apprc_cli.__all__
    assert "prepare_cli_runtime_context" in apprc_cli.__all__
    assert "state_from" in apprc_cli.__all__
    assert "exit_missing_action" in apprc_cli.__all__
    assert "ConfigEditorApp" in apprc_tui.__all__
    assert "ConfigSetupApp" in apprc_tui.__all__
    assert "COMMON_ROOT_FLAG_OPTIONS" not in apprc_cli.__all__
    assert "COMMON_ROOT_VALUE_OPTIONS" not in apprc_cli.__all__
    assert "CliStateFactory" not in apprc_cli.__all__


def test_public_facades_do_not_eagerly_import_textual() -> None:
    """Plain public imports must not require or load the optional TUI stack."""
    code = """
import json
import sys

import apprc
import apprc.cli
import apprc.interfaces

print(json.dumps(any(
    name == "textual" or name.startswith("textual.")
    for name in sys.modules
)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) is False


def test_lazy_facade_runtime_inits_do_not_duplicate_type_exports() -> None:
    """Keep type-only facade declarations in stubs, not runtime modules."""
    for path in (
        ROOT / "src" / "apprc" / "cli" / "__init__.py",
        ROOT / "src" / "apprc" / "interfaces" / "__init__.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "TYPE_CHECKING" not in text
        assert "from apprc.interfaces.tui import" not in text


def test_workspace_files_and_provenance_namespaces_export_helpers() -> None:
    """Advanced non-CLI helpers live under explicit namespaces."""
    assert apprc_workspaces.WorkspaceRegistry is WorkspaceRegistry
    assert not hasattr(apprc_workspaces, "register_workspace")
    assert not hasattr(apprc_files, "resolve_package_root")
    assert not hasattr(apprc_files, "set_env_file_value")
    assert apprc_provenance.ConfigProvenance is ConfigProvenance
    assert apprc_provenance.provenance_of is provenance_of


def test_legacy_aggregate_packages_are_not_public_facades() -> None:
    """Lower-level aggregate packages stay importable but export no API."""
    legacy_exports = {
        "apprc.definition": {
            "AppRC",
            "AppConfigSpec",
            "ConfigField",
            "ConfigOwner",
            "EnvConfig",
            "env_field",
            "env_owner",
        },
        "apprc.runtime": {
            "ConfigProvenance",
            "ResolvedConfig",
            "bootstrap_env",
            "provenance_of",
        },
        "apprc.user_files": {
            "EnvFileUpdate",
            "WorkspaceRegistry",
            "resolve_package_root",
            "set_env_file_value",
        },
        "apprc.user_files.workspace_roots": {
            "WorkspaceRegistry",
            "WorkspaceSelection",
            "register_workspace",
            "write_workspace_registry",
        },
    }

    for module_name, names in legacy_exports.items():
        module = importlib.import_module(module_name)
        assert not hasattr(module, "__all__")
        for name in names:
            assert not hasattr(module, name)


def test_internal_config_package_does_not_expose_legacy_declarations() -> None:
    """The internal package must not revive the removed authoring API."""
    assert not hasattr(config_models, "Config")
    assert not hasattr(config_models, "EnvConfig")
    assert not hasattr(config_models, "env_field")
    assert not hasattr(config_models, "env_owner")
    assert not hasattr(config_models, "config_owner_for")

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.definition.env_config.fields")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apprc.definition.env_config.env")


def test_public_docs_do_not_reference_unreleased_runtime_names() -> None:
    """Keep public docs aligned with the pre-release runtime API."""
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "README.pypi.md",
            "docs/How-To-User-Guides.md",
            "docs/References.md",
            "CHANGELOG.md",
        )
    )

    assert "`CliStateFactory`" not in docs
    assert "runtime_policy=..." in docs
    assert "COMMON_ROOT_FLAG_OPTIONS" not in docs
    assert "COMMON_ROOT_VALUE_OPTIONS" not in docs
    assert "config_policy=" not in docs
    assert 'config_group_name="config"' not in docs
    assert "actions={" not in docs
    current_docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "README.pypi.md",
            "docs/How-To-User-Guides.md",
            "docs/References.md",
        )
    )
    assert "apprc[logging]" not in current_docs
    assert "Optional Logging" not in current_docs
    assert "src/apprc/logging" not in current_docs
