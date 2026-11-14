from __future__ import annotations

import pytest
import typer

from apprc.interfaces.cli.config_command import (
    config_request_skips_runtime,
)
from apprc.interfaces.cli._typer_utils import (
    args_after_command,
    args_after_cli_command,
    help_requested_before_separator,
    parse_leading_options,
    run_typer_app,
    strip_leading_options,
    structural_help_requested,
)


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


def test_parse_leading_options_exposes_separator_and_unknown_options() -> None:
    parsed = parse_leading_options(
        ["--storage", "alpha", "--", "--help"],
        flag_options=set(),
        value_options={"--storage"},
    )
    unknown = parse_leading_options(
        ["--unknown", "config"],
        flag_options=set(),
        value_options=set(),
    )

    assert parsed.action_tokens == ("--help",)
    assert parsed.separator_before_action is True
    assert parsed.unknown_option_before_action is False
    assert unknown.action_tokens == ("--unknown", "config")
    assert unknown.separator_before_action is False
    assert unknown.unknown_option_before_action is True


def test_args_after_command_skips_root_options_before_command() -> None:
    assert args_after_command(
        "config",
        tokens=[
            "--env-file",
            "local.env",
            "--skip-dotenv-layers",
            "config",
            "setup",
        ],
        root_value_options={"--env-file"},
    ) == ["setup"]
    assert args_after_command(
        "config",
        tokens=["-s", "config", "setup"],
        root_value_options={"--env-file"},
    ) == ["setup"]
    assert args_after_command(
        "config",
        tokens=["-o", "config", "setup"],
        root_value_options={"--env-file"},
    ) == ["setup"]
    assert (
        args_after_command(
            "config",
            tokens=["tool", "run"],
            root_value_options={"--env-file"},
        )
        is None
    )
    assert args_after_cli_command(
        "config",
        tokens=["--env-file", "local.env", "config", "setup"],
        cli_value_options={"--env-file"},
    ) == ["setup"]


def test_structural_help_helpers_preserve_value_and_separator_tokens() -> None:
    assert help_requested_before_separator(
        ["show", "--help"],
        value_options=set(),
    )
    assert not help_requested_before_separator(
        ["show", "--", "--help"],
        value_options=set(),
    )
    assert not help_requested_before_separator(
        ["--text", "--help"],
        value_options={"--text"},
    )
    assert help_requested_before_separator(
        ["--env-file", "--help", "app", "doctor", "--help"],
        value_options={"--env-file"},
    )
    assert not help_requested_before_separator(
        ["--env-file", "--help", "app", "doctor", "--", "--help"],
        value_options={"--env-file"},
    )
    assert not help_requested_before_separator(
        ["--env-file=--help", "app", "doctor"],
        value_options={"--env-file"},
    )
    assert structural_help_requested(["cache", "--help"])
    assert not structural_help_requested(["cache", "--json", "--help"])


def test_config_request_skips_runtime_for_setup_only_commands() -> None:
    skips = config_request_skips_runtime

    assert skips(tokens=["config"]) is True
    assert skips(tokens=["config", "--help"]) is True
    assert skips(tokens=["config", "show", "--help"]) is True
    assert skips(tokens=["config", "show", "-h"]) is True
    assert skips(tokens=["config", "--json"]) is True
    assert (
        skips(tokens=["config", "--json"], skip_invalid_options=False) is False
    )
    assert (
        skips(
            tokens=["config", "set", "profile", "demo"],
            runtime_independent_actions={"setup"},
        )
        is False
    )
    assert skips(
        tokens=[
            "config",
            "--skip-dotenv-layers",
            "--workspace",
            "alpha",
            "setup",
        ]
    )
    assert skips(
        tokens=["--env-file", "local.env", "config", "setup"],
        root_value_options={"--env-file"},
    )
    assert skips(
        tokens=["config", "--custom-env", "local.env", "setup"],
        root_value_options={"--custom-env"},
    )
    assert skips(tokens=["config", "show", "--", "--help"]) is False
    assert skips(tokens=["config", "--", "--help"]) is False
    assert (
        skips(tokens=["--workspace", "alpha", "config", "--", "--help"])
        is False
    )
    assert skips(tokens=["config", "setup"])
    assert skips(tokens=["config", "show"]) is False
    assert skips(tokens=["tool", "run"]) is False


@pytest.mark.parametrize("status", [7, 23])
def test_forwarded_typer_callback_preserves_nonzero_status(status: int) -> None:
    app = typer.Typer()

    @app.command()
    def command() -> int:
        return status

    with pytest.raises(typer.Exit) as error:
        run_typer_app(app, args=[], prog_name="forwarded")

    assert error.value.exit_code == status


def test_forwarded_typer_callback_preserves_explicit_exit() -> None:
    app = typer.Typer()

    @app.command()
    def command() -> None:
        raise typer.Exit(code=19)

    with pytest.raises(typer.Exit) as error:
        run_typer_app(app, args=[], prog_name="forwarded")

    assert error.value.exit_code == 19


def test_forwarded_typer_usage_error_preserves_exit_status() -> None:
    app = typer.Typer()

    @app.command()
    def command(value: int) -> None:
        pass

    with pytest.raises(typer.Exit) as error:
        run_typer_app(app, args=["not-an-integer"], prog_name="forwarded")

    assert error.value.exit_code == 2


def test_forwarded_typer_callback_does_not_suppress_programming_error() -> None:
    app = typer.Typer()
    failure = RuntimeError("callback failed")

    @app.command()
    def command() -> None:
        raise failure

    with pytest.raises(RuntimeError) as error:
        run_typer_app(app, args=[], prog_name="forwarded")

    assert error.value is failure
