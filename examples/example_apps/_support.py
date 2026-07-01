"""Shared helpers for executable AppRC examples."""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

# == Internal ================================
import apprc

ResultT = TypeVar("ResultT")


@contextmanager
def isolated_apprc_environment(
    root: Path,
    *,
    env_prefixes: tuple[str, ...],
) -> Iterator[None]:
    """Run one example without reading or mutating the user's config home.

    :param root: Temporary directory allocated for one example run.
    :param env_prefixes: Env prefixes owned by the example.
    :return: Context manager that restores ``os.environ`` afterward.
    """
    original_env = dict(os.environ)
    try:
        for key in tuple(os.environ):
            if key.startswith(env_prefixes):
                del os.environ[key]
        os.environ["XDG_CONFIG_HOME"] = str(root / "config-home")
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
    """Execute one scenario with an isolated AppRC config home.

    :param root: Temporary directory allocated for the scenario.
    :param env_prefixes: Env prefixes owned by the example.
    :param scenario: Callable that exercises one example app.
    :return: Scenario result.
    """
    with isolated_apprc_environment(root, env_prefixes=env_prefixes):
        return scenario()


def config_values(config: apprc.EnvConfig) -> dict[str, Any]:
    """Return public config values for compact JSON example output.

    :param config: Bound AppRC config object.
    :return: JSON-friendly field values.
    """
    values: dict[str, Any] = {}
    for field in apprc.public_config_fields(config):
        value = getattr(config, field.name)
        values[field.name] = str(value) if isinstance(value, Path) else value
    return values


def write_env(path: Path, values: Mapping[str, str]) -> Path:
    """Write deterministic dotenv values for an example scenario.

    :param path: Dotenv path to create or replace.
    :param values: Env key/value pairs.
    :return: Written dotenv path.
    """
    return apprc.write_env_file(path, dict(values), owners=())
