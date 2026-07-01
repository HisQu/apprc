from __future__ import annotations

import re
from pathlib import Path

import apprc
import apprc.interfaces.cli as apprc_cli
from apprc.interfaces.cli._bootstrap import bootstrap_cli_env
from apprc.interfaces.cli.bridge import (
    BootstraplessCommand,
    ConfigCliBridge,
    ConfigCliSession,
    ConfigCliStateFactory,
    HostCliBootstrapPolicy,
    MountConfigCliStateFactory,
)
from apprc.interfaces.cli.config_command import (
    ConfigSelectorContext,
    DefaultConfigCliState,
    config_request_skips_runtime_bootstrap,
)
from apprc.interfaces.cli.context import CliBootstrapOptions
from apprc.interfaces.cli.mount import (
    CliArgvProvider,
    mount_config_cli,
)
from apprc.interfaces.cli.options import (
    COMMON_HOST_FLAG_OPTIONS,
    COMMON_HOST_VALUE_OPTIONS,
)
from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import env_field, env_owner

ROOT = Path(__file__).resolve().parents[1]


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
    assert apprc.CliBootstrapOptions is CliBootstrapOptions
    assert apprc.CliArgvProvider is CliArgvProvider
    assert apprc.MountConfigCliStateFactory is MountConfigCliStateFactory
    assert apprc.ConfigCliBridge is ConfigCliBridge
    assert apprc.ConfigCliSession is ConfigCliSession
    assert apprc.ConfigCliStateFactory is ConfigCliStateFactory
    assert apprc.BootstraplessCommand is BootstraplessCommand
    assert apprc.HostCliBootstrapPolicy is HostCliBootstrapPolicy
    assert apprc.ConfigSelectorContext is ConfigSelectorContext
    assert apprc.DefaultConfigCliState is DefaultConfigCliState
    assert apprc.mount_config_cli is mount_config_cli
    assert apprc.COMMON_HOST_FLAG_OPTIONS is COMMON_HOST_FLAG_OPTIONS
    assert apprc.COMMON_HOST_VALUE_OPTIONS is COMMON_HOST_VALUE_OPTIONS
    assert "EnvFilesOption" in apprc.__all__
    assert "EnvFileOverridesOption" in apprc.__all__
    assert "SkipDotenvLayersOption" in apprc.__all__
    assert "StorageOption" in apprc.__all__
    assert "LogLevelOption" in apprc.__all__
    assert "apprc_options_to_args" in apprc.__all__
    assert "prepare_typer_context" in apprc.__all__
    assert "state_from" in apprc.__all__
    assert "exit_missing_action" in apprc.__all__
    assert apprc_cli.bootstrap_cli_env is bootstrap_cli_env
    assert apprc_cli.CliBootstrapOptions is CliBootstrapOptions
    assert apprc_cli.CliArgvProvider is CliArgvProvider
    assert apprc_cli.COMMON_HOST_FLAG_OPTIONS is COMMON_HOST_FLAG_OPTIONS
    assert apprc_cli.COMMON_HOST_VALUE_OPTIONS is COMMON_HOST_VALUE_OPTIONS
    assert not hasattr(apprc_cli, "COMMON_ROOT_FLAG_OPTIONS")
    assert not hasattr(apprc_cli, "COMMON_ROOT_VALUE_OPTIONS")
    assert not hasattr(apprc_cli, "CliStateFactory")
    assert apprc_cli.MountConfigCliStateFactory is MountConfigCliStateFactory
    assert apprc_cli.ConfigCliBridge is ConfigCliBridge
    assert apprc_cli.ConfigCliSession is ConfigCliSession
    assert apprc_cli.ConfigCliStateFactory is ConfigCliStateFactory
    assert apprc_cli.BootstraplessCommand is BootstraplessCommand
    assert apprc_cli.HostCliBootstrapPolicy is HostCliBootstrapPolicy
    assert apprc_cli.ConfigSelectorContext is ConfigSelectorContext
    assert apprc_cli.DefaultConfigCliState is DefaultConfigCliState
    assert apprc_cli.mount_config_cli is mount_config_cli
    assert (
        apprc_cli.config_request_skips_runtime_bootstrap
        is config_request_skips_runtime_bootstrap
    )
    assert "bootstrap_cli_env" in apprc_cli.__all__
    assert "COMMON_HOST_FLAG_OPTIONS" in apprc_cli.__all__
    assert "COMMON_HOST_VALUE_OPTIONS" in apprc_cli.__all__
    assert "COMMON_ROOT_FLAG_OPTIONS" not in apprc_cli.__all__
    assert "COMMON_ROOT_VALUE_OPTIONS" not in apprc_cli.__all__
    assert "CliBootstrapOptions" in apprc_cli.__all__
    assert "CliArgvProvider" in apprc_cli.__all__
    assert "CliStateFactory" not in apprc_cli.__all__
    assert "MountConfigCliStateFactory" in apprc_cli.__all__
    assert "ConfigCliBridge" in apprc_cli.__all__
    assert "ConfigCliSession" in apprc_cli.__all__
    assert "ConfigCliStateFactory" in apprc_cli.__all__
    assert "BootstraplessCommand" in apprc_cli.__all__
    assert "HostCliBootstrapPolicy" in apprc_cli.__all__
    assert "ConfigSelectorContext" in apprc_cli.__all__
    assert "DefaultConfigCliState" in apprc_cli.__all__
    assert "config_request_skips_runtime_bootstrap" in apprc_cli.__all__
    assert "mount_config_cli" in apprc_cli.__all__


def test_public_docs_do_not_reference_unreleased_bridge_names() -> None:
    """Keep public docs aligned with the pre-release bridge API."""
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
    assert "bootstrap_policy=..." in docs
    assert "COMMON_ROOT_FLAG_OPTIONS" not in docs
    assert "COMMON_ROOT_VALUE_OPTIONS" not in docs
    assert "config_policy=" not in docs
    assert 'config_group_name="config"' not in docs
    assert "actions={" not in docs
    assert re.search(r"(?<!extra_)host_flag_options=", docs) is None
    assert re.search(r"(?<!extra_)host_value_options=", docs) is None
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
