"""Runtime storage helpers for generated config commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import typer

from apprc.cli.config.state import (
    ConfigCliState,
    active_storage_root_from_state,
)
from apprc.config.kit import AppConfigKit
from apprc.config.registry_env import RegistryEnvError
from apprc.config.storage.selector import StorageSelectorError


def active_storage_root_for_cli(
    kit: AppConfigKit,
    state: Any,
    *,
    active_storage_root_hook: Callable[[Any], Path | None] | None,
) -> Path | None:
    """Return the selected storage root using app overrides first.

    :param kit: Application config facade.
    :param state: Application root CLI state.
    :param active_storage_root_hook: Optional app-provided resolver.
    :return: Active storage root, or ``None``.
    :raises typer.BadParameter: If selector resolution fails.
    """
    try:
        if active_storage_root_hook is not None:
            return active_storage_root_hook(state)
        return active_storage_root_from_state(
            kit,
            cast(ConfigCliState, state),
        )
    except RegistryEnvError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=kit.spec.apprc_toml_env_key,
        ) from exc
    except StorageSelectorError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=exc.param_hint,
        ) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--storage") from exc


def required_storage_root_for_write(
    kit: AppConfigKit,
    state: Any,
    *,
    active_storage_root_hook: Callable[[Any], Path | None] | None,
) -> Path:
    """Return a writable active storage root or raise a CLI error.

    :param kit: Application config facade.
    :param state: Application root CLI state.
    :param active_storage_root_hook: Optional app-provided resolver.
    :return: Existing active storage root.
    :raises typer.BadParameter: If no active storage can be used.
    """
    storage_root = active_storage_root_for_cli(
        kit,
        state,
        active_storage_root_hook=active_storage_root_hook,
    )
    if storage_root is None:
        raise typer.BadParameter(
            f"No active {kit.spec.display_name} storage root. Run "
            f"`{kit.spec.config_command_name()} config setup --yes "
            "--storage-root /absolute/path/to/storage` or pass --storage.",
            param_hint="--storage",
        )
    return validate_storage_root_for_write(storage_root)


def validate_storage_root_for_write(storage_root: Path) -> Path:
    """Reject writes when the active storage root no longer exists.

    :param storage_root: Root selected for config writes.
    :return: Expanded storage root path.
    :raises typer.BadParameter: If the directory does not exist.
    """
    root = Path(storage_root).expanduser()
    if not root.is_dir():
        raise typer.BadParameter(
            f"Active storage root does not exist: {root}",
            param_hint="--storage",
        )
    return root


def default_runtime_payload(
    kit: AppConfigKit,
    *,
    storage_root: Path | None,
) -> dict[str, Any]:
    """Return generic ``config show`` data when the app provides none.

    :param kit: Application config facade.
    :param storage_root: Active storage root resolved for this command.
    :return: JSON-friendly config summary.
    """
    registry_path = kit.spec.optional_apprc_toml_path()
    return {
        "app_name": kit.spec.app_name,
        "display_name": kit.spec.display_name,
        "registry_path": (
            str(registry_path) if registry_path is not None else None
        ),
        "storage_root": str(storage_root) if storage_root else None,
    }
