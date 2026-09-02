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
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.user_files.storage_roots._loading import apprc_toml_path_for_create
from apprc.user_files.storage_roots.paths import StorageRootPathError
from apprc.user_files.storage_roots.registry import (
    register_storage,
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
            storage_env_filename=self.kit.spec.require_storage().env_filename,
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
        """Create or update one named storage entry."""
        self.require_named_storage_support()
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
                storage_env_filename=self.kit.spec.require_storage().env_filename,
            )
        except StorageRootPathError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="PATH",
            ) from exc
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc

        record = registry.selected(name)
        typer.echo(f"storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(
            f"storage_env: {self.kit.spec.storage_env_path(record.root)}"
        )
        typer.echo(f"apprc_toml: {registry.path}")

    def storage_remove(self, ctx: typer.Context, *, name: str) -> None:
        """Remove one named storage entry from the index."""
        self.require_named_storage_support()
        selector_context = self.cli_selector_context(ctx)
        try:
            registry = unregister_storage(
                name=name,
                path=apprc_toml_path_for_create(
                    self.kit.spec,
                    proc_env=selector_context.proc_env,
                ),
            )
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"removed_storage: {name}")
        typer.echo(f"apprc_toml: {registry.path}")
