"""Runtime generated config command handlers."""

from __future__ import annotations


# == Standard Library ========================
import sys
from pathlib import Path
from dataclasses import replace

# == 3rd Party ===============================
import typer
from rich import print as rich_print

# == Internal ================================
from apprc.services.manager import ConfigManager, WriteScope
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
)
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)
from apprc.interfaces.cli._typer_utils import dump_json
from apprc.interfaces.cli._interactive_setup import (
    prompt_storage_migration_choice,
    prompt_storage_migration_root,
)
from apprc.interfaces.cli.diagnostics.payload import build_config_doctor_payload
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
    EnvFileUpdate,
)
from apprc.user_files.migration import (
    ConfigMigrationPlan,
    ConfigMigrationResult,
    ConfigMigrationError,
    StorageMigrationResolution,
    UnresolvedStorageMigrationError,
)
from apprc.user_files.purge import (
    ConfigPurgeError,
)


class RuntimeConfigCommands(ConfigCommandBase):
    """Runtime config command implementations."""

    def paths(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show declared and active config paths without writing files."""
        storage = self.cli_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.apprc,
            storage=storage_selector,
            manager=self.manager(ctx),
            config_group_name=self.config_group_name,
        )
        if json_output:
            dump_json(payload.to_payload())
            return
        print_config_paths(self.apprc, payload)

    def show(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show the resolved runtime config available to this CLI run."""
        current_state = self.resolved_config_state(ctx)
        storage_root = (
            self.active_storage_root_for_cli(current_state)
            if current_state is not None
            else None
        )
        try:
            if self.runtime_payload is not None:
                payload_state = self.runtime_payload_state(current_state)
                if payload_state is None:
                    raise RuntimeError("CLI state is not initialized.")
                payload = self.runtime_payload(payload_state)
            else:
                context = self.context_state(ctx)
                resolved = context.resolved if context is not None else None
                payload = self.default_runtime_payload(
                    storage_root=storage_root,
                    resolved=resolved
                    if resolved is not None
                    else self.manager(ctx).resolve(),
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
        storage = self.cli_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.apprc,
            storage=storage_selector,
            manager=self.manager(ctx),
            config_group_name=self.config_group_name,
        )
        if json_output:
            dump_json(payload.to_payload())
        else:
            print_config_doctor(self.apprc, payload)
        if payload.status != ConfigDoctorStatus.RUNNABLE.value:
            raise typer.Exit(code=1)

    def secrets_migrate(
        self, ctx: typer.Context, *, scope: str, assume_yes: bool
    ) -> None:
        """Show and optionally apply a value-free legacy-secret move."""
        selected = self._secret_scope(scope)
        manager = self.manager(ctx)
        try:
            plan = manager.plan_secret_migration(selected)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        if not plan.keys:
            typer.echo("No legacy secret assignments need migration.")
            return
        typer.echo(
            f"Move {len(plan.keys)} secret field(s) from {plan.ordinary_path.name} to {plan.secret_path.name}:"
        )
        for key in plan.keys:
            typer.echo(f"  {key}")
        if not assume_yes and not typer.confirm("Move these assignments?"):
            typer.echo("No files were changed.")
            return
        try:
            manager.apply_secret_migration(plan)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        typer.echo(f"migrated_secret_fields: {len(plan.keys)}")

    def secrets_repair(
        self, ctx: typer.Context, *, scope: str, assume_yes: bool
    ) -> None:
        """Repair a reviewed layer directory and companion permission set."""
        selected = self._secret_scope(scope)
        manager = self.manager(ctx)
        try:
            status = manager.secret_status(selected)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        if status.available and status.path.is_file():
            typer.echo("Secret file permissions are already private.")
            return
        typer.echo(
            f"Restrict access to {status.path.parent} and {status.path.name}."
        )
        if not assume_yes and not typer.confirm(
            "Apply this permission repair?"
        ):
            typer.echo("No files were changed.")
            return
        try:
            result = manager.repair_secret_permissions(selected)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        if not result.available:
            raise typer.BadParameter(
                result.issue or "Secret file is unavailable.",
                param_hint="--scope",
            )
        typer.echo("Secret file permissions repaired.")

    def _secret_scope(self, scope: str) -> WriteScope:
        """Require one of the layer names declared by this AppRC."""
        if scope == "user" and self.apprc.schema.uses_user_dotenv():
            return "user"
        if scope == "storage" and self.apprc.schema.uses_storage():
            return "storage"
        raise typer.BadParameter(
            "Choose an enabled user or storage layer.", param_hint="--scope"
        )

    def migrate(
        self,
        ctx: typer.Context,
        *,
        dry_run: bool,
        assume_yes: bool,
        storage_root: Path | None = None,
        replace_storage: str | None = None,
    ) -> None:
        """Move legacy AppRC-managed files to current filenames."""
        plan = self._migration_plan(
            ctx,
            assume_yes=assume_yes,
            storage_root=storage_root,
            replace_storage=replace_storage,
        )
        self._reject_migration_conflicts(plan)
        if not plan.moves and not plan.writes:
            typer.echo("No released AppRC 0.19 files need migration.")
            for warning in plan.warnings:
                typer.echo(f"warning: {warning}", err=True)
            return
        self._print_migration_moves(plan, dry_run=dry_run)
        if dry_run:
            return
        if not assume_yes and not typer.confirm("Apply this migration plan?"):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        result = self._apply_migration_plan(plan, manager=self.manager(ctx))
        typer.echo(f"migrated_files: {len(result.moved) + len(result.written)}")
        for warning in plan.warnings:
            typer.echo(f"warning: {warning}", err=True)

    def purge(
        self,
        ctx: typer.Context,
        *,
        apprc_dir: Path | None,
        dry_run: bool,
        assume_yes: bool,
    ) -> None:
        """Remove only fixed AppRC files and registered internal storage."""
        try:
            manager = self.manager(ctx)
            if apprc_dir is not None:
                manager = self.apprc.manage(
                    replace(manager.options, apprc_dir=apprc_dir),
                    environment=manager.environment,
                )
            plan = manager.plan_purge()
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
        if plan.stale_user_dotenv:
            typer.echo(
                "warning: apprc.user.env exists for an app that no longer "
                "declares user-dotenv support.",
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
            result = manager.apply_purge(plan)
        except OSError as exc:
            raise typer.BadParameter(str(exc), param_hint="purge") from exc
        typer.echo(f"removed_entries: {len(result.removed)}")
        for path in result.skipped:
            typer.echo(f"skipped_unsafe_target: {path}", err=True)
        if plan.apprc_dir.exists():
            typer.echo(
                "remaining_unmanaged_data: "
                f"{plan.apprc_dir} was kept because it is not empty.",
                err=True,
            )

    def _migration_plan(
        self,
        ctx: typer.Context,
        *,
        assume_yes: bool,
        storage_root: Path | None,
        replace_storage: str | None,
    ) -> ConfigMigrationPlan:
        """Build a migration plan from every CLI-visible storage root.

        :param ctx: Active Typer context.
        :param assume_yes: Whether migration must avoid interactive choices.
        :param storage_root: Explicit directory for an unresolved selector.
        :param replace_storage: Existing entry to rename and repoint.
        :return: Conflict and move inventory.
        """
        if replace_storage is not None and storage_root is None:
            raise typer.BadParameter(
                "--replace-storage requires --storage-root.",
                param_hint="--replace-storage",
            )
        selector_context = self.cli_selector_context(ctx)
        try:
            plan = self.manager(ctx).plan_migration(
                storage_roots=self._migration_storage_roots(selector_context),
            )
        except UnresolvedStorageMigrationError as exc:
            resolution = self._migration_storage_resolution(
                exc,
                assume_yes=assume_yes,
                storage_root=storage_root,
                replace_storage=replace_storage,
            )
            try:
                return self.manager(ctx).plan_migration(
                    storage_roots=self._migration_storage_roots(
                        selector_context
                    ),
                    storage_resolution=resolution,
                )
            except ConfigMigrationError as resolved_exc:
                raise typer.BadParameter(
                    str(resolved_exc),
                    param_hint="migrate",
                ) from resolved_exc
        except ConfigMigrationError as exc:
            raise typer.BadParameter(str(exc), param_hint="migrate") from exc
        if storage_root is not None or replace_storage is not None:
            raise typer.BadParameter(
                "--storage-root and --replace-storage are used only when a "
                "bare storage selector is not registered.",
                param_hint="migrate",
            )
        return plan

    def _migration_storage_resolution(
        self,
        error: UnresolvedStorageMigrationError,
        *,
        assume_yes: bool,
        storage_root: Path | None,
        replace_storage: str | None,
    ) -> StorageMigrationResolution:
        """Resolve an unknown migration selector without guessing intent.

        :param error: Typed preflight failure with selector and registry.
        :param assume_yes: Whether migration must avoid interactive choices.
        :param storage_root: Optional non-interactive directory mapping.
        :param replace_storage: Optional existing entry to replace.
        :return: Explicit mapping used for the second migration preflight.
        """
        selected_root = storage_root
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        if selected_root is None:
            if not interactive:
                command = self.config_command_text(
                    "migrate --storage-root "
                    f"/absolute/path/to/{error.selector_name} --yes"
                )
                replacement = ""
                if error.registry.storages:
                    replacement = (
                        " If this directory replaces a registered storage, "
                        "add `--replace-storage OLD_NAME`."
                    )
                typer.echo(f"Recovery command: {command}", err=True)
                raise typer.BadParameter(
                    f"{error}{replacement}",
                    param_hint="--storage-root",
                )
            selected_root = prompt_storage_migration_root(
                selector_name=error.selector_name
            )
            if selected_root is None:
                typer.echo("No files were changed.", err=True)
                raise typer.Exit(code=1)

        resolved_root = selected_root.expanduser().resolve()
        if not resolved_root.is_dir():
            raise typer.BadParameter(
                "Migration storage root does not exist or is not a directory: "
                f"{resolved_root}",
                param_hint="--storage-root",
            )

        selected_replacement = replace_storage
        if selected_replacement is None and interactive and not assume_yes:
            choice = prompt_storage_migration_choice(
                selector_name=error.selector_name,
                storage_root=resolved_root,
                registry=error.registry,
            )
            if choice is None:
                typer.echo("No files were changed.", err=True)
                raise typer.Exit(code=1)
            _, selected_replacement = choice
        return StorageMigrationResolution(
            root=resolved_root,
            replace_storage=selected_replacement,
        )

    def _migration_storage_roots(
        self,
        selector_context: ConfigSelectorContext,
    ) -> tuple[Path, ...]:
        """Return registered and active roots visible to migration.

        :param selector_context: Explicit CLI selector inputs.
        :return: Storage roots whose managed files should be considered.
        """
        if not self.apprc.schema.uses_storage():
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
        mapping = plan.storage_mapping
        if mapping is not None:
            action = "replace" if mapping.replaced_storage else "register"
            label = f"would_{action}" if dry_run else action
            if mapping.replaced_storage is None:
                typer.echo(
                    f"{label}: {mapping.selector_name} -> {mapping.root}"
                )
            else:
                typer.echo(
                    f"{label}: {mapping.replaced_storage} -> "
                    f"{mapping.selector_name} at {mapping.root}"
                )
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
        *,
        manager: ConfigManager,
    ) -> ConfigMigrationResult:
        """Apply a migration plan and render any partial failure.

        :param plan: Confirmed migration inventory.
        :return: Completed move result.
        """
        try:
            return manager.apply_migration(plan)
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
        manager = self.manager(ctx)
        try:
            resolved_scope = manager.resolve_write_scope(scope)
            plan = manager.plan_update(key, value, scope=resolved_scope)
            update = self._confirm_and_apply_env_file_edit(
                plan, manager=manager
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(
                str(exc), param_hint="--scope / KEY"
            ) from exc
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"{resolved_scope}_dotenv: {update.path}")
        self._print_post_write_warnings(plan)

    @staticmethod
    def _confirm_and_apply_env_file_edit(
        plan: EnvFileEditPlan,
        *,
        manager: ConfigManager,
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
        return manager.apply_edit(plan)

    @staticmethod
    def _print_post_write_warnings(plan: EnvFileEditPlan) -> None:
        """Print warnings after a non-interactive dotenv write.

        :param plan: Applied edit whose warnings may need output.
        """
        if _is_interactive_terminal():
            return
        for warning in plan.warnings:
            typer.echo(f"Warning: {warning}", err=True)


def _is_interactive_terminal() -> bool:
    """Return whether duplicate cleanup can ask for confirmation."""
    return sys.stdin.isatty() and sys.stdout.isatty()
