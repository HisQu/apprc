"""Runtime payload helpers for generated config commands."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Any

# == Internal ================================
from apprc.public.app_rc import AppRC
from apprc.runtime.resolution import ResolvedConfig
from apprc.user_files.app_home.application import AppFiles


def default_runtime_payload(
    apprc: AppRC,
    *,
    workspace_root: Path | None,
    resolved: ResolvedConfig,
) -> dict[str, Any]:
    """Return generic ``config show`` data when the app provides none.

    :param apprc: Application config facade.
    :param workspace_root: Active workspace root, if one is selected.
    :return: JSON-friendly runtime payload.
    """
    paths = resolved.paths
    files = AppFiles(apprc.schema, paths)
    workspace_dotenv = (
        str(files.workspace_dotenv_path(workspace_root))
        if workspace_root is not None
        else None
    )
    config_dir = paths.config_dir
    config_file = str(files.config_file()) if config_dir is not None else None
    return {
        "app_id": apprc.schema.app_id,
        "display_name": apprc.schema.display_name,
        "config_enabled": apprc.schema.paths.config,
        "config_dir": str(config_dir) if config_dir is not None else None,
        "layout": paths.layout.mode,
        "layout_source": paths.source,
        "user_dotenv_enabled": apprc.schema.uses_user_dotenv(),
        "user_dotenv": (
            str(files.user_dotenv_path())
            if apprc.schema.uses_user_dotenv()
            else None
        ),
        "config_file": config_file,
        "workspace_enabled": apprc.schema.uses_workspaces(),
        "workspace_selector_env_key": (apprc.schema.workspace_selector_env_key),
        "workspace": (
            resolved.workspace.workspace_name
            if resolved.workspace is not None
            else None
        ),
        "workspace_root": str(workspace_root) if workspace_root else None,
        "workspace_dotenv": workspace_dotenv,
    }
