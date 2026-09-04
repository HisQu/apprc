"""Runtime generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
import sys
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
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
    EnvFileUpdate,
    apply_env_file_edit,
    plan_env_file_value_update,
    plan_storage_dotenv_value_update,
)
from apprc.user_files.storage_roots.paths import StorageRootPathError
from apprc.user_files.migration import (
    ConfigMigrationPlan,
    ConfigMigrationResult,
    ConfigMigrationError,
    apply_config_migration,
    build_config_migration_plan,
)
from apprc.user_files.purge import (
    ConfigPurgeError,
    apply_config_purge,
    build_config_purge_plan,
)


type ConfigSetScope = Literal["user", "storage"]


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
        if not plan.moves and not plan.writes:
            typer.echo("No released AppRC 0.19 files need migration.")
            for warning in plan.warnings:
                typer.echo(f"warning: {warning}", err=True)
            return
        self._print_migration_moves(plan, dry_run=dry_run)
        if dry_run:
            return
        if not assume_yes and not typer.confirm("Move these files?"):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        result = self._apply_migration_plan(plan)
        typer.echo(f"migrated_files: {len(result.moved) + len(result.written)}")
        for warning in plan.warnings:
            typer.echo(f"warning: {warning}", err=True)

    def purge(self, *, dry_run: bool, assume_yes: bool) -> None:
        """Remove only fixed AppRC files and registered internal storage."""
        try:
            plan = build_config_purge_plan(self.kit.spec)
        except ConfigPurgeError as exc:
            raise typer.BadParameter(str(exc), param_hint="purge") from exc
        typer.echo(f"apprc_dir: {plan.apprc_dir}")
        for path in plan.managed_files:
            typer.echo(f"{'would_remove' if dry_run else 'remove'}: {path}")
        for root in plan.internal_storage_roots:
            typer.echo(
                f"{'would_remove_tree' if dry_run else 'remove_tree'}: {root}"
            )
        for root in plan.external_storage_roots:
            typer.echo(f"keep_external_storage_data: {root}")
        if plan.stale_storage:
            typer.echo(
                "warning: apprc.toml contains stale storage configuration for "
                "an app that no longer declares storage.",
                err=True,
            )
        if dry_run:
            return
        if not assume_yes and not typer.confirm(
            "Remove these AppRC-managed files and internal storage roots?"
        ):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        try:
            result = apply_config_purge(plan)
        except OSError as exc:
            raise typer.BadParameter(str(exc), param_hint="purge") from exc
        typer.echo(f"removed_entries: {len(result.removed)}")
        for path in result.skipped:
            typer.echo(f"skipped_unsafe_target: {path}", err=True)

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
        for write in plan.writes:
            typer.echo(
                f"{'would_write' if dry_run else 'write'}: {write.destination}"
            )
            if write.source is not None and write.source != write.destination:
                typer.echo(f"  remove_legacy: {write.source}")

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
        if resolved_scope == "user":
            plan = self._plan_user_value(key=key, value=value)
            update = self._confirm_and_apply_env_file_edit(plan)
            typer.echo(f"updated: {update.env_key}")
            typer.echo(f"user_dotenv: {update.path}")
            self._print_post_write_warnings(plan)
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
        plan = self._plan_storage_value(root=root, key=key, value=value)
        update = self._confirm_and_apply_env_file_edit(plan)
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"storage_dotenv: {update.path}")
        self._print_post_write_warnings(plan)

    @staticmethod
    def _confirm_and_apply_env_file_edit(
        plan: EnvFileEditPlan,
    ) -> EnvFileUpdate:
        """Confirm duplicate cleanup when interactive, then write the edit.

        :param plan: Validated dotenv edit to inspect and apply.
        :return: Completed dotenv update.
        """
        interactive = _is_interactive_terminal()
        if plan.warnings and interactive:
            for warning in plan.warnings:
                typer.echo(f"Warning: {warning}", err=True)
            if not typer.confirm("Continue with this dotenv edit?"):
                typer.echo("Aborted.")
                raise typer.Exit(code=1)
        return apply_env_file_edit(plan)

    @staticmethod
    def _print_post_write_warnings(plan: EnvFileEditPlan) -> None:
        """Print warnings after a non-interactive dotenv write.

        :param plan: Applied edit whose warnings may need output.
        """
        if _is_interactive_terminal():
            return
        for warning in plan.warnings:
            typer.echo(f"Warning: {warning}", err=True)

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
            supported_scopes = (
                {"user", "storage"}
                if self.kit.spec.uses_storage()
                else {"user"}
            )
            if requested_scope not in supported_scopes:
                raise typer.BadParameter(
                    "--scope must be "
                    + " or ".join(
                        repr(item) for item in sorted(supported_scopes)
                    )
                    + ".",
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
                f"`{self.config_command_text('setup')}`.",
                param_hint="--scope",
            )
        raise typer.BadParameter(
            "Both user and storage dotenv files are writable. Pass "
            "--scope user or --scope storage.",
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
            for scope in ("user", "storage")
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
        if scope == "user":
            return True
        if not self.kit.spec.uses_storage() or state is None:
            return False
        storage_root = self.active_storage_root_for_cli(
            state,
            selector_context=selector_context,
        )
        return storage_root is not None and storage_root.is_dir()

    def _plan_user_value(self, *, key: str, value: str) -> EnvFileEditPlan:
        """Prepare one per-user dotenv edit without writing it."""
        try:
            return plan_env_file_value_update(
                path=self.kit.spec.user_dotenv_path(),
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                layer_name=self.kit.spec.user_dotenv_filename,
            )
        except (AppRCDirectoryError, OSError) as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc

    def _plan_storage_value(
        self,
        *,
        root: Path,
        key: str,
        value: str,
    ) -> EnvFileEditPlan:
        """Prepare one selected-storage dotenv edit without writing it."""
        try:
            return plan_storage_dotenv_value_update(
                storage_root=root,
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                storage_dotenv_filename=self.kit.spec.storage_dotenv_filename,
            )
        except (AppRCDirectoryError, OSError, StorageRootPathError) as exc:
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
    if scope == "user":
        return "The user dotenv layer is unavailable."
    return (
        "The storage dotenv layer is not active. Select a registered storage "
        f"with --storage or export {kit.spec.storage_selector_env_key}."
    )


def _is_interactive_terminal() -> bool:
    """Return whether duplicate cleanup can ask for confirmation."""
    return sys.stdin.isatty() and sys.stdout.isatty()
