from __future__ import annotations

import apprc
import apprc.cli as apprc_cli
from apprc.cli.bootstrap import bootstrap_cli_env
from apprc.cli.config import config_request_skips_runtime_bootstrap
from apprc.runtime_config import EnvConfig, env_field, env_owner
from apprc.runtime_config.kit import AppConfigKit


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
    assert (
        apprc_cli.config_request_skips_runtime_bootstrap
        is config_request_skips_runtime_bootstrap
    )
    assert "bootstrap_cli_env" in apprc_cli.__all__
    assert "config_request_skips_runtime_bootstrap" in apprc_cli.__all__
