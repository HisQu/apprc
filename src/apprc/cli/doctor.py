"""Generic config setup diagnostics."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.environment import resolve_storage_selector_value
from apprc.config.install_state import ConfigInstallState
from apprc.config.kit import AppConfigKit


def config_command_text(kit: AppConfigKit, action: str) -> str:
    """Return one display command for this app's config group.

    :param kit: Application config facade.
    :param action: Command suffix after ``<app> config``.
    :return: Human-readable command text.
    """
    return f"{kit.spec.config_command_name()} config {action}"


def config_setup_message(kit: AppConfigKit) -> str:
    """Return setup text shown when no storage is registered."""
    storage_key = kit.spec.storage_env_key
    setup_action = (
        "setup --yes --apprc-toml "
        f"/absolute/path/to/{kit.spec.apprc_toml_filename}"
    )
    return (
        f"No {kit.spec.display_name} AppRC TOML is installed yet.\n\n"
        f"{kit.spec.display_name} expects {kit.apprc_toml_env_key()} to point "
        "at its AppRC TOML, and "
        f"{storage_key} to track the active storage selector.\n"
        "Choose where that file should live, then run setup:\n"
        f"  {config_command_text(kit, setup_action)}\n\n"
        "Keep both variables exported for future commands, then inspect the setup:\n"
        f"  {config_command_text(kit, 'doctor')}\n"
        f"  {config_command_text(kit, 'show')}\n\n"
        "Setup creates:\n"
        f"  /absolute/path/to/{kit.spec.apprc_toml_filename}\n"
        f"  /absolute/path/to/storage-root/{kit.spec.local_env_filename}"
    )


def build_config_doctor_payload(
    kit: AppConfigKit,
    *,
    storage_name: str | None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Return local setup diagnostics for one app's config registry.

    :param kit: Application config facade.
    :param storage_name: Optional registry storage selected by ``--storage``.
    :param registry_path: Optional explicit registry path used by setup.
    :return: Stable JSON-friendly diagnostic payload.
    """
    registry_env_key = kit.apprc_toml_env_key()
    raw_registry_env_value = os.environ.get(registry_env_key, "").strip()
    registry_env_value = raw_registry_env_value or None
    active_registry_path = (
        Path(registry_path).expanduser().resolve()
        if registry_path is not None
        else kit.optional_registry_path()
    )
    issues: list[str] = []
    selected_storage: str | None = None
    selected_storage_source: str | None = None
    selected_storage_root: Path | None = None
    registry_error: str | None = None
    storage_count = 0
    default_storage: str | None = None
    registry_exists = (
        active_registry_path.is_file()
        if active_registry_path is not None
        else False
    )
    install_state = ConfigInstallState.NOT_INSTALLED

    if active_registry_path is None:
        issues.append(
            f"{registry_env_key} is not set. Run "
            f"{config_command_text(kit, f'setup --yes --apprc-toml /absolute/path/to/{kit.spec.apprc_toml_filename}')}"
            " and keep the printed export command in your shell setup."
        )
    elif not registry_exists:
        issues.append(f"AppRC TOML does not exist: {active_registry_path}")
    else:
        install_state = ConfigInstallState.INSTALLED_UNHEALTHY
        try:
            registry = kit.load_registry(path=active_registry_path)
        except ValueError as exc:
            registry_error = str(exc)
            issues.append(f"Storage registry is invalid: {registry_error}")
        else:
            storage_count = len(registry.storages)
            default_storage = registry.default_storage
            env_storage = os.environ.get(kit.spec.storage_env_key)
            if not registry.storages:
                issues.append(
                    f"No {kit.spec.display_name} storage is registered yet."
                )
            elif registry.default_storage is None:
                issues.append(
                    f"No default {kit.spec.display_name} storage is "
                    "configured. "
                    f"Run {config_command_text(kit, 'set-default NAME')}."
                )

            if storage_name is not None:
                selected_storage = storage_name
                selected_storage_source = "--storage"
                try:
                    selected_storage_root = registry.selected(storage_name).root
                except ValueError as exc:
                    issues.append(str(exc))
            elif env_storage:
                selected_storage_source = kit.spec.storage_env_key
                try:
                    record, root = resolve_storage_selector_value(
                        registry=registry,
                        raw_value=env_storage,
                        storage_env_key=kit.spec.storage_env_key,
                    )
                except ValueError as exc:
                    issues.append(str(exc))
                else:
                    selected_storage_root = root
                    if record is not None:
                        selected_storage = record.name
            elif registry.default_storage is not None:
                selected_storage = registry.default_storage
                selected_storage_source = "default_storage"
                selected_storage_root = registry.selected(
                    registry.default_storage
                ).root

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

    if registry_exists and not issues:
        install_state = ConfigInstallState.INSTALLED_HEALTHY
    elif registry_exists:
        install_state = ConfigInstallState.INSTALLED_UNHEALTHY

    healthy = install_state == ConfigInstallState.INSTALLED_HEALTHY
    return {
        "ok": healthy,
        "install_state": install_state.value,
        "installed": install_state != ConfigInstallState.NOT_INSTALLED,
        "healthy": healthy,
        "registry_env_key": registry_env_key,
        "registry_env_value": registry_env_value,
        "registry_path": (
            str(active_registry_path)
            if active_registry_path is not None
            else None
        ),
        "registry_exists": registry_exists,
        "registry_parse_ok": registry_exists and registry_error is None,
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
                f"setup --yes --apprc-toml /absolute/path/to/{kit.spec.apprc_toml_filename}",
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
    status_labels = {
        ConfigInstallState.NOT_INSTALLED.value: "not installed",
        ConfigInstallState.INSTALLED_UNHEALTHY.value: (
            "installed but unhealthy"
        ),
        ConfigInstallState.INSTALLED_HEALTHY.value: "installed and healthy",
    }
    status = status_labels[str(payload["install_state"])]
    typer.echo(f"{kit.spec.display_name} config doctor: {status}")
    typer.echo("")
    typer.echo(f"registry_env_key: {payload['registry_env_key']}")
    typer.echo(
        f"registry_env_value: {payload['registry_env_value'] or '<none>'}"
    )
    typer.echo(f"registry_path: {payload['registry_path'] or '<none>'}")
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
