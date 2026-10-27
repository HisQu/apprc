"""Runtime generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
import os
import sys

# == 3rd Party ===============================
import typer
from rich import print as rich_print

from apprc.interfaces.cli._typer_utils import dump_json
from apprc.interfaces.cli.config_command._base import ConfigCommandBase
from apprc.interfaces.cli.diagnostics.payload import build_config_doctor_payload
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus
from apprc.interfaces.cli.doctor_output import (
    print_config_doctor,
    print_config_paths,
)

# == Internal ================================
from apprc.services.manager import ConfigManager, WriteScope
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
    EnvFileUpdate,
)


class RuntimeConfigCommands(ConfigCommandBase):
    """Runtime config command implementations."""

    def paths(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show config-specific path readiness without writing files."""
        payload = build_config_doctor_payload(
            self.apprc,
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
        selector_context = self.cli_selector_context(ctx)
        workspace_root = self.active_workspace_root_for_cli(
            current_state,
            selector_context=selector_context,
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
                    workspace_root=workspace_root,
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
        """Inspect captured configuration layers without building app state."""
        payload = build_config_doctor_payload(
            self.apprc,
            manager=self.manager(ctx),
            config_group_name=self.config_group_name,
        )
        if json_output:
            dump_json(payload.to_payload())
        else:
            print_config_doctor(self.apprc, payload)
        if payload.status == ConfigDoctorStatus.ERROR.value:
            raise typer.Exit(code=1)

    def secrets_migrate(
        self, ctx: typer.Context, *, scope: str, assume_yes: bool
    ) -> None:
        """Move secret assignments into a private companion file."""
        selected = self._secret_scope(scope)
        manager = self.manager(ctx)
        try:
            plan = manager.plan_secret_migration(selected)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        if not plan.keys:
            typer.echo("No secret assignments need migration.")
            return
        typer.echo(
            f"Move {', '.join(plan.keys)} from {plan.ordinary_path.name} "
            f"to {plan.secret_path.name}?"
        )
        if not assume_yes and not typer.confirm("Apply this secret migration?"):
            typer.echo("No files were changed.")
            return
        try:
            manager.apply_secret_migration(plan)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--scope") from exc
        typer.echo("Secret assignments migrated.")

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
        allowed_principals = (
            "this user, SYSTEM, and Administrators"
            if os.name == "nt"
            else "the current user"
        )
        typer.echo(
            f"Update safety permissions for {status.path.parent} and "
            f"{status.path.name}. Allow access only to {allowed_principals}."
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
        if scope == "workspace" and self.apprc.schema.uses_workspaces():
            return "workspace"
        raise typer.BadParameter(
            "Choose an enabled user or workspace layer.", param_hint="--scope"
        )

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
