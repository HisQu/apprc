from __future__ import annotations

import re
from pathlib import Path

import apprc
import apprc.cli as apprc_cli
from apprc.cli.bootstrap import bootstrap_cli_env
from apprc.cli.bridge import (
    BootstraplessCommand,
    ConfigCliBridge,
    ConfigCliSession,
    ConfigCliStateFactory,
    HostCliBootstrapPolicy,
    MountConfigCliStateFactory,
)
from apprc.cli.config import (
    ConfigSelectorContext,
    DefaultConfigCliState,
    config_request_skips_runtime_bootstrap,
)
from apprc.cli.context import CliBootstrapOptions
from apprc.cli.integration import (
    CliArgvProvider,
    mount_config_cli,
)
from apprc.runtime_config import EnvConfig, env_field, env_owner
from apprc.runtime_config.kit import AppConfigKit

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
    assert apprc_cli.bootstrap_cli_env is bootstrap_cli_env
    assert apprc_cli.CliBootstrapOptions is CliBootstrapOptions
    assert apprc_cli.CliArgvProvider is CliArgvProvider
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
    assert re.search(r"(?<!extra_)host_flag_options=", docs) is None
    assert re.search(r"(?<!extra_)host_value_options=", docs) is None
