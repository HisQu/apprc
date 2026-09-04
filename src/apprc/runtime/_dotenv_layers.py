"""Dotenv layer parsing and precedence helpers for bootstrap."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Mapping

# == 3rd Party ===============================
from dotenv import dotenv_values

# == Internal ================================
from apprc.definition.app_config.spec import (
    AppConfigSpec,
)


class ExplicitEnvFileError(ValueError):
    """Raised when an explicit ``--env-file`` cannot be read.

    :param message: Human-readable read failure.
    """


@dataclass(frozen=True, slots=True)
class ExplicitEnvLayer:
    """Parsed explicit env file plus its path for provenance tracking.

    :param path: Resolved explicit env file path.
    :param values: Parsed dotenv values from ``path``.
    """

    path: Path
    values: dict[str, str]


def defaults_dotenv_resource(spec: AppConfigSpec) -> Traversable:
    """Return the selected packaged defaults dotenv resource."""
    return files(spec.config_package).joinpath(spec.defaults_dotenv_filename)


def read_defaults_dotenv_values(
    spec: AppConfigSpec,
) -> tuple[Path | None, dict[str, str]]:
    """Read packaged defaults dotenv values when the resource exists.

    Missing resources are tolerated here so storage selection can use a
    packaged default when present without making defaults mandatory for every
    AppRC integration. ``bootstrap_env`` raises later when dotenv layers are
    enabled and the resource is absent.

    :param spec: Application-specific bootstrap contract.
    :return: Defaults dotenv path and parsed values, or ``(None, {})``.
    """
    with as_file(defaults_dotenv_resource(spec)) as defaults_dotenv:
        if not defaults_dotenv.is_file():
            return None, {}
        return defaults_dotenv, read_dotenv_file(defaults_dotenv)


def read_explicit_env_files(
    env_files: Sequence[Path],
) -> tuple[tuple[Path, ...], tuple[ExplicitEnvLayer, ...], dict[str, str]]:
    """Read ordered explicit dotenv files.

    Explicit values may guide storage selection even when dotenv layers
    are not merged into ``os.environ``. Later files override earlier files.
    """
    loaded_paths: list[Path] = []
    layers: list[ExplicitEnvLayer] = []
    merged_values: dict[str, str] = {}
    for env_file in env_files:
        resolved = Path(env_file).expanduser()
        if not resolved.is_file():
            raise FileNotFoundError(
                f"Explicit env file does not exist: {resolved}"
            )
        loaded_paths.append(resolved)
        try:
            values = read_dotenv_file(resolved)
        except OSError as exc:
            raise ExplicitEnvFileError(
                f"Explicit env file could not be read: {resolved}: {exc}"
            ) from exc
        layers.append(ExplicitEnvLayer(path=resolved, values=values))
        merged_values.update(values)
    return tuple(loaded_paths), tuple(layers), merged_values


def read_dotenv_file(path: Path | None) -> dict[str, str]:
    """Read one dotenv file, ignoring missing optional files."""
    if path is None or not path.is_file():
        return {}
    raw_values = dotenv_values(path)
    return {
        key: value
        for key, value in raw_values.items()
        if isinstance(value, str)
    }


def merged_env_values(
    *,
    defaults_values: Mapping[str, str],
    user_dotenv_values: Mapping[str, str],
    storage_values: Mapping[str, str],
    explicit_values: Mapping[str, str],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_os_environ:
        return {
            **defaults_values,
            **user_dotenv_values,
            **storage_values,
            **original_env,
            **explicit_values,
        }
    return {
        **defaults_values,
        **user_dotenv_values,
        **storage_values,
        **explicit_values,
        **original_env,
    }
