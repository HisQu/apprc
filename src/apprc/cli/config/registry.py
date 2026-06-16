"""Registry helpers for generated config commands."""

from __future__ import annotations

from pathlib import Path

import typer

from apprc.cli.config.state import active_storage_root_from_env
from apprc.config.kit import AppConfigKit
from apprc.config.registry_env import RegistryEnvError
from apprc.config.registry_loading import (
    load_existing_registry,
    load_optional_runtime_registry,
)
from apprc.config.storage.registry import StorageRegistry
from apprc.config.storage.selector import StorageSelectorError


def load_required_registry_for_cli(kit: AppConfigKit) -> StorageRegistry:
    """Return the registry required by registry-only CLI commands.

    :param kit: Application config facade.
    :return: Parsed existing registry.
    :raises typer.BadParameter: If registry loading fails.
    """
    try:
        return load_existing_registry(kit.spec)
    except (RegistryEnvError, ValueError) as exc:
        raise registry_bad_parameter(kit, exc) from exc


def load_optional_registry_for_cli(
    kit: AppConfigKit,
) -> StorageRegistry | None:
    """Return the registry only when multi-storage mode is enabled.

    :param kit: Application config facade.
    :return: Parsed registry, or ``None`` for single-storage mode.
    :raises typer.BadParameter: If a configured registry cannot be loaded.
    """
    try:
        return load_optional_runtime_registry(kit.spec)
    except (RegistryEnvError, ValueError) as exc:
        raise registry_bad_parameter(kit, exc) from exc


def registry_bad_parameter(
    kit: AppConfigKit,
    exc: RegistryEnvError | ValueError,
) -> typer.BadParameter:
    """Return Typer's error type for registry loading failures.

    :param kit: Application config facade.
    :param exc: Registry env or parse error.
    :return: Typer parameter error with a focused hint.
    """
    param_hint = (
        kit.spec.apprc_toml_env_key
        if isinstance(exc, RegistryEnvError)
        else kit.spec.apprc_toml_filename
    )
    return typer.BadParameter(str(exc), param_hint=param_hint)


def best_effort_active_storage_root_from_env(
    kit: AppConfigKit,
    *,
    registry: StorageRegistry | None,
) -> Path | None:
    """Return the env-selected storage root, suppressing selector errors.

    :param kit: Application config facade.
    :param registry: Parsed registry, or ``None`` for single-storage mode.
    :return: Resolved active storage root, or ``None`` when unavailable.
    """
    try:
        return active_storage_root_from_env(
            kit,
            registry=registry,
        )
    except StorageSelectorError:
        return None
