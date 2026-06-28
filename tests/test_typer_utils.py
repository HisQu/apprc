from __future__ import annotations

from apprc.cli.config import config_request_skips_runtime_bootstrap
from apprc.cli.typer_utils import args_after_command, strip_leading_options


def test_strip_leading_options_handles_flags_values_and_separator() -> None:
    assert strip_leading_options(
        [
            "--skip-dotenv-layers",
            "--storage",
            "alpha",
            "--log-level=DEBUG",
            "config",
            "show",
        ],
        flag_options={"--skip-dotenv-layers"},
        value_options={"--storage", "--log-level"},
    ) == ["config", "show"]
    assert strip_leading_options(
        ["-s", "--storage", "alpha", "config", "show"],
        flag_options={"-s"},
        value_options={"--storage"},
    ) == ["config", "show"]
    assert strip_leading_options(
        ["-o", "--storage", "alpha", "config", "show"],
        flag_options={"-o"},
        value_options={"--storage"},
    ) == ["config", "show"]
    assert strip_leading_options(
        ["--storage", "alpha", "--", "config", "--json"],
        flag_options=set(),
        value_options={"--storage"},
    ) == ["config", "--json"]


def test_args_after_command_skips_root_options_before_command() -> None:
    assert args_after_command(
        "config",
        tokens=[
            "--env-file",
            "local.env",
            "--skip-dotenv-layers",
            "config",
            "doctor",
        ],
        root_value_options={"--env-file"},
    ) == ["doctor"]
    assert args_after_command(
        "config",
        tokens=["-s", "config", "doctor"],
        root_value_options={"--env-file"},
    ) == ["doctor"]
    assert args_after_command(
        "config",
        tokens=["-o", "config", "doctor"],
        root_value_options={"--env-file"},
    ) == ["doctor"]
    assert (
        args_after_command(
            "config",
            tokens=["tool", "run"],
            root_value_options={"--env-file"},
        )
        is None
    )


def test_config_request_skips_runtime_bootstrap_for_setup_only_commands() -> (
    None
):
    skips = config_request_skips_runtime_bootstrap

    assert skips(tokens=["config"]) is True
    assert skips(tokens=["config", "--help"]) is True
    assert skips(tokens=["config", "show", "--help"]) is True
    assert skips(tokens=["config", "show", "-h"]) is True
    assert skips(tokens=["config", "--json"]) is False
    assert skips(
        tokens=[
            "config",
            "--skip-dotenv-layers",
            "--storage",
            "alpha",
            "doctor",
        ]
    )
    assert skips(
        tokens=["--env-file", "local.env", "config", "doctor"],
        root_value_options={"--env-file"},
    )
    assert skips(tokens=["config", "app", "init"])
    assert skips(tokens=["config", "storage", "add", "alpha", "/tmp/storage"])
    assert skips(tokens=["config", "paths"])
    assert skips(tokens=["config", "show"]) is False
    assert skips(tokens=["tool", "run"]) is False
