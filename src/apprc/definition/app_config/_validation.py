"""Validation and derivation helpers for application config specs."""

from __future__ import annotations

# == Standard Library ========================
import re

# == Internal ================================
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)


def derive_index_env_key(app_name: str) -> str:
    """Return the environment variable that relocates the storage index.

    :param app_name: Application name from the AppRC integration spec.
    :return: Uppercase env key for the named-storage index override.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_APPRC_TOML"


def derive_storage_env_key(app_name: str) -> str:
    """Return the environment variable that selects active storage.

    :param app_name: Application name from the AppRC integration spec.
    :return: Uppercase env key for the active storage selector.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_STORAGE"


def validate_capability_combination(
    *,
    storage_layer: StorageLayerState,
    named_storage_layer: CapabilityState,
    storage_env_key: str | None,
) -> None:
    """Raise when a spec declares a capability combination AppRC cannot use.

    :param storage_layer: Storage root requirement for this integration.
    :param named_storage_layer: Named-storage index policy.
    :param storage_env_key: Explicit storage selector env key.
    :raises ValueError: If storage-only inputs are used without storage.
    """
    if storage_layer == StorageLayerState.DISABLED:
        if storage_env_key is not None:
            raise ValueError(
                "storage_env_key requires a storage-capable constructor."
            )
        if named_storage_layer != CapabilityState.DISABLED:
            raise ValueError(
                "named_storage_layer requires a storage-capable constructor."
            )


def resolve_storage_env_key(
    *,
    app_name: str,
    storage_env_key: str | None,
    storage_layer: StorageLayerState,
) -> str | None:
    """Return the selector env key allowed by the selected storage layer.

    :param app_name: Application name from the AppRC integration spec.
    :param storage_env_key: Optional caller-supplied selector env key.
    :param storage_layer: Storage root requirement for this integration.
    :return: Explicit, derived, or absent storage selector env key.
    """
    if storage_layer == StorageLayerState.DISABLED:
        return None
    return storage_env_key or derive_storage_env_key(app_name)
