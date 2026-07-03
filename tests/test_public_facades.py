"""Public facade and namespace surface tests."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import apprc
import apprc.cli as apprc_cli
import apprc.files as apprc_files
import apprc.interfaces as apprc_interfaces
import apprc.provenance as apprc_provenance
import apprc.storage as apprc_storage
from apprc.interfaces.cli._bootstrap import bootstrap_cli_env
from apprc.interfaces.cli.config_command import (
    ConfigSelectorContext,
    DefaultConfigCliState,
    config_request_skips_runtime,
)
from apprc.interfaces.cli.context import CliRuntimeOptions, cli_options_from
from apprc.interfaces.cli.mount import CliArgvProvider, mount_config_cli
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.interfaces.cli.runtime import (
    RuntimeIndependentCommand,
    CliRuntime,
    CliRuntimePolicy,
    CliRuntimeSession,
    CliRuntimeStateFactory,
    MountCliRuntimeStateFactory,
)
from apprc.public.app_rc import AppRC
from apprc.public.config import Config, ConfigBase
from apprc.public.field import field
from apprc.runtime.provenance import ConfigProvenance, provenance_of
from apprc.user_files import resolve_package_root, set_env_file_value
from apprc.user_files.storage_roots import StorageRegistry, register_storage

ROOT = Path(__file__).resolve().parents[1]
ROOT_FACADE_SNAPSHOT = ROOT / "tests" / "snapshots" / "apprc_root_facade.txt"


def test_root_facade_public_surface_matches_snapshot() -> None:
    """Make root facade changes intentional and easy to review."""
    expected_exports = ROOT_FACADE_SNAPSHOT.read_text(
        encoding="utf-8"
    ).splitlines()

    assert list(apprc.__all__) == expected_exports


def test_root_facade_exports_clean_public_api() -> None:
    """Root exposes only the clean public API and namespace modules."""
    assert apprc.AppRC is AppRC
    assert apprc.Config is Config
    assert apprc.ConfigBase is ConfigBase
    assert apprc.field is field
    assert apprc.cli is apprc_cli
    assert apprc.files is apprc_files
    assert apprc.provenance is apprc_provenance
    assert apprc.storage is apprc_storage

    assert not hasattr(apprc, "AppConfigKit")
    assert not hasattr(apprc, "EnvConfig")
    assert not hasattr(apprc, "env_field")
    assert not hasattr(apprc, "env_owner")
    assert not hasattr(apprc, "mount_config_cli")


def test_cli_namespace_exports_advanced_cli_symbols() -> None:
    """Advanced CLI APIs live under ``apprc.cli``."""
    assert apprc_cli.bootstrap_cli_env is bootstrap_cli_env
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
    assert apprc_cli.mount_config_cli is mount_config_cli
    assert apprc_cli.COMMON_CLI_FLAG_OPTIONS is COMMON_CLI_FLAG_OPTIONS
    assert apprc_cli.COMMON_CLI_VALUE_OPTIONS is COMMON_CLI_VALUE_OPTIONS
    assert (
        apprc_cli.config_request_skips_runtime is config_request_skips_runtime
    )

    assert "EnvFilesOption" in apprc_cli.__all__
    assert "EnvFileOverridesOption" in apprc_cli.__all__
    assert "SkipDotenvLayersOption" in apprc_cli.__all__
    assert "StorageOption" in apprc_cli.__all__
    assert "LogLevelOption" in apprc_cli.__all__
    assert "cli_runtime_options_to_args" in apprc_cli.__all__
    assert "cli_options_from" in apprc_cli.__all__
    assert "prepare_cli_runtime_context" in apprc_cli.__all__
    assert "state_from" in apprc_cli.__all__
    assert "exit_missing_action" in apprc_cli.__all__
    assert "ConfigEditorApp" in apprc_cli.__all__
    assert "ConfigSetupApp" in apprc_cli.__all__
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


def test_lazy_facade_stubs_match_runtime_exports() -> None:
    """Typed lazy facades must describe the same public names as runtime."""
    assert _stub_import_names(
        ROOT / "src" / "apprc" / "cli" / "__init__.pyi"
    ) == set(apprc_cli.__all__)
    assert _stub_import_names(
        ROOT / "src" / "apprc" / "interfaces" / "__init__.pyi"
    ) == set(apprc_interfaces.__all__)


def test_lazy_facade_runtime_inits_do_not_duplicate_type_exports() -> None:
    """Keep type-only facade declarations in stubs, not runtime modules."""
    for path in (
        ROOT / "src" / "apprc" / "cli" / "__init__.py",
        ROOT / "src" / "apprc" / "interfaces" / "__init__.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "TYPE_CHECKING" not in text
        assert "from apprc.interfaces.tui import" not in text


def test_storage_files_and_provenance_namespaces_export_helpers() -> None:
    """Advanced non-CLI helpers live under explicit namespaces."""
    assert apprc_storage.StorageRegistry is StorageRegistry
    assert apprc_storage.register_storage is register_storage
    assert apprc_files.resolve_package_root is resolve_package_root
    assert apprc_files.set_env_file_value is set_env_file_value
    assert apprc_provenance.ConfigProvenance is ConfigProvenance
    assert apprc_provenance.provenance_of is provenance_of


def _stub_import_names(path: Path) -> set[str]:
    """Return public names imported by one facade stub."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        names.update(alias.asname or alias.name for alias in node.names)
    return names


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
