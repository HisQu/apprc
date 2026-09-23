"""Runtime payload helpers for generated config commands."""

from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

# == Standard Library ========================
from pathlib import Path
from typing import Any

# == Internal ================================
from apprc.public.app_rc import AppRC
from apprc.runtime.resolution import ResolvedConfig


def default_runtime_payload(
    apprc: AppRC,
    *,
    storage_root: Path | None,
    resolved: ResolvedConfig,
) -> dict[str, Any]:
    """Return generic ``config show`` data when the app provides none.

    :param apprc: Application config facade.
    :param storage_root: Active storage root, if one is selected.
    :return: JSON-friendly runtime payload.
    """
    paths = resolved.paths
    storage_dotenv = (
        str(AppFiles(apprc.schema).storage_dotenv_path(storage_root))
        if storage_root is not None
        else None
    )
    apprc_dir = str(paths.root) if paths is not None else None
    return {
        "app_id": apprc.schema.app_id,
        "display_name": apprc.schema.display_name,
        "user_dotenv_enabled": apprc.schema.uses_user_dotenv(),
        "storage_enabled": apprc.schema.uses_storage(),
        "apprc_dir": apprc_dir,
        "apprc_dir_env_key": (
            apprc.schema.apprc_dir_env_key
            if apprc.schema.uses_managed_files()
            else None
        ),
        "user_dotenv": (
            str(paths.user_dotenv)
            if paths is not None and apprc.schema.uses_user_dotenv()
            else None
        ),
        "apprc_toml": (
            str(paths.apprc_toml)
            if paths is not None and apprc.schema.uses_storage()
            else None
        ),
        "storage_root": str(storage_root) if storage_root else None,
        "storage_dotenv": storage_dotenv,
    }
