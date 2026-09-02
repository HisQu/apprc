"""Runtime generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Literal, cast

# == 3rd Party ===============================
import typer
from rich import print as rich_print

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
    ResolvedConfigState,
)
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)
from apprc.interfaces.cli._typer_utils import dump_json
from apprc.runtime.diagnostics.payload import build_config_doctor_payload
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.user_files.env_files.updates import (
    set_env_file_value,
    set_storage_env_value,
)
from apprc.user_files.storage_roots.paths import StorageRootPathError
from apprc.user_files.migration import (
    ConfigMigrationPlan,
    ConfigMigrationResult,
    ConfigMigrationError,
    apply_config_migration,
    build_config_migration_plan,
)


type ConfigSetScope = Literal["app", "storage"]


class RuntimeConfigCommands(ConfigCommandBase):
    """Runtime config command implementations."""

    def paths(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show declared and active config paths without writing files."""
        selector_context = self.cli_selector_context(ctx)
        storage = self.cli_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.kit,
            storage=storage_selector,
            explicit_values=selector_context.explicit_values,
            env_file_overrides_os_environ=(
                selector_context.env_file_overrides_os_environ
            ),
            config_group_name=self.config_group_name,
        )
        if json_output:
            dump_json(payload.to_payload())
            return
        print_config_paths(self.kit, payload)

    def show(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show the resolved runtime config available to this CLI run."""
        current_state = self.resolved_config_state(ctx)
        storage_root = (
            self.active_storage_root_for_cli(current_state)
            if current_state is not None
            else None
        )
        if self.kit.spec.uses_storage() and storage_root is None:
            typer.echo(self.missing_setup, err=True)
            raise typer.Exit(code=1)
        try:
            if self.runtime_payload is not None:
                payload_state = self.runtime_payload_state(current_state)
                if payload_state is None:
                    raise RuntimeError("CLI state is not initialized.")
                payload = self.runtime_payload(payload_state)
            else:
                payload = self.default_runtime_payload(
                    storage_root=storage_root,
                )
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.runtime_error_param_hint,
            ) from exc
        if json_output:
            dump_json(payload)
            return
        rich_print(payload)

    def doctor(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Check AppRC config readiness and print suggested fixes."""
        selector_context = self.cli_selector_context(ctx)
        storage = self.cli_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.kit,
            storage=storage_selector,
            explicit_values=selector_context.explicit_values,
            env_file_overrides_os_environ=(
                selector_context.env_file_overrides_os_environ
            ),
            config_group_name=self.config_group_name,
        )
        if json_output:
            dump_json(payload.to_payload())
        else:
            print_config_doctor(self.kit, payload)
        if payload.status != ConfigDoctorStatus.RUNNABLE.value:
            raise typer.Exit(code=1)

    def migrate(
        self,
        ctx: typer.Context,
        *,
        dry_run: bool,
        assume_yes: bool,
    ) -> None:
        """Move legacy AppRC-managed files to current filenames."""
        plan = self._migration_plan(ctx)
        self._reject_migration_conflicts(plan)
        if not plan.moves:
            typer.echo("AppRC files already use the current filenames.")
            return
        self._print_migration_moves(plan, dry_run=dry_run)
        if dry_run:
            return
        if not assume_yes and not typer.confirm("Move these files?"):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        result = self._apply_migration_plan(plan)
        typer.echo(f"migrated_files: {len(result.moved)}")

    def _migration_plan(self, ctx: typer.Context) -> ConfigMigrationPlan:
        """Build a migration plan from every CLI-visible storage root.

        :param ctx: Active Typer context.
        :return: Conflict and move inventory.
        """
        selector_context = self.cli_selector_context(ctx)
        try:
            return build_config_migration_plan(
                self.kit.spec,
                storage_roots=self._migration_storage_roots(selector_context),
            )
        except ConfigMigrationError as exc:
            raise typer.BadParameter(str(exc), param_hint="migrate") from exc

    def _migration_storage_roots(
        self,
        selector_context: ConfigSelectorContext,
    ) -> tuple[Path, ...]:
        """Return registered and active roots visible to migration.

        :param selector_context: Explicit CLI selector inputs.
        :return: Storage roots whose managed files should be considered.
        """
        if not self.kit.spec.uses_storage():
            return ()
        registry = self.load_storage_registry_or_empty(
            selector_context=selector_context,
        )
        roots = [record.root for record in registry.storages.values()]
        active_root = self.best_effort_active_storage_root_from_env(
            storage_registry=registry,
            selector_context=selector_context,
        )
        if active_root is not None:
            roots.append(active_root)
        return tuple(roots)

    @staticmethod
    def _reject_migration_conflicts(plan: ConfigMigrationPlan) -> None:
        """Print every migration conflict and stop before writes.

        :param plan: Migration inventory to validate.
        """
        if plan.conflicts:
            typer.echo("Migration stopped: conflicting files exist.", err=True)
            for conflict in plan.conflicts:
                typer.echo(
                    f"conflict: {conflict.label}: {conflict.preferred} and "
                    f"{conflict.conflicting}",
                    err=True,
                )
            raise typer.Exit(code=1)

    @staticmethod
    def _print_migration_moves(
        plan: ConfigMigrationPlan,
        *,
        dry_run: bool,
    ) -> None:
        """Print planned or imminent filename moves.

        :param plan: Conflict-free migration inventory.
        :param dry_run: Whether the command stops after presentation.
        """
        for move in plan.moves:
            typer.echo(
                f"{'would_move' if dry_run else 'move'}: "
                f"{move.source} -> {move.destination}"
            )

    @staticmethod
    def _apply_migration_plan(
        plan: ConfigMigrationPlan,
    ) -> ConfigMigrationResult:
        """Apply a migration plan and render any partial failure.

        :param plan: Confirmed migration inventory.
        :return: Completed move result.
        """
        try:
            return apply_config_migration(plan)
        except ConfigMigrationError as exc:
            typer.echo(str(exc), err=True)
            for move in exc.completed:
                typer.echo(
                    f"moved_before_failure: {move.destination}",
                    err=True,
                )
            raise typer.Exit(code=1) from exc

    def set(
        self,
        ctx: typer.Context,
        *,
        key: str,
        value: str,
        scope: str | None,
    ) -> None:
        """Write one config override to the selected writable layer."""
        selector_context = self.cli_selector_context(ctx)
        current_state = self.resolved_config_state(ctx)
        resolved_scope = self._resolve_write_scope(
            current_state,
            requested_scope=scope,
            selector_context=selector_context,
        )
        if resolved_scope == "app":
            update = self._set_app_value(key=key, value=value)
            typer.echo(f"updated: {update.env_key}")
            typer.echo(f"app_env: {update.path}")
            return
        if current_state is None:
            raise typer.BadParameter(
                "Storage scope requires runtime CLI state.",
                param_hint="--scope",
            )
        root = self.required_storage_root_for_write(
            current_state,
            selector_context=selector_context,
        )
        update = self._set_storage_value(root=root, key=key, value=value)
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"storage_env: {update.path}")

    def _resolve_write_scope(
        self,
        state: ResolvedConfigState | None,
        *,
        requested_scope: str | None,
        selector_context: ConfigSelectorContext,
    ) -> ConfigSetScope:
        """Return the target write scope or raise for ambiguous writes.

        :param state: Optional resolved CLI state.
        :param requested_scope: User-provided scope.
        :return: Concrete write scope.
        :raises typer.BadParameter: If no layer or multiple layers qualify.
        """
        if requested_scope is not None:
            if requested_scope not in {"app", "storage"}:
                raise typer.BadParameter(
                    "--scope must be 'app' or 'storage'.",
                    param_hint="--scope",
                )
            resolved_requested_scope = cast(ConfigSetScope, requested_scope)
            if not self._write_scope_is_active(
                state,
                resolved_requested_scope,
                selector_context=selector_context,
            ):
                raise typer.BadParameter(
                    _inactive_scope_message(
                        self.kit,
                        resolved_requested_scope,
                        config_group_name=self.config_group_name,
                    ),
                    param_hint="--scope",
                )
            return resolved_requested_scope
        active_scopes = self._active_write_scopes(
            state,
            selector_context=selector_context,
        )
        if len(active_scopes) == 1:
            return active_scopes[0]
        if not active_scopes:
            raise typer.BadParameter(
                "No writable AppRC layer is active. Run "
                f"`{self.config_command_text('app init')}`, select a storage "
                "root, or set environment variables directly.",
                param_hint="--scope",
            )
        raise typer.BadParameter(
            "Both app config and storage config are writable. Pass "
            "--scope app or --scope storage.",
            param_hint="--scope",
        )

    def _active_write_scopes(
        self,
        state: ResolvedConfigState | None,
        *,
        selector_context: ConfigSelectorContext,
    ) -> list[ConfigSetScope]:
        """Return write scopes currently active for ``config set``."""
        return [
            scope
            for scope in ("app", "storage")
            if self._write_scope_is_active(
                state,
                scope,
                selector_context=selector_context,
            )
        ]

    def _write_scope_is_active(
        self,
        state: ResolvedConfigState | None,
        scope: ConfigSetScope,
        *,
        selector_context: ConfigSelectorContext,
    ) -> bool:
        """Return whether one write scope can be updated now."""
        if scope == "app":
            if not self.kit.spec.uses_legacy_constructor():
                return True
            app_path = self.kit.spec.app_env_path()
            return self.kit.spec.app_env_enabled() and (
                self.kit.spec.setup_creates_app_env() or app_path.is_file()
            )
        if not self.kit.spec.uses_storage() or state is None:
            return False
        storage_root = self.active_storage_root_for_cli(
            state,
            selector_context=selector_context,
        )
        return storage_root is not None and storage_root.is_dir()

    def _set_app_value(self, *, key: str, value: str):
        """Write one value to the per-user app dotenv file."""
        try:
            return set_env_file_value(
                path=self.kit.spec.app_env_path(),
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                layer_name=self.kit.spec.app_env_filename,
            )
        except (ConfigHomeError, OSError) as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc

    def _set_storage_value(self, *, root: Path, key: str, value: str):
        """Write one value to the selected storage dotenv file."""
        try:
            return set_storage_env_value(
                storage_root=root,
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                storage_env_filename=self.kit.spec.require_storage().env_filename,
            )
        except (ConfigHomeError, OSError, StorageRootPathError) as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="--storage",
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc


def _inactive_scope_message(
    kit: AppConfigKit,
    scope: ConfigSetScope,
    *,
    config_group_name: str = "config",
) -> str:
    """Return a readable error for an unavailable write scope.

    :param kit: Application config facade.
    :param scope: Requested write scope.
    :param config_group_name: Config command group name used in generated
        guidance.
    :return: Human-facing CLI error.
    """
    if scope == "app":
        return (
            "App config is not active. Run "
            f"`{kit.spec.config_command_name()} {config_group_name} app init` "
            "first."
        )
    return (
        "The storage layer is not active. Select a storage root with --storage "
        f"or export {kit.spec.storage_selector_env_key}."
    )
