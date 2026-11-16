"""Read-only installation diagnostics and explicit saved recovery commands."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit
from urllib.request import url2pathname

import typer
from typer._click import Context as ClickContext
from typer.core import TyperCommand

from apprc.definition.installation import (
    EditableCheckout,
    InstallationInspection,
    InstallationRecord,
    InstallationPlacement,
    MigrationPlan,
    OperationContext,
    RuntimeSlot,
)
from apprc.interfaces.cli.context import (
    InstallationCommandContext,
    installation_command_context_from,
)

if TYPE_CHECKING:
    from apprc.distribution.models import DistributionSpec
    from apprc.distribution.runtime._uninstall_controller import (
        UninstallPreparation,
    )


def _installation_error_message(error: BaseException) -> str:
    """Keep rollback outcome notes visible at the command's error boundary.

    :param error: Original installation error, including recovery notes.
    :return: Error and notes suitable for Typer's parameter error display.
    """
    return "\n".join((str(error), *getattr(error, "__notes__", ())))


class _InstallationCommand(TyperCommand):
    """Capture the invocation before Click consumes known installer options."""

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        ctx.meta["apprc.installation.arguments"] = tuple(args)
        return super().parse_args(ctx, args)


def mount_installation_group(
    app: typer.Typer,
    *,
    maintenance_group_name: str = "app",
    config_group_name: str = "config",
    installation_management: bool = False,
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
) -> typer.Typer:
    """Register explicitly enabled installation actions on a maintenance group."""
    child = app
    if installer_entrypoint is not None and not callable(installer_entrypoint):
        raise TypeError("installer_entrypoint must be callable.")
    if installer_entrypoint is not None or installation_management:

        @child.command(
            "install",
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
        ) -> None:
            """Register the existing checkout or invoke an authored installer."""
            if editable:
                if not installation_management:
                    raise typer.BadParameter(
                        "Editable installation requires AppRC installation management."
                    )
                try:
                    result = _register_editable(
                        ctx,
                        command_directory=command_directory,
                        assume_yes=assume_yes,
                    )
                    from apprc.distribution.runtime.installation import (
                        offer_configuration_setup,
                    )

                    offer_configuration_setup(
                        result,
                        skip=skip_setup,
                        config_group_name=config_group_name,
                    )
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(
                        _installation_error_message(exc)
                    ) from exc
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
            raise typer.Exit(code=installer_entrypoint(arguments))

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
            _emit(_migration_payload(plan), json_output)
            if dry_run:
                return
            if not assume_yes and not sys.stdin.isatty():
                raise typer.BadParameter("Unattended migration requires --yes.")
            if not assume_yes and not typer.confirm(
                "Migration requires old application consumers to be stopped. Proceed?",
                default=False,
            ):
                raise typer.Abort()
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
        _emit(_inspection_payload(result), json_output)

    @child.command("repair")
    def repair(ctx: typer.Context) -> None:
        """Repair a managed runtime with its authenticated native manager."""
        context = _inspection(ctx)
        if (
            context.native_binding is None
            or context._native_manager_executable is None
        ):
            record = context.inspection.record
            if record is not None and isinstance(
                record.active_runtime, EditableCheckout
            ):
                raise typer.BadParameter(
                    "This editable environment is owned by Git and uv. "
                    "Restore it with `uv sync --locked` in the recorded checkout."
                )
            raise typer.BadParameter(
                "Managed repair requires the matching native setup executable. "
                "Run that setup executable to repair the installation."
            )
        try:
            from apprc.distribution.runtime._manager import _manager_uv
            from apprc.distribution.runtime.installation import (
                _repair_managed_application,
            )

            result = _repair_managed_application(
                context.manager,
                manager_executable=context._native_manager_executable,
                uv=_manager_uv(),
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(_installation_error_message(exc)) from exc
        _emit(_inspection_payload(result), False)

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
        keep_data: Annotated[
            bool,
            typer.Option(
                "--keep-data",
                help="Remove the program while retaining application data and configuration.",
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
        """Preview or remove the program and only explicitly selected owned data."""
        if keep_data and remove_repository:
            raise typer.BadParameter(
                "--keep-data cannot be combined with --remove-repository."
            )
        command_context = _inspection(ctx)
        inspection = command_context.inspection
        directory = inspection.directory
        try:
            from apprc.distribution.runtime import _uninstall_controller

            manager_executable = command_context._native_manager_executable
            preparation = _uninstall_controller.prepare_uninstall(
                directory,
                keep_data=True if keep_data else None,
                remove_repository=remove_repository,
                manager_executable=manager_executable,
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        payload = _preparation_payload(preparation)
        _emit(payload, json_output)
        if dry_run:
            return
        if preparation.plan is None or not preparation.can_execute:
            raise typer.Exit(code=1)
        if not assume_yes and not sys.stdin.isatty():
            raise typer.BadParameter("Unattended removal requires --yes.")
        if not assume_yes and not typer.confirm(
            "Remove the program and the exact owned targets shown above?",
            default=False,
        ):
            raise typer.Abort()

        try:
            handoff = _uninstall_controller.start_uninstall_handoff(
                preparation.plan,
                original_pid=os.getpid(),
                manager_executable=command_context._native_manager_executable,
            )
            handoff.wait_ready()
            handoff.signal_exit()
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        raise SystemExit(0)

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


def _editable_source_path(url: str) -> Path:
    """Decode an editable file URL without dropping a network authority.

    :param url: Installed distribution's direct source URL.
    :return: Absolute source path in the current platform's filesystem.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.query or parsed.fragment:
        raise ValueError(
            "Editable source must be a file URL without query or fragment."
        )
    path = parsed.path
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        if os.name != "nt":
            raise ValueError(
                f"Cannot convert editable source URL {url!r} to a local "
                "filesystem path on this platform. Use the network share's "
                "mounted local path."
            )
        path = f"//{parsed.netloc}{path}"
    try:
        source = Path(url2pathname(path))
    except OSError as exc:
        raise ValueError(
            f"Cannot convert editable source URL {url!r} to a filesystem path: {exc}"
        ) from exc
    if not source.is_absolute():
        raise ValueError(
            "Editable source file URL must identify an absolute path."
        )
    return source


def _register_editable(
    ctx: typer.Context,
    *,
    command_directory: Path | None,
    assume_yes: bool,
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
    uv, command_directory = _editable_command_destination(
        context, project_root, prefix, command_directory, guidance
    )
    from apprc.distribution.runtime.installation import (
        register_editable_application,
    )

    try:
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
        )
    except (OSError, ValueError) as exc:
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

        installed_commands = tuple(
            importlib.metadata.entry_points(
                group="console_scripts",
                name=command,
            )
        )
        record = context.inspection.record
        expected_identity = (
            context.native_binding.identity
            if context.native_binding is not None
            else record.identity
            if record is not None
            else None
        )
        if expected_identity is not None:
            installed_commands = tuple(
                entry
                for entry in installed_commands
                if entry.dist is not None
                and re.sub(r"[-_.]+", "-", entry.dist.metadata["Name"]).lower()
                == expected_identity.distribution
            )
        if len(installed_commands) != 1:
            raise ValueError(
                "The mounted console command does not identify one installed "
                "distribution."
            )
        installed_command = installed_commands[0]
        distribution = installed_command.dist
        if distribution is None:
            raise ValueError(
                "The mounted console command has no distribution owner."
            )
        installed_name = re.sub(
            r"[-_.]+", "-", distribution.metadata["Name"]
        ).lower()
        direct_url = distribution.read_text("direct_url.json")
        direct = json.loads(direct_url) if direct_url is not None else None
        source_root = (
            _editable_source_path(direct["url"])
            if isinstance(direct, dict) and isinstance(direct.get("url"), str)
            else None
        )
        if (
            source_root is None
            or not isinstance(direct, dict)
            or not isinstance(direct.get("dir_info"), dict)
            or direct["dir_info"].get("editable") is not True
        ):
            raise ValueError("The installed distribution is not editable.")
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
        or os.fspath(command_directory)
        not in context.environment.get("PATH", "").split(os.pathsep)
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


def _inspection_payload(
    inspection: InstallationInspection,
) -> dict[str, object]:
    return {
        "status": inspection.status,
        "app_id": inspection.app_id,
        "directory": str(inspection.directory),
        "revision": inspection.revision,
        "record": _record_payload(inspection.record),
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "recovery": item.recovery,
            }
            for item in inspection.diagnostics
        ],
    }


def _record_payload(
    record: InstallationRecord | None,
) -> dict[str, object] | None:
    if record is None:
        return None
    placement = record.placement
    return {
        "generation_id": str(record.generation_id),
        "identity": record.identity.app_id,
        "command_name": record.command_name,
        "status": record.status,
        "layout": placement.layout.mode,
        "root": str(placement.layout.root) if placement.layout.root else None,
        "capabilities": sorted(placement.capabilities),
        "active_runtime": (
            None
            if record.active_runtime is None
            else {
                "kind": (
                    "editable"
                    if isinstance(record.active_runtime, EditableCheckout)
                    else "managed"
                ),
                "distribution": record.identity.distribution,
                "version": (
                    record.active_runtime.version
                    if isinstance(record.active_runtime, RuntimeSlot)
                    else None
                ),
                "slot_id": (
                    str(record.active_runtime.slot_id)
                    if isinstance(record.active_runtime, RuntimeSlot)
                    else None
                ),
            }
        ),
        "retiring_runtime_ids": [
            str(slot_id) for slot_id in record.retiring_runtime_ids
        ],
        "operation": record.operation.kind if record.operation else None,
    }


def _migration_payload(plan: MigrationPlan) -> dict[str, object]:
    return {
        "directory": str(plan.directory),
        "source_root": str(plan.inventory.source_root),
        "destination_root": str(plan.inventory.destination_root),
        "entries": [str(item.path) for item in plan.inventory.entries],
        "unknown": [str(path) for path in plan.inventory.unknown],
        "quiescent_required": True,
    }


def _preparation_payload(
    preparation: UninstallPreparation,
) -> dict[str, object]:
    record = preparation.inspection.record
    retained: list[dict[str, str]] = []
    if record is not None:
        if preparation.plan is not None and not preparation.plan.complete:
            from apprc.user_files.installation.planning import resource_roots

            retained.extend(
                {"path": str(path), "reason": "--keep-data"}
                for _, path in resource_roots(record.placement)
            )
        if isinstance(record.active_runtime, EditableCheckout) and not any(
            entry.kind == "repository" for entry in preparation.entries
        ):
            retained.extend(
                {"path": str(path), "reason": "editable installation"}
                for path in (
                    record.active_runtime.project,
                    record.active_runtime.environment,
                )
            )
    return {
        "preserved": retained,
        "inspection": _inspection_payload(preparation.inspection),
        "can_execute": preparation.can_execute,
        "entries": [
            {
                "path": str(entry.path),
                "kind": entry.kind,
                "resource": entry.resource,
            }
            for entry in preparation.entries
        ],
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "recovery": item.recovery,
            }
            for item in preparation.diagnostics
        ],
    }


def _emit(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
