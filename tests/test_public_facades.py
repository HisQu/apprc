from __future__ import annotations

import re
from pathlib import Path

import apprc
import apprc.interfaces.cli as apprc_cli
from apprc.interfaces.cli._bootstrap import bootstrap_cli_env
from apprc.interfaces.cli.runtime import (
    RuntimeIndependentCommand,
    CliRuntime,
    CliRuntimeSession,
    CliRuntimeStateFactory,
    CliRuntimePolicy,
    MountCliRuntimeStateFactory,
)
from apprc.interfaces.cli.config_command import (
    ConfigSelectorContext,
    DefaultConfigCliState,
    config_request_skips_runtime,
)
from apprc.interfaces.cli.context import CliRuntimeOptions, cli_options_from
from apprc.interfaces.cli.mount import (
    CliArgvProvider,
    mount_config_cli,
)
from apprc.interfaces.cli.options import (
    COMMON_CLI_FLAG_OPTIONS,
    COMMON_CLI_VALUE_OPTIONS,
)
from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import env_field, env_owner

ROOT = Path(__file__).resolve().parents[1]
ROOT_FACADE_SNAPSHOT = ROOT / "tests" / "snapshots" / "apprc_root_facade.txt"


def test_root_facade_public_surface_matches_snapshot() -> None:
    """Make root facade changes intentional and easy to review."""
    expected_exports = ROOT_FACADE_SNAPSHOT.read_text(
        encoding="utf-8"
    ).splitlines()

    assert list(apprc.__all__) == expected_exports


def test_root_facade_exports_config_symbols_needed_by_cunf() -> None:
    """Keep application imports on AppRC's public root facade."""
    assert apprc.AppConfigKit is AppConfigKit
    assert apprc.EnvConfig is EnvConfig
    assert apprc.env_field is env_field
    assert apprc.env_owner is env_owner
    assert "AppConfigKit" in apprc.__all__
    assert "EnvConfig" in apprc.__all__
    assert "env_field" in apprc.__all__
    assert "env_owner" in apprc.__all__


def test_cli_facade_exports_bootstrap_symbols_needed_by_cunf() -> None:
    """Keep application CLI bootstrap imports on AppRC's public CLI facade."""
    assert apprc.bootstrap_cli_env is bootstrap_cli_env
    assert apprc.CliRuntimeOptions is CliRuntimeOptions
    assert apprc.cli_options_from is cli_options_from
    assert apprc.CliArgvProvider is CliArgvProvider
    assert apprc.MountCliRuntimeStateFactory is MountCliRuntimeStateFactory
    assert apprc.CliRuntime is CliRuntime
    assert apprc.CliRuntimeSession is CliRuntimeSession
    assert apprc.CliRuntimeStateFactory is CliRuntimeStateFactory
    assert apprc.RuntimeIndependentCommand is RuntimeIndependentCommand
    assert apprc.CliRuntimePolicy is CliRuntimePolicy
    assert apprc.ConfigSelectorContext is ConfigSelectorContext
    assert apprc.DefaultConfigCliState is DefaultConfigCliState
    assert apprc.mount_config_cli is mount_config_cli
    assert apprc.COMMON_CLI_FLAG_OPTIONS is COMMON_CLI_FLAG_OPTIONS
    assert apprc.COMMON_CLI_VALUE_OPTIONS is COMMON_CLI_VALUE_OPTIONS
    assert "EnvFilesOption" in apprc.__all__
    assert "EnvFileOverridesOption" in apprc.__all__
    assert "SkipDotenvLayersOption" in apprc.__all__
    assert "StorageOption" in apprc.__all__
    assert "LogLevelOption" in apprc.__all__
    assert "cli_runtime_options_to_args" in apprc.__all__
    assert "cli_options_from" in apprc.__all__
    assert "prepare_cli_runtime_context" in apprc.__all__
    assert "state_from" in apprc.__all__
    assert "exit_missing_action" in apprc.__all__
    assert apprc_cli.bootstrap_cli_env is bootstrap_cli_env
    assert apprc_cli.CliRuntimeOptions is CliRuntimeOptions
    assert apprc_cli.cli_options_from is cli_options_from
    assert apprc_cli.CliArgvProvider is CliArgvProvider
    assert apprc_cli.COMMON_CLI_FLAG_OPTIONS is COMMON_CLI_FLAG_OPTIONS
    assert apprc_cli.COMMON_CLI_VALUE_OPTIONS is COMMON_CLI_VALUE_OPTIONS
    assert not hasattr(apprc_cli, "COMMON_ROOT_FLAG_OPTIONS")
    assert not hasattr(apprc_cli, "COMMON_ROOT_VALUE_OPTIONS")
    assert not hasattr(apprc_cli, "CliStateFactory")
    assert apprc_cli.MountCliRuntimeStateFactory is MountCliRuntimeStateFactory
    assert apprc_cli.CliRuntime is CliRuntime
    assert apprc_cli.CliRuntimeSession is CliRuntimeSession
    assert apprc_cli.CliRuntimeStateFactory is CliRuntimeStateFactory
    assert apprc_cli.RuntimeIndependentCommand is RuntimeIndependentCommand
    assert apprc_cli.CliRuntimePolicy is CliRuntimePolicy
    assert apprc_cli.ConfigSelectorContext is ConfigSelectorContext
    assert apprc_cli.DefaultConfigCliState is DefaultConfigCliState
    assert apprc_cli.mount_config_cli is mount_config_cli
    assert (
        apprc_cli.config_request_skips_runtime is config_request_skips_runtime
    )
    assert "bootstrap_cli_env" in apprc_cli.__all__
    assert "COMMON_CLI_FLAG_OPTIONS" in apprc_cli.__all__
    assert "COMMON_CLI_VALUE_OPTIONS" in apprc_cli.__all__
    assert "COMMON_ROOT_FLAG_OPTIONS" not in apprc_cli.__all__
    assert "COMMON_ROOT_VALUE_OPTIONS" not in apprc_cli.__all__
    assert "CliRuntimeOptions" in apprc_cli.__all__
    assert "cli_options_from" in apprc_cli.__all__
    assert "CliArgvProvider" in apprc_cli.__all__
    assert "CliStateFactory" not in apprc_cli.__all__
    assert "MountCliRuntimeStateFactory" in apprc_cli.__all__
    assert "CliRuntime" in apprc_cli.__all__
    assert "CliRuntimeSession" in apprc_cli.__all__
    assert "CliRuntimeStateFactory" in apprc_cli.__all__
    assert "RuntimeIndependentCommand" in apprc_cli.__all__
    assert "CliRuntimePolicy" in apprc_cli.__all__
    assert "ConfigSelectorContext" in apprc_cli.__all__
    assert "DefaultConfigCliState" in apprc_cli.__all__
    assert "config_request_skips_runtime" in apprc_cli.__all__
    assert "mount_config_cli" in apprc_cli.__all__


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
    assert re.search(r"(?<!extra_)cli_flag_options=", docs) is None
    assert re.search(r"(?<!extra_)cli_value_options=", docs) is None
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
