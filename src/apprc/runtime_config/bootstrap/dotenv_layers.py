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
from apprc.runtime_config.config_home import ConfigHomeError


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

    :param app_wide_values: Values from the app-wide dotenv file.
    :param shared_values: Values from the packaged shared dotenv file.
    :param issues: Non-fatal read problems suitable for diagnostics.
    """

    app_wide_values: dict[str, str]
    shared_values: dict[str, str]
    issues: list[str]


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
    collect_app_wide_issues: bool = False,
) -> StorageSelectorFallbackValues:
    """Read persistent dotenv values used for storage selection.

    Skipped-bootstrap config commands and doctor must resolve persistent
    storage selectors with the same file-reading rules. Selector precedence
    stays in :mod:`apprc.runtime_config.storage.selector`.

    :param spec: Application-specific config contract.
    :param collect_app_wide_issues: Whether app-wide dotenv read errors should
        be returned as diagnostic issues instead of raised.
    :return: Parsed fallback values and any diagnostic issues.
    """
    app_wide_values = {}
    issues: list[str] = []
    app_wide_env_path = spec.app_wide_env_path()
    if spec.app_wide_allowed() and app_wide_env_path.is_file():
        try:
            app_wide_values = read_dotenv_file(app_wide_env_path)
        except OSError as exc:
            issue = (
                "AppRC-managed file could not be read: "
                f"{app_wide_env_path}: {exc}"
            )
            if collect_app_wide_issues:
                issues.append(issue)
            else:
                raise ConfigHomeError(issue) from exc
    try:
        _, shared_values = read_shared_env_values(spec)
    except (ImportError, OSError, TypeError) as exc:
        shared_values = {}
        issues.append(
            "Packaged shared env could not be read for "
            f"{spec.config_package!r}: {exc}"
        )
    return StorageSelectorFallbackValues(
        app_wide_values=app_wide_values,
        shared_values=shared_values,
        issues=issues,
    )


def merged_env_values(
    *,
    shared_values: Mapping[str, str],
    app_wide_values: Mapping[str, str],
    storage_values: Mapping[str, str],
    explicit_values: Mapping[str, str],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_os_environ:
        return {
            **shared_values,
            **app_wide_values,
            **storage_values,
            **original_env,
            **explicit_values,
        }
    return {
        **shared_values,
        **app_wide_values,
        **storage_values,
        **explicit_values,
        **original_env,
    }
