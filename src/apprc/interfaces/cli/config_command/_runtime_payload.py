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
    storage_dotenv = (
        str(kit.spec.storage_dotenv_path(storage_root))
        if storage_root is not None
        else None
    )
    return {
        "app_id": kit.spec.app_id,
        "display_name": kit.spec.display_name,
        "storage_enabled": kit.spec.uses_storage(),
        "apprc_dir": str(kit.spec.apprc_dir()),
        "apprc_dir_env_key": kit.spec.apprc_dir_env_key,
        "user_dotenv": str(kit.spec.user_dotenv_path()),
        "apprc_toml": str(kit.spec.preferred_apprc_toml_path()),
        "storage_root": str(storage_root) if storage_root else None,
        "storage_dotenv": storage_dotenv,
    }
