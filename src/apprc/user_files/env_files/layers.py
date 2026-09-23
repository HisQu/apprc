"""Dotenv layer parsing for explicit source resolution."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Mapping

# == 3rd Party ===============================
from apprc.user_files.env_files._parsing import parse_dotenv_file

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


def defaults_dotenv_resource(spec: AppConfigSpec) -> Traversable | None:
    """Return the selected packaged defaults dotenv resource."""
    if spec.config_package is None:
        return None
    return files(spec.config_package).joinpath(spec.defaults_dotenv_filename)


def read_explicit_env_files(
    env_files: Sequence[Path],
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[tuple[Path, ...], tuple[ExplicitEnvLayer, ...], dict[str, str]]:
    """Read ordered explicit dotenv files.

    Explicit values may guide storage selection even when dotenv layers
    are not included in setting values. Later files override earlier files.
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
            values = parse_dotenv_file(resolved, environment=environment)
        except OSError as exc:
            raise ExplicitEnvFileError(
                f"Explicit env file could not be read: {resolved}: {exc}"
            ) from exc
        layers.append(ExplicitEnvLayer(path=resolved, values=values))
        merged_values.update(values)
    return tuple(loaded_paths), tuple(layers), merged_values


def read_dotenv_file(path: Path | None) -> dict[str, str]:
    """Read one dotenv file, ignoring missing optional files."""
    return parse_dotenv_file(path)
