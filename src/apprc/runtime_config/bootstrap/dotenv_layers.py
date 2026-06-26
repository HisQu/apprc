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
from apprc.runtime_config.app_spec import AppConfigSpec


@dataclass(frozen=True, slots=True)
class ExplicitEnvLayer:
    """Parsed explicit env file plus its path for provenance tracking.

    :param path: Resolved explicit env file path.
    :param values: Parsed dotenv values from ``path``.
    """

    path: Path
    values: dict[str, str]


def shared_env_resource(spec: AppConfigSpec) -> Traversable:
    """Return the packaged shared dotenv resource."""
    return files(spec.config_package).joinpath(spec.shared_env_filename)


def read_shared_env_values(
    spec: AppConfigSpec,
) -> tuple[Path | None, dict[str, str]]:
    """Read packaged shared dotenv values when the resource exists.

    Missing shared resources are tolerated here so storage selection can use a
    packaged default when present without making shared defaults mandatory for
    every AppRC integration. ``bootstrap_env`` raises later when dotenv layers
    are enabled and the shared resource is absent.

    :param spec: Application-specific bootstrap contract.
    :return: Shared dotenv path and parsed values, or ``(None, {})``.
    """
    with as_file(shared_env_resource(spec)) as shared_env:
        if not shared_env.is_file():
            return None, {}
        return shared_env, read_dotenv_file(shared_env)


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
        values = read_dotenv_file(resolved)
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
    shared_values: Mapping[str, str],
    global_values: Mapping[str, str],
    local_values: Mapping[str, str],
    explicit_values: Mapping[str, str],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_os_environ:
        return {
            **shared_values,
            **global_values,
            **local_values,
            **original_env,
            **explicit_values,
        }
    return {
        **shared_values,
        **global_values,
        **local_values,
        **explicit_values,
        **original_env,
    }
