"""Read-only checks for workspace directories selected for runtime use."""

from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.workspace_roots.selector import (
    WorkspaceNotInitializedError,
)


def validate_runtime_workspace_root(
    *,
    spec: AppConfigSpec,
    app_paths: AppPaths,
    workspace_root: Path,
    workspace_name: str | None,
    param_hint: str,
) -> None:
    """Reject a selected workspace root that is not ready for runtime use.

    Runtime resolution reads configuration but never creates workspace
    directories or dotenv files.

    :param spec: Application contract used to identify the application.
    :param app_paths: Captured resolved application paths.
    :param workspace_root: Resolved path selected for this process.
    :param workspace_name: Associated registry name, when known.
    :param param_hint: Selector source shown by CLI error rendering.
    :raises WorkspaceSelectorError: If the root or marker is unusable.
    """
    missing_root_guidance = (
        "Use WorkspaceManager.repoint_workspace(name, existing_root) to "
        "attach an existing initialized directory."
        if workspace_name is not None
        else "Initialize this direct path with "
        "WorkspaceManager.initialize_workspace(workspace_root)."
    )
    if not workspace_root.exists():
        raise WorkspaceNotInitializedError(
            f"Selected {spec.display_name} workspace root does not exist: "
            f"{workspace_root}. {missing_root_guidance}",
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            param_hint=param_hint,
        )
    if not workspace_root.is_dir():
        raise WorkspaceNotInitializedError(
            f"Selected {spec.display_name} workspace root is not a directory: "
            f"{workspace_root}. {missing_root_guidance}",
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            param_hint=param_hint,
        )
    workspace_dotenv = AppFiles(spec, app_paths).workspace_dotenv_path(
        workspace_root
    )
    if not workspace_dotenv.is_file():
        raise WorkspaceNotInitializedError(
            f"Selected {spec.display_name} workspace is missing its AppRC "
            f"marker: {workspace_dotenv}. {missing_root_guidance}",
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            param_hint=param_hint,
        )
    try:
        with workspace_dotenv.open("r", encoding="utf-8"):
            pass
    except OSError as exc:
        raise WorkspaceNotInitializedError(
            f"Selected {spec.display_name} workspace dotenv is not readable: "
            f"{workspace_dotenv}: {exc}",
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            param_hint=param_hint,
        ) from exc
