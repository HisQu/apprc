"""Read-only installation diagnostics and explicit saved recovery commands."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import typer
from apprc.interfaces.cli._typer_utils import click
from typer.core import TyperCommand

from apprc.definition.installation import (
    EditableCheckout,
    InstallationInspection,
    InstallationPlacement,
    MigrationPlan,
    OperationContext,
)
from apprc.interfaces.cli._editable_checkout import (
    _distribution_name,
    editable_entry_point,
)
from apprc.interfaces.cli.context import (
    InstallationCommandContext,
    installation_command_context_from,
)

if TYPE_CHECKING:
    from apprc.distribution.models import DistributionSpec


def _installation_error_message(error: BaseException) -> str:
    """Keep rollback outcome notes visible at the command's error boundary.

    :param error: Original installation error, including recovery notes.
    :return: Error and notes suitable for Typer's parameter error display.
    """
    return "\n".join((str(error), *getattr(error, "__notes__", ())))


class _InstallationCommand(TyperCommand):
    """Capture the invocation before Click consumes known installer options."""

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        ctx.meta["apprc.installation.arguments"] = tuple(args)
        return super().parse_args(ctx, args)


def update_command(
    ctx: typer.Context,
    assume_yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Apply the update without prompting."),
    ] = False,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview", help="Update the managed Preview installation."
        ),
    ] = False,
    release_tag: Annotated[
        str | None,
        typer.Option(
            "--release",
            metavar="TAG",
            help="Select a published release tag for a managed installation.",
        ),
    ] = None,
    release_version: Annotated[
        str | None,
        typer.Option(
            "--version",
            "-v",
            metavar="VERSION",
            help="Select a published package or Windows product version.",
        ),
    ] = None,
) -> None:
    """Update the registered release or editable checkout."""
    from zipfile import ZipFile

    from apprc.distribution.models import read_native_bindings
    from apprc.distribution.runtime._update_handoff import (
        EditableUpdateRetryError,
    )
    from apprc.distribution.runtime.update import update_application

    context = _inspection(ctx)
    binding = context.native_binding
    executable = context._native_manager_executable

    def confirm(message: str) -> None:
        if assume_yes:
            typer.echo(message)
        else:
            if not sys.stdin.isatty():
                raise click.ClickException(
                    f"{message} Rerun with --yes to apply the update."
                )
            if not typer.confirm(message, default=False):
                raise typer.Abort()

    try:
        regular_app_id = None
        expected_target = None
        manager = context.manager
        if preview and release_tag is not None and release_version is not None:
            raise click.ClickException("Choose either --version or --release.")
        if preview and binding is None:
            raise click.ClickException(
                "Run preview update through an installed managed command."
            )
        if binding is not None:
            from apprc.distribution.runtime._manager import (
                _owned_manager_invocation,
                _preview_update_target,
            )

            if executable is None or not _owned_manager_invocation(
                executable, context.manager, binding
            ):
                raise click.ClickException(
                    "Run update through the installed application command."
                )
            with ZipFile(executable) as archive:
                regular, preview_binding = read_native_bindings(archive)
            regular_app_id = regular.identity.app_id
            if preview:
                options = context.runtime_options
                if (
                    options.layout is not None
                    or options.env_files
                    or options.workspace is not None
                ):
                    raise click.ClickException(
                        "Preview uses fixed native application paths."
                    )
                manager, binding, expected_target = _preview_update_target(
                    regular, preview_binding, manager
                )
        group = (
            binding.maintenance_group_name
            if binding is not None
            else ctx.meta.get("apprc.update.maintenance_group", "app")
        )
        result = update_application(
            manager,
            binding=binding,
            regular_app_id=regular_app_id,
            maintenance_group=group,
            confirm=confirm,
            release_tag=release_tag,
            release_version=release_version,
            **(
                {"expected_target": expected_target}
                if expected_target is not None
                else {}
            ),
        )
    except EditableUpdateRetryError as error:
        # > Rich error panels wrap commands and add border characters.
        typer.echo(f"Error: {_installation_error_message(error)}", err=True)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise click.ClickException(
            _installation_error_message(error)
        ) from error
    if result:
        raise typer.Exit(result)


def mount_installation_group(
    app: typer.Typer,
    *,
    maintenance_group_name: str = "app",
    config_group_name: str = "config",
    installation_management: bool = False,
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
    checkout_installation: bool = False,
    preview_options: bool = False,
    native_management: bool = False,
) -> typer.Typer:
    """Register explicitly enabled installation actions on a maintenance group."""
    child = app
    if installer_entrypoint is not None and not callable(installer_entrypoint):
        raise TypeError("installer_entrypoint must be callable.")
    if installer_entrypoint is not None or installation_management:
        if checkout_installation:
            install_help = (
                "Install a Source Build (SB), building setup if needed, or "
                "register the current Editable Source Checkout (eSC) with -e.\n\n"
                "Reuse a verified, current setup for this platform. "
                "If setup is missing or stale, offer to build it from committed source."
            )
        elif installer_entrypoint is None:
            install_help = (
                "Register the current Editable Source Checkout (eSC) with -e."
            )
        elif installation_management:
            install_help = "Run the configured installer or register the current Editable Source Checkout (eSC) with -e."
        else:
            install_help = "Run the configured installer."

        if native_management:
            install_help += (
                "\n\nUse --preview --version VERSION or --preview --release TAG "
                "to install a published release into Preview."
            )

        @child.command(
            "install",
            help=install_help,
            cls=_InstallationCommand,
            context_settings={
                "allow_extra_args": True,
                "ignore_unknown_options": True,
            },
        )
        def install(
            ctx: typer.Context,
            editable: Annotated[
                bool,
                typer.Option(
                    "--editable",
                    "-e",
                    help="Register this checkout and its existing environment.",
                ),
            ] = False,
            command_directory: Annotated[
                Path | None,
                typer.Option(
                    "--command-directory",
                    help="Publish the command in an existing directory on PATH.",
                ),
            ] = None,
            assume_yes: Annotated[
                bool,
                typer.Option(
                    "--yes",
                    "-y",
                    help="Proceed without asking for confirmation.",
                ),
            ] = False,
            skip_setup: Annotated[
                bool,
                typer.Option(
                    "--skip-setup",
                    help="Skip the optional configuration setup prompt.",
                ),
            ] = False,
            desktop: Annotated[
                bool,
                typer.Option(
                    "--desktop",
                    help="Create a desktop shortcut without prompting.",
                ),
            ] = False,
            preview: bool = typer.Option(
                False,
                "--preview",
                "-p",
                hidden=not (preview_options or native_management),
                help="Install or update the preview and leave it installed.",
            ),
            smoke: bool = typer.Option(
                False,
                "--smoke",
                "-s",
                hidden=not preview_options,
                help="Install a fresh preview, verify its runtime, and uninstall it.",
            ),
            update_generation: str | None = typer.Option(
                None,
                "--apprc-update-generation",
                hidden=True,
                help="Expected installation generation for an update.",
            ),
            update_revision: str | None = typer.Option(
                None,
                "--apprc-update-revision",
                hidden=True,
                help="Expected installation revision for an update.",
            ),
        ) -> None:
            if (update_generation is None) != (update_revision is None) or (
                update_generation is not None and not editable
            ):
                raise typer.BadParameter("Invalid editable update authority.")
            try:
                expected_update = (
                    (UUID(update_generation), update_revision)
                    if update_generation is not None
                    and update_revision is not None
                    else None
                )
            except ValueError as error:
                raise typer.BadParameter(
                    "Invalid editable update generation."
                ) from error
            if (
                editable
                and native_management
                and any(
                    token.split("=", 1)[0] in {"--version", "-v", "--release"}
                    for token in ctx.args
                )
            ):
                raise typer.BadParameter(
                    "Release selection requires a managed preview install."
                )
            if editable and (preview or smoke):
                raise typer.BadParameter(
                    "--editable cannot be combined with --preview or --smoke."
                )
            if editable:
                if not installation_management:
                    raise typer.BadParameter(
                        "Editable installation requires AppRC installation management."
                    )
                from apprc.distribution.runtime._install_progress import (
                    InstallProgress,
                    installation_progress,
                )
                from apprc.interfaces.cli._installation_output import (
                    InstallationProgressOutput,
                )

                context = _inspection(ctx)
                output = InstallationProgressOutput(
                    ctx, context.manager.spec.display_name, "editable"
                )
                output(InstallProgress("stage", "Reusing Runtime"))
                try:
                    with installation_progress(output):
                        result = _register_editable(
                            ctx,
                            command_directory=command_directory,
                            assume_yes=assume_yes,
                            **(
                                {"expected_update": expected_update}
                                if expected_update is not None
                                else {}
                            ),
                        )
                except OSError as exc:
                    output.failed(_installation_error_message(exc))
                    raise typer.Exit(code=2) from exc
                except ValueError as exc:
                    raise typer.BadParameter(
                        _installation_error_message(exc)
                    ) from exc
                record = result.require_usable()
                if record is None or not isinstance(
                    record.active_runtime, EditableCheckout
                ):
                    raise click.ClickException(
                        "Installation did not return an editable checkout."
                    )
                try:
                    from apprc.distribution.runtime.installation.post_install import (
                        confirm_desktop_shortcut,
                        offer_configuration_setup,
                        publish_optional_shortcuts,
                    )

                    from apprc.interfaces._terminal_console import (
                        color_environment,
                    )

                    offer_configuration_setup(
                        result,
                        skip=skip_setup,
                        config_group_name=config_group_name,
                        runtime_options=context.runtime_options,
                        environment=color_environment(
                            context.environment, ctx.color
                        ),
                        raise_on_failure=True,
                    )
                except (OSError, subprocess.CalledProcessError) as exc:
                    output(
                        InstallProgress(
                            "warning",
                            f"The global command is available, but {record.command_name} {config_group_name} setup failed: {exc}\nRun `{record.command_name} {config_group_name} setup` to retry.",
                        )
                    )
                if desktop or (
                    context.inspection.record is None
                    and confirm_desktop_shortcut(
                        record.identity, assume_yes=assume_yes
                    )
                ):
                    command = next(
                        (
                            Path(item.path)
                            for item in reversed(record.owned_outputs)
                            if item.kind == "command"
                        ),
                        None,
                    )
                    if command is not None:
                        try:
                            with installation_progress(output):
                                publish_optional_shortcuts(
                                    context.manager,
                                    command,
                                    record.identity,
                                    display_name=context.manager.spec.display_name,
                                    start_menu=False,
                                    desktop=True,
                                    launch_enabled=False,
                                )
                        except (OSError, ValueError) as exc:
                            output(
                                InstallProgress(
                                    "warning",
                                    f"Optional shortcuts were not updated: {exc}",
                                )
                            )
                output.complete()
                return
            if installer_entrypoint is None:
                command = (
                    _inspection(ctx).manager.spec.command_name
                    or Path(sys.argv[0]).stem
                )
                raise typer.BadParameter(
                    "Managed installation requires the application's native setup "
                    f"executable. For an editable checkout, run `uv run --locked "
                    f"{command} {maintenance_group_name} install -e`."
                )
            arguments = tuple(
                token
                for token in ctx.meta["apprc.installation.arguments"]
                if token != "--"
            )
            if preview_options and (preview or smoke):
                # > Setup selects its identity before interpreting the remaining options.
                arguments = ("--smoke" if smoke else "--preview", *ctx.args)
                if command_directory is not None:
                    arguments += ("--command-directory", str(command_directory))
                if assume_yes:
                    arguments += ("--yes",)
                if skip_setup:
                    arguments += ("--skip-setup",)
                if desktop:
                    arguments += ("--desktop",)
            from apprc.distribution.runtime._install_progress import (
                installation_color_override,
            )

            with installation_color_override(ctx.color):
                status = installer_entrypoint(arguments)
            raise typer.Exit(code=status)

    @child.command("migrate")
    def migrate(
        ctx: typer.Context,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show the planned changes without applying them.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes", "-y", help="Proceed without asking for confirmation."
            ),
        ] = False,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit machine-readable JSON.")
        ] = False,
    ) -> None:
        """Preview or explicitly execute recognized AppRC placement migration."""
        from apprc.interfaces._terminal_console import cli_line, human_report
        from apprc.interfaces.cli._installation_output import (
            installation_inspection_payload,
            migration_payload,
            print_installation_result,
            print_migration_preview,
        )

        human = human_report(json_output)
        context = _inspection(ctx)
        manager = context.manager
        try:
            inspection = manager.inspect()
            record = inspection.record
            pending = (
                record
                if record is not None
                and record.operation is not None
                and record.operation.kind == "migrate"
                and record.migration is not None
                and inspection.revision is not None
                else None
            )
            if pending is not None:
                operation = pending.operation
                assert operation is not None and pending.migration is not None
                plan = MigrationPlan(
                    directory=inspection.directory,
                    expected_revision=inspection.revision,
                    expected_generation=pending.generation_id,
                    app_id=pending.identity.app_id,
                    operation_id=operation.operation_id,
                    generation_id=pending.generation_id,
                    placement=operation.placement,
                    inventory=pending.migration.inventory,
                    quiescent=True,
                    identity=pending.identity,
                    command_name=pending.command_name,
                )
            elif context.native_binding is None:
                plan = manager.preview_migration()
            else:
                plan = manager.preview_migration(
                    identity=context.native_binding.identity,
                    command_name=context.native_binding.command_name,
                )
            if human:
                print_migration_preview(ctx, plan)
            else:
                _emit(migration_payload(plan), json_output)
            if dry_run:
                return
            if not assume_yes and not sys.stdin.isatty():
                raise typer.BadParameter("Unattended migration requires --yes.")
            if not assume_yes and not typer.confirm(
                "Migration requires old application consumers to be stopped. Proceed?",
                default=False,
                err=json_output,
            ):
                raise typer.Abort()
            if human:
                cli_line(ctx, "1. Applying Migration", style="stage")
            migration_hook = _migration_bridge(context)
            if pending is not None:
                assert inspection.revision is not None
                result = manager.resume_migration(
                    operation_id=plan.operation_id,
                    expected_revision=inspection.revision,
                    migration_hook=migration_hook,
                )
            else:
                result = manager.migrate(
                    plan, quiescent=True, migration_hook=migration_hook
                )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        if human:
            print_installation_result(ctx, result, operation="Migration")
        else:
            _emit(installation_inspection_payload(result), json_output)

    def recover_runtime(
        ctx: typer.Context,
        assume_yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Apply managed runtime recovery."),
        ] = False,
    ) -> None:
        """Resume a pending managed installation or rebuild its saved runtime."""
        context = _inspection(ctx)
        binding = context.native_binding
        executable = context._native_manager_executable
        if binding is None or executable is None:
            raise click.ClickException(
                "Run runtime recovery through the installed native command or matching native setup."
            )
        from apprc.definition.installation import RuntimeSlot

        record = context.inspection.record
        revision = context.inspection.revision
        doctor = f"{binding.command_name} {maintenance_group_name} doctor"
        if (
            record is None
            or revision is None
            or record.identity != binding.identity
            or record.command_name != binding.command_name
        ):
            raise click.ClickException(
                f"Recovery requires a matching installation record. Run `{doctor}`."
            )
        operation = record.operation
        if operation is not None:
            if (
                operation.kind not in {"install", "replace", "repair"}
                or operation.intended is None
                or not isinstance(operation.intended.runtime, RuntimeSlot)
            ):
                raise click.ClickException(
                    f"The pending {operation.kind} operation has a separate recovery route. Run `{doctor}`."
                )
            prompt = f"Resume the saved managed {operation.kind} operation?"
        elif isinstance(record.active_runtime, EditableCheckout):
            raise click.ClickException(
                "To restore dependencies for this editable installation, run "
                f"`uv sync --locked` in {record.active_runtime.project}."
            )
        elif record.status == "ready" and isinstance(
            record.active_runtime, RuntimeSlot
        ):
            prompt = (
                "Rebuild the managed runtime from its saved project archive?"
            )
        else:
            raise click.ClickException(
                f"No managed runtime is available for recovery. Run `{doctor}`."
            )
        if not assume_yes:
            if not sys.stdin.isatty():
                raise click.ClickException(
                    f"{prompt} Add --yes to confirm runtime recovery."
                )
            if not typer.confirm(prompt, default=False):
                raise typer.Abort()

        from contextlib import nullcontext

        from apprc.distribution.runtime._install_progress import (
            InstallProgress,
            installation_progress,
        )
        from apprc.distribution.runtime._manager import _manager_uv
        from apprc.distribution.runtime.installation.managed import (
            repair_managed_installation,
        )
        from apprc.distribution.runtime.installation.transaction import (
            installation_maintenance_group,
        )
        from apprc.interfaces._terminal_console import human_report
        from apprc.interfaces.cli._installation_output import (
            InstallationProgressOutput,
            installation_inspection_payload,
            print_installation_result,
        )

        output = (
            InstallationProgressOutput(
                ctx, context.manager.spec.display_name, "recovery"
            )
            if human_report()
            else None
        )
        if output is not None:
            output(InstallProgress("stage", "Preparing Runtime"))
        try:
            with (
                installation_maintenance_group(maintenance_group_name),
                installation_progress(output)
                if output is not None
                else nullcontext(),
            ):
                result = repair_managed_installation(
                    context.manager,
                    manager_executable=executable,
                    uv=_manager_uv(),
                    expected_revision=revision,
                )
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ) as exc:
            raise click.ClickException(
                _installation_error_message(exc)
            ) from exc
        if output is None:
            _emit(installation_inspection_payload(result), False)
        elif result.status == "ready":
            output.complete()
        else:
            print_installation_result(ctx, result, operation="Runtime recovery")

    if native_management:
        child.command("recover-runtime")(recover_runtime)

    @child.command("uninstall")
    def uninstall(
        ctx: typer.Context,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show the planned changes without applying them.",
            ),
        ] = False,
        keep_config: Annotated[
            bool,
            typer.Option(
                "--keep-config",
                help="Keep the config directory, including saved settings and secrets.",
            ),
        ] = False,
        wait: Annotated[
            bool,
            typer.Option(
                "--wait",
                help="Keep the uninstall terminal visible until acknowledged.",
            ),
        ] = False,
        remove_repository: Annotated[
            bool,
            typer.Option(
                "--remove-repository",
                help="Also remove the recorded editable checkout after ownership checks.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes", "-y", help="Proceed without asking for confirmation."
            ),
        ] = False,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit machine-readable JSON.")
        ] = False,
    ) -> None:
        """Preview or remove the installation and selected application data."""
        from apprc.distribution.runtime import _uninstall_terminal
        from apprc.interfaces._terminal_console import cli_line

        wait = wait and not assume_yes and not dry_run
        result_window = (
            os.name == "nt" and not dry_run and (wait or sys.stdin.isatty())
        )
        closing_wait = wait or (result_window and not assume_yes)
        handed_off = False
        if wait:
            _uninstall_terminal.prepare()
        try:
            command_context = _inspection(ctx)
            inspection = command_context.inspection
            from apprc.distribution.runtime._uninstall_controller import (
                EXPECTED_UNINSTALL_REVISION,
            )

            expected_revision = command_context.environment.get(
                EXPECTED_UNINSTALL_REVISION
            )
            if (
                expected_revision is not None
                and inspection.revision != expected_revision
            ):
                raise typer.BadParameter(
                    "Installation changed since the guided test accepted its authority."
                )
            directory = inspection.directory
            record = inspection.record
            if (
                not dry_run
                and not assume_yes
                and not keep_config
                and sys.stdin.isatty()
                and record is not None
                and record.operation is None
                and record.placement.config_dir is not None
                and record.placement.config_dir.exists()
            ):
                from apprc.interfaces.cli._installation_output import (
                    print_installation_path,
                )

                print_installation_path(
                    ctx,
                    "User configuration",
                    record.placement.config_dir,
                    error=json_output,
                )
                keep_config = typer.confirm(
                    "Keep this configuration directory (settings and secrets)?",
                    default=True,
                    err=json_output,
                )
            try:
                from apprc.distribution.runtime import _uninstall_controller

                manager_executable = command_context._native_manager_executable
                preparation = _uninstall_controller.prepare_uninstall(
                    directory,
                    keep_config=True if keep_config else None,
                    remove_repository=remove_repository,
                    manager_executable=manager_executable,
                )
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            if (
                expected_revision is not None
                and preparation.inspection.revision != expected_revision
            ):
                raise typer.BadParameter(
                    "Installation changed before the guided uninstall preview."
                )
            if json_output:
                from apprc.interfaces.cli._installation_output import (
                    uninstall_preparation_payload,
                )

                _emit(uninstall_preparation_payload(preparation), True)
            else:
                from apprc.interfaces.cli._installation_output import (
                    installation_console,
                    uninstall_tree,
                )

                installation_console(ctx).print(uninstall_tree(preparation))
                for diagnostic in preparation.diagnostics:
                    cli_line(
                        ctx,
                        f"Cannot uninstall: {diagnostic.message} {diagnostic.recovery}",
                        style="error",
                        error=True,
                    )
            if dry_run:
                return
            if preparation.plan is None or not preparation.can_execute:
                raise typer.Exit(code=1)
            if not assume_yes and not sys.stdin.isatty():
                raise typer.BadParameter("Unattended removal requires --yes.")
            if not assume_yes:
                warning = _uninstall_controller.uninstall_activity_warning(
                    preparation
                )
                if warning is not None:
                    cli_line(ctx, warning, style="warning", error=True)
                if not typer.confirm(
                    f'Uninstall {command_context.manager.spec.display_name or command_context.manager.spec.app_id} and delete the items marked "Delete"?',
                    default=False,
                    err=json_output,
                ):
                    raise typer.Abort()

            try:
                handoff = _uninstall_controller.start_uninstall_handoff(
                    preparation.plan,
                    original_pid=os.getpid(),
                    wait=closing_wait,
                    result_window=result_window,
                    color=ctx.color,
                    manager_executable=command_context._native_manager_executable,
                )
                handoff.wait_ready()
                if result_window and not json_output:
                    typer.echo(
                        "Uninstall results will appear in a separate window."
                        + (
                            " Press Enter there to close it after cleanup."
                            if closing_wait
                            else ""
                        ),
                        err=True,
                    )
                handoff.signal_exit()
                handed_off = True
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            raise SystemExit(0)
        except BaseException as error:
            if wait and not handed_off:
                cli_line(
                    ctx,
                    f"Uninstall did not complete: {error}",
                    style="error",
                    error=True,
                )
                _uninstall_terminal.acknowledge()
            raise

    return child


def _migration_bridge(
    context: InstallationCommandContext,
) -> Callable[[MigrationPlan, OperationContext], None] | None:
    """Compose the recorded-runtime migration bridge outside installation core."""
    inspection = context.manager.inspect()
    record = inspection.record
    if record is None or record.active_runtime is None:
        return None
    runtime = record.active_runtime
    if not runtime.hooks.migrate:
        return None

    def invoke(plan: MigrationPlan, operation: OperationContext) -> None:
        from apprc.distribution.runtime.probe import application_bridge

        result = application_bridge(
            inspection.directory,
            record.identity,
            runtime,
            command_name=record.command_name,
            action="migrate",
            environment=dict(context.environment),
            manager_executable=context._native_manager_executable,
            expected_revision=plan.expected_revision,
            operation_context=operation,
            migration_plan=plan,
        )
        if result != {"completed": True}:
            raise ValueError("Migration hook did not report completion.")

    return invoke


def _register_editable(
    ctx: typer.Context,
    *,
    command_directory: Path | None,
    assume_yes: bool,
    expected_update: tuple[UUID, str] | None = None,
) -> InstallationInspection:
    """Validate the mounted command's existing editable uv checkout."""
    context = _inspection(ctx)
    if context.native_binding is not None:
        command = context.native_binding.command_name
    else:
        command = context.manager.spec.command_name or Path(sys.argv[0]).stem
    if not command:
        command = "<command>"
    maintenance_group = (
        context.native_binding.maintenance_group_name
        if context.native_binding is not None
        else ctx.parent.info_name
        if ctx.parent is not None and ctx.parent.info_name
        else "app"
    )
    guidance = (
        f"Run `uv run --locked {command} {maintenance_group} "
        "install -e` from the checkout."
    )
    project_root, prefix, distribution_spec = _validate_editable_checkout(
        context, command, guidance
    )
    placement = _editable_placement(
        context, distribution_spec, project_root, prefix, guidance
    )
    from apprc.distribution.runtime.installation.commands import (
        recorded_command_directory,
    )
    from apprc.distribution.runtime.installation.editable import (
        register_editable_application,
    )
    from apprc.distribution.runtime.installation.transaction import (
        require_update_record,
    )

    if expected_update is not None:
        previous = require_update_record(context.inspection, expected_update)
        command_directory = recorded_command_directory(
            previous, context.manager.directory
        )
        if command_directory is None:
            raise ValueError(
                "The editable installation has no recorded command location."
            )
    uv, command_directory = _editable_command_destination(
        context,
        project_root,
        prefix,
        command_directory,
        guidance,
        **({"recorded": True} if expected_update is not None else {}),
    )

    try:
        from apprc.distribution.runtime.installation.transaction import (
            installation_maintenance_group,
        )

        with installation_maintenance_group(maintenance_group):
            return register_editable_application(
                context.manager,
                distribution_spec.metadata.identity,
                EditableCheckout(
                    project=project_root,
                    environment=prefix,
                    hooks=distribution_spec.hooks,
                ),
                placement,
                command_name=command,
                uv=uv,
                command_directory=command_directory,
                assume_yes=assume_yes,
                **(
                    {"expected_update": expected_update}
                    if expected_update is not None
                    else {}
                ),
            )
    except OSError as exc:
        exc.add_note(guidance)
        raise
    except ValueError as exc:
        raise ValueError(
            f"{_installation_error_message(exc)} {guidance}"
        ) from exc


def _validate_editable_checkout(
    context: InstallationCommandContext,
    command: str,
    guidance: str,
) -> tuple[Path, Path, DistributionSpec]:
    """Authenticate installed checkout metadata and interpreter identity."""
    try:
        cwd = Path.cwd().resolve(strict=True)
        prefix = Path(sys.prefix).resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"Cannot access the current checkout or interpreter environment {sys.prefix}: "
            f"{exc}. {guidance}"
        ) from exc
    source_root: Path | None = None
    expected_environment: Path | None = None
    project_root: Path | None = None
    distribution_spec = None
    distribution = None
    try:
        from apprc.definition.resolution import resolve_editable_environment
        from apprc.distribution.metadata import read_distribution_spec

        record = context.inspection.record
        expected_identity = (
            context.native_binding.identity
            if context.native_binding is not None
            else record.identity
            if record is not None
            else None
        )
        installed_command, distribution, source_root = editable_entry_point(
            command,
            expected_identity.distribution
            if expected_identity is not None
            else None,
        )
        installed_name = _distribution_name(distribution.metadata["Name"])
        project_root = source_root.resolve(strict=True)
        distribution_spec = read_distribution_spec(project_root)
        identity = distribution_spec.metadata.identity
        if (
            installed_name != identity.distribution
            or distribution.version != distribution_spec.metadata.version
            or identity.app_id != context.manager.spec.app_id
            or command not in identity.commands
            or (expected_identity is not None and identity != expected_identity)
            or (
                context.native_binding is not None
                and distribution_spec.metadata.version
                != context.native_binding.version
            )
        ):
            raise ValueError(
                "The installed distribution differs from the mounted "
                "identity or version."
            )
        expected_environment = resolve_editable_environment(project_root)
        if not expected_environment.samefile(prefix):
            raise ValueError(
                "The selected checkout does not own the current interpreter. "
                f"Expected environment: {expected_environment}; "
                f"running environment: {prefix}."
            )
        if not any(
            ancestor.samefile(root)
            for ancestor in (cwd, *cwd.parents)
            for root in (project_root, expected_environment.parent)
        ):
            raise ValueError(
                "Run editable installation from the selected checkout or its "
                "workspace root."
            )
    except OSError as exc:
        source_description = (
            f"editable source {source_root}"
            if source_root is not None
            else "editable distribution metadata"
        )
        expected_description = (
            f"expected environment: {expected_environment}; "
            if expected_environment is not None
            else ""
        )
        raise ValueError(
            f"Cannot access {source_description}; {expected_description}"
            f"running environment: {prefix}. {exc}. {guidance}"
        ) from exc
    except (
        ValueError,
        KeyError,
        TypeError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        raise ValueError(f"{exc} {guidance}") from exc
    if (
        project_root is None
        or distribution_spec is None
        or distribution is None
    ):
        raise ValueError(
            "The installed console command does not identify an editable checkout. "
            f"{guidance}"
        )
    if not prefix.is_dir() or not (project_root / "pyproject.toml").is_file():
        raise ValueError(
            f"Checkout {project_root} or environment {prefix} is unavailable. {guidance}"
        )
    try:
        with (project_root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        scripts = project.get("scripts")
        primary = distribution_spec.metadata.command_name or (
            distribution_spec.metadata.identity.commands[0]
            if len(distribution_spec.metadata.identity.commands) == 1
            else None
        )
        if (
            not isinstance(scripts, dict)
            or primary != command
            or installed_command.value != scripts.get(command)
        ):
            raise ValueError(
                "The installed command entry point differs from checkout "
                "metadata."
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{exc} {guidance}") from exc
    executable = (
        prefix
        / ("Scripts" if os.name == "nt" else "bin")
        / (command + (".exe" if os.name == "nt" else ""))
    )
    if not executable.is_file():
        raise ValueError(
            f"Console command {command!r} is unavailable at {executable}. {guidance}"
        )

    return project_root, prefix, distribution_spec


def _editable_placement(
    context: InstallationCommandContext,
    distribution_spec: DistributionSpec,
    project_root: Path,
    prefix: Path,
    guidance: str,
) -> InstallationPlacement:
    """Resolve placement under the exact pending operation, if present."""
    from apprc.definition.resolution import ResolveOptions
    from apprc.user_files.app_home.layouts import resolve_app_paths

    options = context.runtime_options
    operation_context = None
    record = context.inspection.record
    if record is not None and record.operation is not None:
        operation = record.operation
        intended = operation.intended
        if (
            operation.kind not in {"install", "replace", "repair"}
            or intended is None
            or not isinstance(intended.runtime, EditableCheckout)
            or intended.identity != distribution_spec.metadata.identity
            or intended.runtime.project != project_root
            or intended.runtime.environment != prefix
            or intended.runtime.hooks != distribution_spec.hooks
        ):
            raise ValueError(
                "Pending installation addresses another operation or checkout. "
                f"{guidance}"
            )
        operation_context = OperationContext(
            directory=context.manager.directory,
            operation_id=operation.operation_id,
            generation_id=record.generation_id,
            placement=operation.placement,
        )
    paths = resolve_app_paths(
        context.manager.spec,
        ResolveOptions(
            env_files=options.env_files,
            env_file_overrides_os_environ=options.env_file_overrides_os_environ,
            load_dotenv_layers=options.load_dotenv_layers,
            workspace=options.workspace,
            layout=options.layout,
        ),
        context.environment,
        operation_context=operation_context,
    )
    return InstallationPlacement.from_paths(paths, context.manager.spec.paths)


def _editable_command_destination(
    context: InstallationCommandContext,
    project_root: Path,
    prefix: Path,
    command_directory: Path | None,
    guidance: str,
    *,
    recorded: bool = False,
) -> tuple[Path, Path]:
    """Select uv and an external existing command directory on PATH."""
    uv_name = shutil.which("uv", path=context.environment.get("PATH"))
    if uv_name is None:
        raise ValueError(f"uv is unavailable. {guidance}")
    uv = Path(uv_name).resolve()
    if command_directory is None:
        selected = subprocess.run(
            [str(uv), "tool", "dir", "--bin"],
            cwd=project_root,
            env=dict(context.environment),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        command_directory = Path(selected)
    if (
        not command_directory.is_absolute()
        or not command_directory.is_dir()
        or (
            not recorded
            and os.fspath(command_directory)
            not in context.environment.get("PATH", "").split(os.pathsep)
        )
    ):
        raise ValueError(
            "The command directory must be an absolute existing directory on PATH. "
            f"{guidance}"
        )
    selected_command_directory = command_directory.resolve()
    if (
        selected_command_directory.is_relative_to(project_root)
        or selected_command_directory.is_relative_to(prefix)
        or selected_command_directory.is_relative_to(prefix.parent)
    ):
        raise ValueError(
            "The command directory must be outside the checkout and .venv. "
            f"{guidance}"
        )
    return uv, command_directory


def installation_context(
    ctx: typer.Context,
) -> InstallationCommandContext | None:
    """Return diagnostic installation context without fabricating runtime paths."""
    return installation_command_context_from(ctx)


def _inspection(ctx: typer.Context) -> InstallationCommandContext:
    context = installation_context(ctx)
    if context is None:
        raise RuntimeError("Installation command context is not initialized.")
    return context


def _emit(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
