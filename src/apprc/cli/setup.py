"""Interactive setup flow for generated AppRC config CLIs."""

from __future__ import annotations

# == Standard Library ========================
import os
import shutil
from pathlib import Path

# == 3rd Party ===============================
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

# == Internal ================================
from apprc.cli.doctor import build_config_doctor_payload, print_config_doctor
from apprc.cli.storage_prompts import guard_storage_root_init
from apprc.config.kit import AppConfigKit
from apprc.config.paths import StorageRootPathError
from apprc.config.storage_registry import StorageRegistry


def run_config_setup(kit: AppConfigKit) -> None:
    """Guide a user through the first AppRC setup for one application.

    :param kit: Application config facade mounted by the host CLI.
    :raises typer.Exit: If the user aborts or chooses an unusable path.
    :raises typer.BadParameter: If existing registry data or paths are invalid.
    """
    console = Console(soft_wrap=True)
    _print_setup_intro(kit, console)

    existing_path = _find_existing_registry_path(kit)
    if existing_path is None:
        registry_path = _prompt_registry_path(kit, console)
        _require_registry_path_available(kit, registry_path, console)
        registry = _load_registry(kit, registry_path)
    else:
        _, registry = _handle_existing_registry(
            kit,
            existing_path,
            console,
        )

    registry = _ensure_default_storage(kit, registry, console)
    _print_setup_finish(kit, registry, console)


def _print_setup_intro(kit: AppConfigKit, console: Console) -> None:
    """Explain the setup flow before asking for locations."""
    env_key = kit.config_file_env_key()
    default_path = _normalized_config_file_path(kit.default_registry_path())
    active_path = _normalized_config_file_path(kit.registry_path())
    body = (
        f"[bold]{kit.spec.display_name} config setup[/bold]\n\n"
        "AppRC uses one small TOML config file to remember named storage "
        "directories and which storage is the default. The config file does "
        "not contain your storage data; it only points to storage roots.\n\n"
        f"Automatic config file:\n[cyan]{default_path}[/cyan]\n\n"
        f"Override variable:\n[cyan]{env_key}[/cyan]\n\n"
        f"Active config file for this process:\n[cyan]{active_path}[/cyan]"
    )
    console.print(Panel(body, title="Setup", border_style="cyan"))


def _find_existing_registry_path(kit: AppConfigKit) -> Path | None:
    """Return the registry path setup should treat as already configured."""
    active_path = _normalized_config_file_path(kit.registry_path())
    if active_path.is_file():
        return active_path

    default_path = _normalized_config_file_path(kit.default_registry_path())
    if not _same_path(active_path, default_path) and default_path.is_file():
        return default_path
    return None


def _handle_existing_registry(
    kit: AppConfigKit,
    registry_path: Path,
    console: Console,
) -> tuple[Path, StorageRegistry]:
    """Ask how to handle an existing registry before setup continues."""
    registry = _load_registry(kit, registry_path)
    _print_existing_registry(kit, registry, console)

    active_path = _normalized_config_file_path(kit.registry_path())
    default_action = (
        "move" if not _same_path(registry_path, active_path) else "keep"
    )
    action = Prompt.ask(
        "Existing setup action",
        choices=["keep", "reset", "move"],
        default=default_action,
    )

    if action == "keep":
        _require_registry_path_available(kit, registry_path, console)
        return registry_path, registry
    if action == "reset":
        _confirm_registry_reset(kit, registry, console)
        _remove_registry_config_state(kit, registry_path)
        fresh_path = _prompt_registry_path(kit, console)
        _require_registry_path_available(kit, fresh_path, console)
        return fresh_path, _load_registry(kit, fresh_path)
    return _move_existing_registry(kit, registry_path, active_path, console)


def _print_existing_registry(
    kit: AppConfigKit,
    registry: StorageRegistry,
    console: Console,
) -> None:
    """Show the current registry and its known storage roots."""
    table = Table(title="Registered storages", show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Default")
    table.add_column("Root")
    for name in sorted(registry.storages):
        record = registry.selected(name)
        table.add_row(
            name,
            "yes" if name == registry.default_storage else "",
            str(record.root),
        )

    body = (
        f"AppRC found an existing {kit.spec.display_name} config file:\n"
        f"[cyan]{registry.path}[/cyan]\n\n"
        "Keeping it preserves the registered storage roots. Resetting removes "
        "only AppRC config state, not storage directories. Moving it preserves "
        "the registry contents at a new config-file path."
    )
    console.print(
        Panel(body, title="Step 0: Existing Setup", border_style="yellow")
    )
    if registry.storages:
        console.print(table)
    else:
        console.print("[dim]No live storages are registered yet.[/dim]")


def _confirm_registry_reset(
    kit: AppConfigKit,
    registry: StorageRegistry,
    console: Console,
) -> None:
    """Warn before deleting AppRC config state."""
    if registry.storages:
        console.print(
            "[bold yellow]Resetting will orphan these registered storages.[/bold yellow]"
        )
        for name in sorted(registry.storages):
            record = registry.selected(name)
            console.print(f"  [yellow]- {name}: {record.root}[/yellow]")
    console.print(
        "Storage directories are left untouched. Only the AppRC config file "
        "is removed. When it lives below the automatic config directory, that "
        f"AppRC-owned {kit.spec.display_name} directory is removed too."
    )
    if not Confirm.ask("Reset AppRC config state?", default=False):
        console.print("Aborted.")
        raise typer.Exit(code=1)


def _remove_registry_config_state(
    kit: AppConfigKit,
    registry_path: Path,
) -> None:
    """Delete only AppRC config files, never registered storage roots."""
    default_dir = _normalized_config_file_path(
        kit.default_registry_path()
    ).parent
    resolved_registry_path = _normalized_config_file_path(registry_path)
    if resolved_registry_path.is_relative_to(default_dir):
        shutil.rmtree(default_dir, ignore_errors=True)
        return
    resolved_registry_path.unlink(missing_ok=True)


def _move_existing_registry(
    kit: AppConfigKit,
    source_path: Path,
    active_path: Path,
    console: Console,
) -> tuple[Path, StorageRegistry]:
    """Move the existing registry file and return the moved registry."""
    console.print(
        Panel(
            "Choose the new config-file path. If this is not the automatic "
            f"default, {kit.config_file_env_key()} must point to it.",
            title="Move Config File",
            border_style="cyan",
        )
    )
    target_path = _prompt_registry_path(
        kit,
        console,
        default_path=active_path,
        title="Move target",
    )
    _require_registry_path_available(kit, target_path, console)
    if _same_path(source_path, target_path):
        return target_path, _load_registry(kit, target_path)
    if target_path.exists():
        if target_path.is_dir():
            raise typer.BadParameter(
                f"Config file target is a directory: {target_path}",
                param_hint="CONFIG_FILE",
            )
        if not Confirm.ask("Replace existing config file?", default=False):
            console.print("Aborted.")
            raise typer.Exit(code=1)
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(target_path))
    console.print(f"Moved config file to [cyan]{target_path}[/cyan].")
    return target_path, _load_registry(kit, target_path)


def _prompt_registry_path(
    kit: AppConfigKit,
    console: Console,
    *,
    default_path: Path | None = None,
    title: str = "Step 1: Config File",
) -> Path:
    """Ask where the AppRC registry TOML file should live."""
    env_key = kit.config_file_env_key()
    suggested = default_path or _normalized_config_file_path(
        kit.registry_path()
    )
    body = (
        "This TOML file stores the storage registry: storage names, storage "
        "root paths, and the default storage. It is small and safe to keep in "
        "your normal per-user config directory.\n\n"
        f"Press Enter to use:\n[cyan]{suggested}[/cyan]\n\n"
        f"To use any custom path, start the command with [cyan]{env_key}[/cyan] "
        "pointing at that exact file. AppRC does not edit shell startup files."
    )
    console.print(Panel(body, title=title, border_style="cyan"))
    raw_path = Prompt.ask("Config file", default=str(suggested))
    return _normalized_config_file_path(raw_path)


def _require_registry_path_available(
    kit: AppConfigKit,
    registry_path: Path,
    console: Console,
) -> None:
    """Reject config-file paths future commands cannot rediscover."""
    default_path = _normalized_config_file_path(kit.default_registry_path())
    if _same_path(registry_path, default_path):
        raw_override = os.environ.get(kit.config_file_env_key(), "").strip()
        if raw_override and not _same_path(raw_override, default_path):
            console.print(
                "[bold red]The config-file override is active.[/bold red]\n"
                f"Unset it before using the automatic path:\n"
                f"[cyan]unset {kit.config_file_env_key()}[/cyan]"
            )
            raise typer.Exit(code=1)
        return

    if _env_path_matches(kit, registry_path):
        return

    console.print(
        "[bold red]Custom config-file paths require an environment variable.[/bold red]\n"
        "Run setup again with this variable exported so future commands use "
        "the same file:\n"
        f"[cyan]{_export_config_file_command(kit, registry_path)}[/cyan]"
    )
    raise typer.Exit(code=1)


def _ensure_default_storage(
    kit: AppConfigKit,
    registry: StorageRegistry,
    console: Console,
) -> StorageRegistry:
    """Ensure the registry has a live default storage."""
    console.print(
        Panel(
            "A storage root is where the application keeps user data and the "
            f"storage-local {kit.spec.local_env_filename} file. The registry "
            "can remember many named storages, but setup makes one default so "
            "normal commands work without --storage.",
            title="Step 2: Default Storage",
            border_style="cyan",
        )
    )

    current_default = registry.default()
    if current_default is not None and current_default.root.is_dir():
        console.print(
            "Current default storage:\n"
            f"[bold]{current_default.name}[/bold] -> "
            f"[cyan]{current_default.root}[/cyan]"
        )
        if Confirm.ask("Keep this default storage?", default=True):
            return registry

    storage_name = Prompt.ask(
        "Storage name",
        default=registry.default_storage or "default",
    )
    raw_storage_root = Prompt.ask(
        "Storage root",
        default=str(kit.default_storage_data_root()),
    )
    normalized_root = guard_storage_root_init(
        kit,
        Path(raw_storage_root),
        storage_name=storage_name,
        make_default=True,
        assume_yes=False,
    )
    try:
        return kit.register_storage(
            name=storage_name,
            root=normalized_root,
            make_default=True,
            path=registry.path,
        )
    except StorageRootPathError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="STORAGE_ROOT",
        ) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="Storage name") from exc


def _print_setup_finish(
    kit: AppConfigKit,
    registry: StorageRegistry,
    console: Console,
) -> None:
    """Run diagnostics and print next commands."""
    console.print(
        Panel("Setup wrote the registry. Running doctor now.", title="Step 3")
    )
    payload = build_config_doctor_payload(kit, storage_name=None)
    print_config_doctor(kit, payload)

    lines = [
        f"[cyan]{kit.spec.app_name} config edit[/cyan]",
        f"[cyan]{kit.spec.app_name} config show[/cyan]",
        f"[cyan]{kit.spec.app_name} config doctor[/cyan]",
    ]
    if not _same_path(registry.path, kit.default_registry_path()):
        lines.append(
            "\nKeep this variable exported for future shells:\n"
            f"[cyan]{_export_config_file_command(kit, registry.path)}[/cyan]"
        )
    body = "Next steps:\n" + "\n".join(f"  {line}" for line in lines)
    console.print(Panel(body, title="Done", border_style="green"))
    if not payload["ok"]:
        raise typer.Exit(code=1)


def _load_registry(kit: AppConfigKit, registry_path: Path) -> StorageRegistry:
    """Load a registry and convert parse failures to CLI errors."""
    try:
        return kit.load_registry(path=registry_path)
    except ValueError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint=str(registry_path),
        ) from exc


def _env_path_matches(kit: AppConfigKit, registry_path: Path) -> bool:
    """Return whether the override env var points at ``registry_path``."""
    raw_override = os.environ.get(kit.config_file_env_key(), "").strip()
    if not raw_override:
        return False
    return _same_path(raw_override, registry_path)


def _export_config_file_command(kit: AppConfigKit, registry_path: Path) -> str:
    """Return the shell export command for one custom config file path."""
    path_text = str(_normalized_config_file_path(registry_path)).replace(
        '"', '\\"'
    )
    return f'export {kit.config_file_env_key()}="{path_text}"'


def _same_path(left: str | Path, right: str | Path) -> bool:
    """Return whether two path spellings identify the same filesystem path."""
    return _normalized_config_file_path(left) == _normalized_config_file_path(
        right
    )


def _normalized_config_file_path(path: str | Path) -> Path:
    """Return an absolute, user-expanded config file path."""
    return Path(path).expanduser().resolve()
