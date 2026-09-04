"""Shared helpers for the repository-local AppRC example CLIs."""

from __future__ import annotations

# == Standard Library ========================
import json
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.env_config.env import EnvConfig
from apprc.definition.env_config.fields import config_owner_for
from apprc.definition.env_config.lookup import iter_config_fields

ResultT = TypeVar("ResultT")
BundleT = TypeVar("BundleT")


def setup_example_logging(level: str | int = "INFO", **_: object) -> None:
    """Configure stdlib logging for repository example CLIs.

    :param level: Logging level name or number supplied by AppRC's CLI hook.
    :param _: Extra logger-specific keyword arguments ignored by the example.
    :return: ``None``.
    """

    logging.basicConfig(level=level)


def build_standard_app(
    *,
    kit: AppConfigKit,
    bundle_cls: type[BundleT],
    section_getter: Callable[[BundleT], EnvConfig],
    help_text: str,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Build a normal Typer example app through ``mount_config_cli``.

    :param kit: AppRC contract mounted into the CLI.
    :param bundle_cls: Top-level ``@MyRC.bundle`` class to instantiate.
    :param section_getter: Callable that returns the section printed in the
        compact example output.
    :param help_text: Root command help text.
    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer app with AppRC host options and generated config commands.
    """
    app = typer.Typer(
        help=help_text,
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )

    rc.cli.mount_config_cli(
        app,
        kit,
        args_provider=args_provider,
        runtime_payload=lambda state: runtime_payload(
            kit=kit,
            bundle_cls=bundle_cls,
            section_getter=section_getter,
            state=state,
        ),
        editor_app_cls=editor_app_cls,
        setup_logging=setup_example_logging,
    )

    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Print the runtime config resolved for this CLI process."""
        state = require_default_state(ctx)
        typer.echo(
            json.dumps(
                runtime_payload(
                    kit=kit,
                    bundle_cls=bundle_cls,
                    section_getter=section_getter,
                    state=state,
                ),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    return app


def require_default_state(ctx: typer.Context) -> rc.cli.DefaultConfigCliState:
    """Return AppRC default state from a runtimeful example command.

    :param ctx: Active Typer command context.
    :return: Runtime state created by AppRC's standard callback.
    :raises RuntimeError: If a command that needs runtime state was skipped.
    """
    if isinstance(ctx.obj, rc.cli.DefaultConfigCliState):
        return ctx.obj
    raise RuntimeError("AppRC runtime state was not initialized.")


def runtime_payload(
    *,
    kit: AppConfigKit,
    bundle_cls: type[BundleT],
    section_getter: Callable[[BundleT], EnvConfig],
    state: rc.cli.DefaultConfigCliState,
) -> dict[str, object]:
    """Return JSON-friendly runtime state for example output.

    :param kit: AppRC contract whose metadata should be displayed.
    :param bundle_cls: Top-level ``@MyRC.bundle`` class to instantiate from
        ``os.environ``.
    :param section_getter: Callable that extracts the section printed in the
        compact example output.
    :param state: CLI state produced by AppRC bootstrap.
    :return: Payload with bootstrap paths and redacted config values.
    """
    bundle = bundle_cls()
    config = section_getter(bundle)
    return {
        "app_id": kit.spec.app_id,
        "command_name": kit.spec.config_command_name(),
        "display_name": kit.spec.display_name,
        "bundle": type(bundle).__name__,
        "bootstrap": bootstrap_payload(state.env_bootstrap),
        "config": config_values(config),
    }


def bootstrap_payload(
    bootstrap: rc.cli.EnvBootstrapResult | None,
) -> dict[str, object]:
    """Return JSON-friendly bootstrap metadata.

    :param bootstrap: Bootstrap result created by AppRC, if runtime bootstrap
        ran for the current command.
    :return: Payload suitable for CLI output and tests.
    """
    if bootstrap is None:
        return {
            "defaults_dotenv": None,
            "user_dotenv": None,
            "storage_dotenv": None,
            "env_files": [],
            "apprc_toml": None,
            "storage_selector_source": None,
            "storage_selector_value": None,
            "storage_name": None,
            "storage_root": None,
            "storage_count": 0,
        }
    return {
        "defaults_dotenv": _path_text(bootstrap.defaults_dotenv),
        "user_dotenv": _path_text(bootstrap.user_dotenv),
        "storage_dotenv": _path_text(bootstrap.storage_dotenv),
        "env_files": [str(path) for path in bootstrap.env_files],
        "apprc_toml": _path_text(bootstrap.apprc_toml),
        "storage_selector_source": bootstrap.storage_selector_source,
        "storage_selector_value": bootstrap.storage_selector_value,
        "storage_name": bootstrap.storage_name,
        "storage_root": _path_text(bootstrap.storage_root),
        "storage_count": bootstrap.storage_count,
    }


def config_values(config: EnvConfig) -> dict[str, object]:
    """Return public config values with secrets redacted.

    :param config: Bound runtime config object.
    :return: JSON-friendly values keyed by Python field name.
    """
    owner = config_owner_for(type(config))
    specs = {spec.name: spec for _owner, spec in iter_config_fields((owner,))}
    values: dict[str, object] = {}
    for field in rc.provenance.public_config_fields(config):
        spec = specs[field.name]
        value = getattr(config, field.name)
        if spec.secret:
            values[field.name] = "<redacted>" if value else None
        elif isinstance(value, Path):
            values[field.name] = str(value)
        else:
            values[field.name] = value
    return values


@contextmanager
def isolated_apprc_environment(
    root: Path,
    *,
    env_prefixes: tuple[str, ...],
) -> Iterator[None]:
    """Run one demo without retaining environment changes.

    :param root: Temporary directory allocated for one demo run.
    :param env_prefixes: Env prefixes owned by the example.
    :return: Context manager that restores ``os.environ`` afterward.
    """
    original_env = dict(os.environ)
    try:
        for key in tuple(os.environ):
            if key.startswith(env_prefixes):
                del os.environ[key]
        yield
    finally:
        os.environ.clear()
        os.environ.update(original_env)


def run_isolated(
    root: Path,
    *,
    env_prefixes: tuple[str, ...],
    scenario: Callable[[], ResultT],
) -> ResultT:
    """Execute a scenario with isolated AppRC-owned paths.

    :param root: Temporary directory allocated for the scenario.
    :param env_prefixes: Env prefixes owned by the example.
    :param scenario: Callable that exercises one example app.
    :return: Scenario result.
    """
    with isolated_apprc_environment(root, env_prefixes=env_prefixes):
        return scenario()


def write_env(path: Path, values: Mapping[str, str]) -> Path:
    """Write deterministic dotenv values for a demo scenario.

    :param path: Dotenv path to create or replace.
    :param values: Env key/value pairs.
    :return: Written dotenv path.
    """
    return rc.files.write_env_file(path, dict(values), owners=())


def _path_text(path: Path | None) -> str | None:
    """Return path text while preserving missing values."""
    return str(path) if path is not None else None
