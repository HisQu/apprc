"""Validation and derivation helpers for application config specs."""

from __future__ import annotations

# == Standard Library ========================
import re


def _environment_key_prefix(app_id: str) -> str:
    """Return the normalized environment-key prefix for an application.

    :param app_id: Stable application identity.
    :return: Uppercase identifier suitable for an environment key.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_id).strip("_").upper()
    return normalized or "APP"


def derive_apprc_dir_env_key(app_id: str) -> str:
    """Return the environment key that relocates the AppRC directory.

    :param app_id: Stable application identity.
    :return: Uppercase ``<APP>_APPRC_DIR`` key.
    """
    return f"{_environment_key_prefix(app_id)}_APPRC_DIR"


def derive_legacy_apprc_toml_env_key(app_id: str) -> str:
    """Return the released 0.19 AppRC TOML relocation key.

    :param app_id: Legacy application identity.
    :return: Uppercase ``<APP>_APPRC_TOML`` key.
    """
    return f"{_environment_key_prefix(app_id)}_APPRC_TOML"


def derive_storage_selector_env_key(app_id: str) -> str:
    """Return the environment variable that selects active storage.

    :param app_id: Application name from the AppRC integration spec.
    :return: Uppercase env key for the active storage selector.
    """
    return f"{_environment_key_prefix(app_id)}_STORAGE"


def resolve_storage_selector_env_key(
    *,
    app_id: str,
    selector_env_key: str | None,
) -> str:
    """Return the explicit or derived active-storage selector key.

    :param app_id: Application name used for the conventional key.
    :param selector_env_key: Optional caller-supplied key.
    :return: Explicit key or the derived ``<APP>_STORAGE`` key.
    """
    return selector_env_key or derive_storage_selector_env_key(app_id)
