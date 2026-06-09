"""Generic config setup diagnostics."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.kit import AppConfigKit


def config_command_text(kit: AppConfigKit, action: str) -> str:
    """Return one display command for this app's config group.

    :param kit: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :return: Human-readable command text.
    """
    return f"{kit.spec.app_name} config {action}"


def config_setup_message(kit: AppConfigKit) -> str:
    """Return setup text shown when no storage is registered."""
    init_action = (
        "init /absolute/path/to/storage-root "
        f"--name {kit.default_storage_name()} --default"
    )
    return (
        f"No {kit.spec.display_name} storage is registered yet.\n\n"
        "Create a default storage:\n"
        f"  {config_command_text(kit, init_action)}\n\n"
        "Then inspect the setup:\n"
        f"  {config_command_text(kit, 'doctor')}\n"
        f"  {config_command_text(kit, 'show')}\n\n"
        "This creates:\n"
        f"  ~/.config/{kit.spec.app_name}/{kit.spec.registry_filename}\n"
        f"  /absolute/path/to/storage-root/{kit.spec.local_env_filename}"
    )


def build_config_doctor_payload(
    kit: AppConfigKit,
    *,
    storage_name: str | None,
) -> dict[str, Any]:
    """Return local setup diagnostics for one app's config registry.

    :param kit: Application config facade.
    :param storage_name: Optional registry storage selected by ``--storage``.
    :return: Stable JSON-friendly diagnostic payload.
    """
    registry_path = kit.registry_path()
    issues: list[str] = []
    selected_storage: str | None = None
    selected_storage_source: str | None = None
    selected_storage_root: Path | None = None
    registry_error: str | None = None
    storage_count = 0
    default_storage: str | None = None

    try:
        registry = kit.load_registry()
    except ValueError as exc:
        registry_error = str(exc)
        issues.append(f"Storage registry is invalid: {registry_error}")
    else:
        storage_count = len(registry.storages)
        default_storage = registry.default_storage
        env_storage = os.environ.get(kit.spec.storage_root_env_key)
        if storage_name is not None:
            selected_storage = storage_name
            selected_storage_source = "--storage"
            try:
                selected_storage_root = registry.selected(storage_name).root
            except ValueError as exc:
                issues.append(str(exc))
        elif env_storage:
            selected_storage_source = kit.spec.storage_root_env_key
            selected_storage_root = Path(env_storage).expanduser()
        elif registry.default_storage is not None:
            selected_storage = registry.default_storage
            selected_storage_source = "default_storage"
            selected_storage_root = registry.selected(
                registry.default_storage
            ).root
        elif registry.storages:
            issues.append(
                f"No default {kit.spec.display_name} storage is configured. "
                f"Run {config_command_text(kit, 'set-default NAME')}."
            )
        else:
            issues.append(
                f"No {kit.spec.display_name} storage is registered yet."
            )

    local_env = (
        selected_storage_root / kit.spec.local_env_filename
        if selected_storage_root is not None
        else None
    )
    storage_root_exists = (
        selected_storage_root.is_dir()
        if selected_storage_root is not None
        else None
    )
    local_env_exists = local_env.is_file() if local_env is not None else None
    if selected_storage_root is not None and not storage_root_exists:
        issues.append(f"Storage root does not exist: {selected_storage_root}")
    if local_env is not None and not local_env_exists:
        issues.append(f"Storage local env file does not exist: {local_env}")

    return {
        "ok": not issues,
        "registry_path": str(registry_path),
        "registry_exists": registry_path.is_file(),
        "registry_parse_ok": registry_error is None,
        "registry_error": registry_error,
        "storage_count": storage_count,
        "default_storage": default_storage,
        "selected_storage": selected_storage,
        "selected_storage_source": selected_storage_source,
        "selected_storage_root": (
            str(selected_storage_root)
            if selected_storage_root is not None
            else None
        ),
        "selected_storage_root_exists": storage_root_exists,
        "selected_local_env": (
            str(local_env) if local_env is not None else None
        ),
        "selected_local_env_exists": local_env_exists,
        "issues": issues,
        "next_steps": []
        if not issues
        else [
            config_command_text(
                kit,
                "init /absolute/path/to/storage-root "
                f"--name {kit.default_storage_name()} --default",
            ),
            config_command_text(kit, "doctor"),
            config_command_text(kit, "show"),
        ],
    }


def print_config_doctor(
    kit: AppConfigKit,
    payload: dict[str, Any],
) -> None:
    """Print a human-readable ``config doctor`` report."""
    status = "ok" if payload["ok"] else "needs setup"
    typer.echo(f"{kit.spec.display_name} config doctor: {status}")
    typer.echo("")
    typer.echo(f"registry_path: {payload['registry_path']}")
    typer.echo(f"registry_exists: {payload['registry_exists']}")
    typer.echo(f"registry_parse_ok: {payload['registry_parse_ok']}")
    typer.echo(f"storage_count: {payload['storage_count']}")
    typer.echo(f"default_storage: {payload['default_storage'] or '<none>'}")
    typer.echo(f"selected_storage: {payload['selected_storage'] or '<none>'}")
    typer.echo(
        "selected_storage_source: "
        f"{payload['selected_storage_source'] or '<none>'}"
    )
    typer.echo(
        f"selected_storage_root: {payload['selected_storage_root'] or '<none>'}"
    )
    typer.echo(
        f"selected_local_env: {payload['selected_local_env'] or '<none>'}"
    )

    issues = payload["issues"]
    if issues:
        typer.echo("")
        typer.echo("Issues:")
        for issue in issues:
            typer.echo(f"- {issue}")

        typer.echo("")
        typer.echo("Next steps:")
        for step in payload["next_steps"]:
            typer.echo(f"  {step}")
