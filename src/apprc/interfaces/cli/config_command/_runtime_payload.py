"""Runtime payload helpers for generated config commands."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Any

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit


def default_runtime_payload(
    kit: AppConfigKit,
    *,
    storage_root: Path | None,
) -> dict[str, Any]:
    """Return generic ``config show`` data when the app provides none.

    :param kit: Application config facade.
    :param storage_root: Active storage root, if one is selected.
    :return: JSON-friendly runtime payload.
    """
    storage_env = (
        str(kit.spec.storage_env_path(storage_root))
        if storage_root is not None
        else None
    )
    return {
        "app_name": kit.spec.app_name,
        "display_name": kit.spec.display_name,
        "storage_enabled": kit.spec.uses_storage(),
        "app_config_enabled": kit.spec.app_env_enabled(),
        "named_storage_enabled": kit.spec.named_storage_enabled(),
        "config_home": str(kit.spec.config_home()),
        "app_env": str(kit.spec.app_env_path()),
        "apprc_toml": str(kit.spec.apprc_toml_path()),
        "storage_root": str(storage_root) if storage_root else None,
        "storage_env": storage_env,
    }
