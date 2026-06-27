"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console

# == Internal ================================
from apprc.cli.errors import config_home_bad_parameter
from apprc.runtime_config.config_home import ConfigHomeError
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.storage.local_env import ensure_local_env_file
from apprc.runtime_config.storage.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.runtime_config.terminal_styles import (
    ENV_KEY_STYLE,
    PATH_STYLE,
    style_literals,
)


def run_config_setup(
    kit: AppConfigKit,
    *,
    assume_yes: bool = False,
    storage_root: Path | None = None,
) -> None:
    """Configure files for the declared AppRC capability layers.

    :param kit: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to run without prompts.
    :param storage_root: Optional active storage root.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If setup inputs are invalid.
    """
    if not kit.spec.storage_required():
        if storage_root is not None:
            raise typer.BadParameter(
                f"{kit.spec.display_name} does not use AppRC storage.",
                param_hint="--storage-root",
            )
        if kit.spec.app_wide_default():
            try:
                app_wide_path = kit.spec.ensure_app_wide_env()
            except ConfigHomeError as exc:
                raise config_home_bad_parameter(exc) from exc
            _print_app_wide_setup(kit, app_wide_path=app_wide_path)
            return
        _print_env_only_setup(kit)
        return

    root = _prepare_storage_root(
        kit,
        storage_root=storage_root,
        assume_yes=assume_yes,
    )
    try:
        storage_env = ensure_local_env_file(
            root,
            filename=kit.spec.storage_env_filename,
        )
        app_wide_path = (
            kit.spec.ensure_app_wide_env()
            if kit.spec.app_wide_default()
            else None
        )
    except (ConfigHomeError, StorageRootPathError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage-root") from exc
    _print_storage_setup(
        kit,
        storage_root=root,
        storage_env=storage_env,
        app_wide_path=app_wide_path,
    )


def _prepare_storage_root(
    kit: AppConfigKit,
    *,
    storage_root: Path | None,
    assume_yes: bool,
) -> Path:
    """Return the storage root selected for setup, creating directories.

    :param kit: Application config facade.
    :param storage_root: Optional CLI-provided root.
    :param assume_yes: Whether setup may run without prompts.
    :return: Existing storage root directory.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If the path cannot be used as a directory.
    """
    selected = storage_root
    if selected is None and assume_yes:
        raise typer.BadParameter(
            "--storage-root is required with --yes for storage setup.",
            param_hint="--storage-root",
        )
    if selected is None:
        raw_value = typer.prompt("Storage root")
        selected = Path(raw_value)
    try:
        root = normalize_storage_root_path(selected)
    except StorageRootPathError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="--storage-root",
        ) from exc
    if root.exists() and not root.is_dir():
        raise typer.BadParameter(
            f"Storage root exists but is not a directory: {root}",
            param_hint="--storage-root",
        )
    if root.exists() and any(root.iterdir()) and not assume_yes:
        if not typer.confirm(
            f"Reuse non-empty storage root for {kit.spec.display_name}?"
        ):
            raise typer.Exit(code=1)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _print_env_only_setup(kit: AppConfigKit) -> None:
    """Print setup-free guidance for env-only integrations."""
    text = "\n".join(
        (
            f"{kit.spec.display_name} uses env-only AppRC setup.",
            "",
            "writes: none",
            "",
            "Set environment variables in your shell or pass explicit env files.",
            "Inspect the current paths:",
            f"  {kit.spec.config_command_name()} config paths",
        )
    )
    Console(soft_wrap=True).print(text)


def _print_app_wide_setup(
    kit: AppConfigKit,
    *,
    app_wide_path: Path,
) -> None:
    """Print setup completion for app-wide config."""
    text = "\n".join(
        (
            f"{kit.spec.display_name} app-wide config is ready.",
            "",
            f"app_wide_env: {app_wide_path}",
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} config doctor",
        )
    )
    Console(soft_wrap=True).print(
        style_literals(text, {str(app_wide_path): PATH_STYLE})
    )


def _print_storage_setup(
    kit: AppConfigKit,
    *,
    storage_root: Path,
    storage_env: Path,
    app_wide_path: Path | None,
) -> None:
    """Print setup completion for storage-capable integrations."""
    storage_key = kit.spec.require_storage_env_key()
    lines = [
        f"{kit.spec.display_name} storage config is ready.",
        "",
        f"storage_root: {storage_root}",
        f"storage_env: {storage_env}",
    ]
    if app_wide_path is not None:
        lines.append(f"app_wide_env: {app_wide_path}")
    lines.extend(
        (
            "",
            "Add this to your shell or dotenv file:",
            f'  export {storage_key}="{storage_root}"',
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} config doctor",
        )
    )
    paths = {str(storage_root): PATH_STYLE, str(storage_env): PATH_STYLE}
    if app_wide_path is not None:
        paths[str(app_wide_path)] = PATH_STYLE
    Console(soft_wrap=True).print(
        style_literals(
            "\n".join(lines),
            {
                storage_key: ENV_KEY_STYLE,
                **paths,
            },
        )
    )
