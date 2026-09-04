"""Named-storage generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.interfaces.cli.config_command._output import (
    print_storage_list,
    storage_list_payload,
)
from apprc.interfaces.cli.config_command._prompts import guard_storage_root_init
from apprc.interfaces.cli._typer_utils import dump_json
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.storage_roots._loading import apprc_toml_path_for_create
from apprc.user_files.storage_roots.paths import StorageRootPathError
from apprc.user_files.storage_roots.move import StorageMoveError, move_storage
from apprc.user_files.storage_roots.registry import (
    register_storage,
    rename_storage,
    repoint_storage,
    select_storage,
    unregister_storage,
)


class StorageConfigCommands(ConfigCommandBase):
    """Named-storage config command implementations."""

    def storage_list(self, ctx: typer.Context, *, json_output: bool) -> None:
        """List named storage roots from optional AppRC TOML."""
        selector_context = self.cli_selector_context(ctx)
        registry = self.load_storage_registry_or_empty(
            selector_context=selector_context,
        )
        payload = storage_list_payload(
            registry,
            storage_dotenv_filename=self.kit.spec.storage_dotenv_filename,
            active_storage_root=self.best_effort_active_storage_root_from_env(
                storage_registry=registry,
                selector_context=selector_context,
            ),
        )
        if json_output:
            dump_json(payload)
            return
        print_storage_list(payload)

    def storage_add(
        self,
        ctx: typer.Context,
        *,
        name: str,
        path: Path,
        assume_yes: bool,
    ) -> None:
        """Create one named storage entry."""
        self.require_storage_registry_support()
        selector_context = self.cli_selector_context(ctx)
        apprc_toml_path = apprc_toml_path_for_create(
            self.kit.spec,
            proc_env=selector_context.proc_env,
        )
        normalized_root = guard_storage_root_init(
            self.kit,
            path,
            storage_name=name,
            assume_yes=assume_yes,
            apprc_toml_path=apprc_toml_path,
        )
        try:
            registry = register_storage(
                name=name,
                root=normalized_root,
                path=apprc_toml_path,
                storage_dotenv_filename=self.kit.spec.storage_dotenv_filename,
            )
        except StorageRootPathError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="PATH",
            ) from exc
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc

        record = registry.selected(name)
        typer.echo(f"storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(
            f"storage_dotenv: {self.kit.spec.storage_dotenv_path(record.root)}"
        )
        typer.echo(f"apprc_toml: {registry.path}")

    def storage_select(self, ctx: typer.Context, *, name: str) -> None:
        """Persist the selected storage name."""
        path = self._registry_path(ctx)
        try:
            registry = select_storage(name=name, path=path)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"selected_storage: {registry.selected_storage}")
        typer.echo(f"apprc_toml: {registry.path}")

    def storage_rename(
        self,
        ctx: typer.Context,
        *,
        name: str,
        new_name: str,
    ) -> None:
        """Rename a registered storage without moving data."""
        path = self._registry_path(ctx)
        try:
            registry = rename_storage(
                current_name=name,
                name=new_name,
                path=path,
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"renamed_storage: {name} -> {new_name}")
        typer.echo(f"selected_storage: {registry.selected_storage or '<none>'}")

    def storage_repoint(
        self,
        ctx: typer.Context,
        *,
        name: str,
        root: Path,
    ) -> None:
        """Change only one registered root path."""
        path = self._registry_path(ctx)
        try:
            registry = repoint_storage(name=name, root=root, path=path)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="ROOT") from exc
        record = registry.selected(name)
        typer.echo(f"repointed_storage: {name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo("files_moved: no")

    def storage_move(
        self,
        ctx: typer.Context,
        *,
        name: str,
        destination: Path,
        assume_yes: bool,
    ) -> None:
        """Move a complete storage directory and update its registry root."""
        path = self._registry_path(ctx)
        if not assume_yes and not typer.confirm(
            f"Move storage {name!r} to {destination}?"
        ):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        try:
            result = move_storage(
                name=name,
                destination=destination,
                path=path,
            )
        except (OSError, StorageMoveError, ValueError) as exc:
            raise typer.BadParameter(
                str(exc), param_hint="DESTINATION"
            ) from exc
        typer.echo(f"moved_storage: {result.name}")
        typer.echo(f"storage_root: {result.destination}")
        for warning in result.warnings:
            typer.echo(f"warning: {warning}", err=True)

    def storage_remove(self, ctx: typer.Context, *, name: str) -> None:
        """Remove one named storage entry from the index."""
        self.require_storage_registry_support()
        path = self._registry_path(ctx)
        try:
            current = self.load_storage_registry_or_empty(
                selector_context=self.cli_selector_context(ctx)
            )
            removed_selected = current.selected_storage == name
            registry = unregister_storage(
                name=name,
                path=path,
            )
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"removed_storage: {name}")
        if removed_selected:
            typer.echo(
                "warning: the selected storage was removed; no storage is "
                "selected now.",
                err=True,
            )
        typer.echo(f"apprc_toml: {registry.path}")

    def _registry_path(self, ctx: typer.Context) -> Path:
        """Return the fixed registry path for one command context.

        :param ctx: Active Typer context.
        :return: AppRC TOML path selected by ``<APP>_APPRC_DIR``.
        """
        self.require_storage_support()
        selector_context = self.cli_selector_context(ctx)
        return apprc_toml_path_for_create(
            self.kit.spec,
            proc_env=selector_context.proc_env,
        )
