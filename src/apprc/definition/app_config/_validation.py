"""Validation and derivation helpers for application declarations."""

from __future__ import annotations

import re


def environment_key_prefix(app_id: str) -> str:
    """Return the normalized bootstrap prefix for an application.

    :param app_id: Stable application identity.
    :return: Uppercase identifier suitable for environment keys.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", app_id).strip("_").upper()


def derive_workspace_selector_env_key(app_id: str) -> str:
    """Return the default workspace selector key.

    :param app_id: Application identity or explicit bootstrap prefix.
    :return: The conventional workspace environment key.
    """
    return f"{environment_key_prefix(app_id)}_WORKSPACE"


def resolve_workspace_selector_env_key(
    *, app_id: str, selector_env_key: str | None
) -> str:
    """Return an explicit selector or its application-derived default.

    :param app_id: Identity used to derive the default prefix.
    :param selector_env_key: Explicit selection key, when declared.
    :return: Workspace selection environment key.
    """
    return selector_env_key or derive_workspace_selector_env_key(app_id)
