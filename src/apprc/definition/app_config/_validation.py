"""Validation and derivation helpers for application config specs."""

from __future__ import annotations

# == Standard Library ========================
import re


def derive_apprc_toml_env_key(app_name: str) -> str:
    """Return the environment variable that relocates the AppRC TOML file.

    :param app_name: Application name from the AppRC integration spec.
    :return: Uppercase env key for the AppRC TOML override.
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


def resolve_storage_selector_env_key(
    *,
    app_name: str,
    env_key: str | None,
) -> str:
    """Return the explicit or derived active-storage selector key.

    :param app_name: Application name used for the conventional key.
    :param env_key: Optional caller-supplied key.
    :return: Explicit key or the derived ``<APP>_STORAGE`` key.
    """
    return env_key or derive_storage_env_key(app_name)
