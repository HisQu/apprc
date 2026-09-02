"""Setup command entrypoint for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.user_files.setup.flow import ConfigSetupError, ConfigSetupFlow
from apprc.user_files.storage_roots.paths import (
    StorageRootPathError,
    normalize_storage_root_path,
)
from apprc.user_files.storage_roots._naming import suggested_storage_root
from apprc.interfaces._terminal_styles import (
    ENV_KEY_STYLE,
    PATH_STYLE,
    style_literals,
)


def run_config_setup(
    kit: AppConfigKit,
    *,
    assume_yes: bool = False,
    storage_root: str | Path | None = None,
    config_group_name: str = "config",
) -> None:
    """Configure files required by the AppRC declaration.

    :param kit: Application config facade mounted by the host CLI.
    :param assume_yes: Whether to run without prompts.
    :param storage_root: Optional active storage root.
    :param config_group_name: Config command group name used in generated
        guidance.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If setup inputs are invalid.
    """
    if not kit.spec.uses_storage():
        if storage_root is not None:
            raise typer.BadParameter(
                f"{kit.spec.display_name} does not use AppRC storage.",
                param_hint="--storage-root",
            )
        if kit.spec.setup_creates_app_env():
            try:
                result = ConfigSetupFlow(kit).run_app_setup()
            except ConfigSetupError as exc:
                raise typer.BadParameter(
                    str(exc),
                    param_hint=exc.param_hint,
                ) from exc
            _print_app_setup(
                kit,
                app_path=result.app_env,
                config_group_name=config_group_name,
            )
            return
        _print_config_only_setup(kit, config_group_name=config_group_name)
        return

    root = _select_storage_root(
        kit,
        storage_root=storage_root,
        assume_yes=assume_yes,
    )
    try:
        result = ConfigSetupFlow(kit).run_storage_setup(root)
    except ConfigSetupError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint or "--storage-root",
        ) from exc
    _print_storage_setup(
        kit,
        storage_root=result.active_storage_root,
        storage_env=result.storage_env,
        app_path=result.app_env,
        config_group_name=config_group_name,
    )


def _select_storage_root(
    kit: AppConfigKit,
    *,
    storage_root: str | Path | None,
    assume_yes: bool,
) -> Path:
    """Return the storage root selected for setup before creation.

    :param kit: Application config facade.
    :param storage_root: Optional CLI-provided root.
    :param assume_yes: Whether setup may run without prompts.
    :return: Normalized storage root.
    :raises typer.Exit: If the user cancels.
    :raises typer.BadParameter: If the path cannot be used as a directory.
    """
    selected = storage_root
    suggested = (
        kit.spec.storage.suggested_root
        if kit.spec.storage is not None
        and kit.spec.storage.suggested_root is not None
        else suggested_storage_root(kit.spec.app_name)
    )
    if selected is None:
        if assume_yes:
            selected = suggested
        elif typer.confirm(f"Create storage directory at {suggested}?"):
            selected = suggested
        else:
            raise typer.Exit(code=1)
    if Path(selected) == Path("."):
        raise typer.BadParameter(
            "--storage-root must not be empty or the current directory.",
            param_hint="--storage-root",
        )
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
    return root


def _print_config_only_setup(
    kit: AppConfigKit,
    *,
    config_group_name: str,
) -> None:
    """Print setup-free guidance for config-only integrations."""
    text = "\n".join(
        (
            f"{kit.spec.display_name} needs no AppRC setup.",
            "",
            "writes: none",
            "",
            "Per-user app config is created when a value is first saved.",
            "Inspect the current paths:",
            f"  {kit.spec.config_command_name()} {config_group_name} paths",
        )
    )
    Console(soft_wrap=True).print(text)


def _print_app_setup(
    kit: AppConfigKit,
    *,
    app_path: Path | None,
    config_group_name: str,
) -> None:
    """Print setup completion for per-user app config."""
    if app_path is None:
        raise typer.BadParameter("App setup did not create a dotenv file.")
    text = "\n".join(
        (
            f"{kit.spec.display_name} app config is ready.",
            "",
            f"app_env: {app_path}",
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} {config_group_name} doctor",
        )
    )
    Console(soft_wrap=True).print(
        style_literals(text, {str(app_path): PATH_STYLE})
    )


def _print_storage_setup(
    kit: AppConfigKit,
    *,
    storage_root: Path | None,
    storage_env: Path | None,
    app_path: Path | None,
    config_group_name: str,
) -> None:
    """Print setup completion for storage-capable integrations."""
    if storage_root is None or storage_env is None:
        raise typer.BadParameter("Storage setup did not create a dotenv file.")
    storage_key = kit.spec.require_storage_selector_env_key()
    lines = [
        f"{kit.spec.display_name} storage config is ready.",
        "",
        f"storage_root: {storage_root}",
        f"storage_env: {storage_env}",
    ]
    if app_path is not None:
        lines.append(f"app_env: {app_path}")
    if kit.spec.uses_legacy_constructor():
        lines.extend(
            (
                "",
                "Add this to your shell or dotenv file:",
                f'  export {storage_key}="{storage_root}"',
            )
        )
    else:
        lines.extend(("", f"selector_saved: {storage_key}"))
    lines.extend(
        (
            "",
            "Then verify:",
            f"  {kit.spec.config_command_name()} {config_group_name} doctor",
        )
    )
    paths = {str(storage_root): PATH_STYLE, str(storage_env): PATH_STYLE}
    if app_path is not None:
        paths[str(app_path)] = PATH_STYLE
    Console(soft_wrap=True).print(
        style_literals(
            "\n".join(lines),
            {
                storage_key: ENV_KEY_STYLE,
                **paths,
            },
        )
    )
