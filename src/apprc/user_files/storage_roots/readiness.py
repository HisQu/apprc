"""Read-only checks for a storage directory selected for runtime use."""

from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.storage_roots.selector import StorageNotInitializedError


def validate_runtime_storage_root(
    *,
    spec: AppConfigSpec,
    storage_root: Path,
    storage_name: str | None,
    param_hint: str,
) -> None:
    """Reject a selected root that AppRC setup has not prepared.

    Runtime resolution reads configuration but never creates directories. The
    generated config commands own recovery so applications get one consistent
    path before they construct storage-backed runtime objects.

    :param spec: Application contract used to build recovery instructions.
    :param storage_root: Resolved path selected for this process.
    :param storage_name: Associated registry name, when known.
    :param param_hint: Selector source shown by CLI error rendering.
    :return: None.
    :raises StorageSelectorError: If the path or AppRC marker is unusable.
    """
    setup_command = (
        f"{spec.config_command_name()} config setup --yes "
        f"--storage-root {storage_root}"
    )
    reconnect_command = (
        f"{spec.config_command_name()} config storage repoint {storage_name} "
        "/absolute/path/to/existing-storage"
        if storage_name is not None
        else setup_command
    )
    missing_root_guidance = (
        f"Run `{reconnect_command}` after locating the existing storage. "
        "Setup will not recreate a missing registered root."
        if storage_name is not None
        else f"Run `{setup_command}` to initialize this path."
    )
    if not storage_root.exists():
        raise StorageNotInitializedError(
            f"Selected {spec.display_name} storage root does not exist: "
            f"{storage_root}. {missing_root_guidance}",
            storage_root=storage_root,
            storage_name=storage_name,
            param_hint=param_hint,
        )
    if not storage_root.is_dir():
        raise StorageNotInitializedError(
            f"Selected {spec.display_name} storage root is not a directory: "
            f"{storage_root}. Run `{reconnect_command}` after locating the "
            "existing storage.",
            storage_root=storage_root,
            storage_name=storage_name,
            param_hint=param_hint,
        )
    storage_dotenv = AppFiles(spec).storage_dotenv_path(storage_root)
    if not storage_dotenv.is_file():
        raise StorageNotInitializedError(
            f"Selected {spec.display_name} storage directory is not "
            f"initialized by AppRC: missing {storage_dotenv}. Run "
            f"`{setup_command}` before runtime use.",
            storage_root=storage_root,
            storage_name=storage_name,
            param_hint=param_hint,
        )
    try:
        with storage_dotenv.open("r", encoding="utf-8"):
            pass
    except OSError as exc:
        raise StorageNotInitializedError(
            f"Selected {spec.display_name} storage dotenv is not readable: "
            f"{storage_dotenv}: {exc}",
            storage_root=storage_root,
            storage_name=storage_name,
            param_hint=param_hint,
        ) from exc
