"""Dotenv layer parsing and precedence helpers for bootstrap."""

from __future__ import annotations

# == Standard Library ========================
import warnings
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
    DEFAULT_DEFAULTS_ENV_FILENAME,
    LEGACY_DEFAULTS_ENV_FILENAME,
    AppConfigSpec,
)
from apprc.user_files.app_home.locations import ConfigHomeError


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


@dataclass(frozen=True, slots=True)
class StorageSelectorFallbackValues:
    """Dotenv values used after process env storage selectors.

    :param app_values: Values from the per-user app dotenv file.
    :param defaults_values: Values from the packaged defaults dotenv file.
    :param issues: Non-fatal read problems suitable for diagnostics.
    """

    app_values: dict[str, str]
    defaults_values: dict[str, str]
    issues: list[str]


def defaults_env_resource(spec: AppConfigSpec) -> Traversable:
    """Return the selected packaged defaults dotenv resource."""
    package_files = files(spec.config_package)
    preferred = package_files.joinpath(spec.defaults_env_filename)
    if (
        spec.uses_legacy_constructor()
        or spec.defaults_env_filename != DEFAULT_DEFAULTS_ENV_FILENAME
    ):
        return preferred
    legacy = package_files.joinpath(LEGACY_DEFAULTS_ENV_FILENAME)
    if preferred.is_file():
        if legacy.is_file():
            warnings.warn(
                "Both apprc.defaults.env and .env.shared exist in "
                f"{spec.config_package}. AppRC uses apprc.defaults.env and "
                "ignores .env.shared.",
                RuntimeWarning,
                stacklevel=2,
            )
        return preferred
    return legacy if legacy.is_file() else preferred


def shared_env_resource(spec: AppConfigSpec) -> Traversable:
    """Return packaged defaults through the deprecated 0.19 name."""
    return defaults_env_resource(spec)


def read_defaults_env_values(
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
    with as_file(defaults_env_resource(spec)) as defaults_env:
        if not defaults_env.is_file():
            return None, {}
        return defaults_env, read_dotenv_file(defaults_env)


def read_shared_env_values(
    spec: AppConfigSpec,
) -> tuple[Path | None, dict[str, str]]:
    """Read packaged defaults through the deprecated 0.19 name."""
    return read_defaults_env_values(spec)


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


def read_storage_selector_fallback_values(
    spec: AppConfigSpec,
    *,
    collect_app_issues: bool = False,
) -> StorageSelectorFallbackValues:
    """Read persistent dotenv values used for storage selection.

    Skipped-bootstrap config commands and doctor must resolve persistent
    storage selectors with the same file-reading rules. Selector precedence
    stays in :mod:`apprc.user_files.storage_roots.selector`.

    :param spec: Application-specific config contract.
    :param collect_app_issues: Whether per-user app dotenv read errors should
        be returned as diagnostic issues instead of raised.
    :return: Parsed fallback values and any diagnostic issues.
    """
    app_values = {}
    issues: list[str] = []
    app_env_path = spec.app_env_path()
    if spec.app_env_enabled() and app_env_path.is_file():
        try:
            app_values = read_dotenv_file(app_env_path)
        except OSError as exc:
            issue = (
                f"AppRC-managed file could not be read: {app_env_path}: {exc}"
            )
            if collect_app_issues:
                issues.append(issue)
            else:
                raise ConfigHomeError(issue) from exc
    try:
        _, defaults_values = read_defaults_env_values(spec)
    except (ImportError, OSError, TypeError) as exc:
        defaults_values = {}
        issues.append(
            "Packaged defaults env could not be read for "
            f"{spec.config_package!r}: {exc}"
        )
    return StorageSelectorFallbackValues(
        app_values=app_values,
        defaults_values=defaults_values,
        issues=issues,
    )


def merged_env_values(
    *,
    defaults_values: Mapping[str, str],
    app_values: Mapping[str, str],
    storage_values: Mapping[str, str],
    explicit_values: Mapping[str, str],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_os_environ:
        return {
            **defaults_values,
            **app_values,
            **storage_values,
            **original_env,
            **explicit_values,
        }
    return {
        **defaults_values,
        **app_values,
        **storage_values,
        **explicit_values,
        **original_env,
    }
