"""Fixed Typer commands for AppRC paths and resource maintenance."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping, Sequence
import json
import sys
from typing import Annotated, Callable, Literal, cast
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.installation import EditableCheckout
from apprc.definition.maintenance import (
    MaintenanceHandlers,
    RemovalPlan,
    RemovalResult,
)
from apprc.definition.paths import ResourceKind
from apprc.interfaces.cli.installation_command import (
    installation_context,
    mount_installation_group,
)
from apprc.public.app_rc import AppRC
from apprc.services.maintenance import (
    MaintenanceManager,
    _MaintenanceApplyError,
)
from apprc.services.workspaces import WorkspaceManager
from apprc.interfaces.cli._root_help import _AppRCMaintenanceGroup
from apprc.user_files.workspace_roots._loading import (
    WorkspaceRegistryInspection,
)
from apprc.interfaces.cli.doctor_output import print_doctor_report

from apprc.interfaces.cli.diagnostics.application import (
    build_application_doctor_payload,
    _validate_native_runtime_observations,
    _context,
    _options,
    _locations,
    _paths_payload,
    _declared,
)

_CATEGORIES = ("config", "appdata", "cache", "state", "logs")


def mount_maintenance_groups(
    app: typer.Typer,
    apprc: AppRC,
    *,
    handlers: MaintenanceHandlers = MaintenanceHandlers(),
    maintenance_help_panel: str = "AppRC: Commands",
    maintenance_group_name: str = "app",
    config_group_name: str = "config",
    installation_management: bool = False,
    host_diagnostics: Callable[[], Mapping[str, object]] | None = None,
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
    checkout_installation: bool = False,
    preview_options: bool = False,
    native_management: bool = False,
    resource_diagnostics: Mapping[
        Literal["appdata", "cache", "state"],
        Callable[[Path], Mapping[str, object]],
    ]
    | None = None,
    resource_group_extensions: Mapping[
        Literal["appdata", "cache", "state"], Callable[[typer.Typer], None]
    ]
    | None = None,
) -> dict[str, typer.Typer]:
    """Build the configured maintenance subtree and optional workspace group."""
    declared = {
        kind
        for kind in ("appdata", "cache", "state")
        if _declared(apprc, cast(ResourceKind, kind))
    }
    for label, registration in (
        ("resource_diagnostics", resource_diagnostics or {}),
        ("resource_group_extensions", resource_group_extensions or {}),
    ):
        invalid = set(registration) - declared
        if invalid:
            raise ValueError(
                f"{label} names undeclared resources: "
                + ", ".join(sorted(invalid))
            )
    maintenance = typer.Typer(
        cls=_AppRCMaintenanceGroup,
        help="Inspect and maintain the application.",
    )
    mounted: dict[str, typer.Typer] = {maintenance_group_name: maintenance}
    resource_groups: dict[
        Literal["appdata", "cache", "state"], typer.Typer
    ] = {}
    mount_installation_group(
        maintenance,
        maintenance_group_name=maintenance_group_name,
        config_group_name=config_group_name,
        installation_management=installation_management,
        installer_entrypoint=installer_entrypoint,
        checkout_installation=checkout_installation,
        preview_options=preview_options,
        native_management=native_management,
    )

    @maintenance.command("paths", rich_help_panel=maintenance_help_panel)
    def paths_command(
        ctx: typer.Context,
        category: Annotated[
            str | None,
            typer.Argument(
                help="Select config, appdata, cache, state, or logs; omit to show all locations."
            ),
        ] = None,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit machine-readable JSON.")
        ] = False,
        open_path: Annotated[
            bool,
            typer.Option(
                "--open",
                help="Open the selected directory; requires a category and cannot be combined with --json.",
            ),
        ] = False,
    ) -> None:
        """Show selected AppRC locations without creating them."""
        from apprc.interfaces._terminal_console import cli_console, cli_line
        from apprc.interfaces._terminal_styles import path_text
        from rich.text import Text

        try:
            runtime = _context(ctx)
        except RuntimeError:
            diagnostic = installation_context(ctx)
            if diagnostic is not None and diagnostic.path_error is not None:
                raise typer.BadParameter(diagnostic.path_error)
            raise
        if category is not None and category not in _CATEGORIES:
            raise typer.BadParameter(f"Unknown path category: {category}")
        if open_path and (category is None or json_output):
            raise typer.BadParameter(
                "--open requires a category and cannot be combined with --json."
            )
        if category is not None:
            try:
                path = runtime.paths.require(category)  # type: ignore[arg-type]
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            exists = path.is_dir()
            if json_output:
                _emit(
                    {"category": category, "path": str(path), "exists": exists},
                    True,
                )
            else:
                cli_line(ctx, "", path=path)
            if open_path:
                if not exists:
                    raise typer.BadParameter(
                        f"Directory does not exist: {path}"
                    )
                typer.launch(str(path))
            return
        payload = _paths_payload(runtime)
        if json_output:
            _emit(payload, True)
        else:
            typer.echo(f"layout: {payload['layout']}")
            root = payload["root"]
            if isinstance(root, str):
                cli_line(ctx, "root", path=root)
            else:
                typer.echo("root: (native)")
            typer.echo(f"source: {payload['source']}")
            exists = cast(dict[str, bool | None], payload["exists"])
            console = cli_console(ctx)
            for key, path in _locations(runtime).items():
                if path is not None:
                    console.print(
                        Text.assemble(
                            f"{key}: ",
                            path_text(path),
                            f" (exists: {exists[key]})",
                        )
                    )

    @maintenance.command("doctor", rich_help_panel=maintenance_help_panel)
    def doctor_command(
        ctx: typer.Context,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                help="Include detailed configuration and runtime diagnostics.",
            ),
        ] = False,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit machine-readable JSON.")
        ] = False,
    ) -> None:
        """Check installation authority, paths, and declared configuration."""
        payload = build_application_doctor_payload(
            ctx,
            apprc,
            maintenance_group_name=maintenance_group_name,
            verbose=verbose,
            host_diagnostics=host_diagnostics,
            resource_diagnostics=resource_diagnostics or {},
            resource_groups=resource_groups,
        )
        diagnostic = installation_context(ctx)
        if diagnostic is not None and diagnostic.native_binding is not None:
            record = diagnostic.inspection.record
            if record is None or record.active_runtime is None:
                cast(list[object], payload["checks"]).extend(
                    [
                        {
                            "name": "runtime_health",
                            "status": "error",
                            "message": "No active runtime is available to probe.",
                        },
                        {
                            "name": "application_runtime",
                            "status": "warning",
                            "message": "Application checks are unavailable because no runtime is active.",
                        },
                    ]
                )
                payload["status"] = "error"
            else:
                from apprc.distribution.runtime.probe import application_bridge

                manager_executable = diagnostic._native_manager_executable
                try:
                    observations = application_bridge(
                        diagnostic.inspection.directory,
                        record.identity,
                        record.active_runtime,
                        command_name=record.command_name,
                        action="probe",
                        environment=dict(diagnostic.environment),
                        manager_executable=manager_executable,
                        expected_revision=diagnostic.inspection.revision,
                    )
                    _validate_native_runtime_observations(
                        observations,
                        directory=diagnostic.inspection.directory,
                        identity=record.identity,
                        runtime=record.active_runtime,
                        command_name=record.command_name,
                    )
                    cast(list[object], payload["checks"]).append(
                        {
                            "name": "runtime_health",
                            "status": "ok",
                            "message": (
                                "The active interpreter, distribution, and "
                                "declared console commands match installation authority."
                            ),
                        }
                    )
                    if verbose:
                        details = cast(dict[str, object], payload["details"])
                        host = cast(dict[str, object], details["host"])
                        host["runtime"] = observations
                except (OSError, ValueError) as exc:
                    message = f"Active runtime probe failed: {exc}"
                    if record.operation is None:
                        if isinstance(record.active_runtime, EditableCheckout):
                            message += (
                                " To restore dependencies, run `uv sync --locked` "
                                f"in {record.active_runtime.project}."
                            )
                        else:
                            message += (
                                f" Run `{record.command_name} {maintenance_group_name} "
                                "recover-runtime` to rebuild the managed runtime."
                            )
                    cast(list[object], payload["checks"]).extend(
                        [
                            {
                                "name": "runtime_health",
                                "status": "error",
                                "message": message,
                            },
                            {
                                "name": "application_runtime",
                                "status": "warning",
                                "message": "Application checks are unavailable because the active runtime probe failed.",
                            },
                        ]
                    )
                    payload["status"] = "error"
                else:
                    try:
                        from apprc.interfaces.cli.context import (
                            _cli_runtime_options_payload,
                        )

                        application = application_bridge(
                            diagnostic.inspection.directory,
                            record.identity,
                            record.active_runtime,
                            command_name=record.command_name,
                            action="doctor",
                            environment=dict(diagnostic.environment),
                            manager_executable=manager_executable,
                            expected_revision=diagnostic.inspection.revision,
                            runtime_options=_cli_runtime_options_payload(
                                diagnostic.runtime_options,
                                maintenance_group_name,
                            ),
                        )
                        app_checks = application.get("checks", [])
                        if isinstance(app_checks, list):
                            cast(list[object], payload["checks"]).extend(
                                app_checks
                            )
                        app_details = application.get("details", {})
                        if verbose and isinstance(app_details, dict):
                            details = cast(
                                dict[str, object], payload["details"]
                            )
                            configuration = app_details.get("configuration")
                            if configuration is not None:
                                details["configuration"] = configuration
                            resource_details = app_details.get("resources", {})
                            resources = cast(
                                dict[str, object], details["resources"]
                            )
                            if isinstance(resource_details, dict):
                                for kind, provider in resource_details.items():
                                    resource = resources.get(kind)
                                    if isinstance(resource, dict):
                                        resource["provider"] = provider
                            host_details = app_details.get("host", {})
                            host = cast(dict[str, object], details["host"])
                            if isinstance(host_details, dict):
                                host.update(host_details)
                        if application.get("status") in {
                            "error",
                            "invalid",
                            "provisional",
                            "incomplete",
                        }:
                            payload["status"] = "error"
                        elif (
                            application.get("status") == "warning"
                            and payload["status"] == "ok"
                        ):
                            payload["status"] = "warning"
                    except (OSError, ValueError) as exc:
                        cast(list[object], payload["checks"]).append(
                            {
                                "name": "application_runtime",
                                "status": "warning",
                                "message": f"Application checks are unavailable: {exc}",
                            }
                        )
                        if payload["status"] == "ok":
                            payload["status"] = "warning"
            if diagnostic.inspection.status in {
                "invalid",
                "provisional",
                "incomplete",
            }:
                payload["status"] = diagnostic.inspection.status
        if json_output:
            _emit(payload, True)
        else:
            print_doctor_report(payload, ctx=ctx)
        if payload["status"] in {
            "error",
            "invalid",
            "provisional",
            "incomplete",
        }:
            raise typer.Exit(code=1)

    resource_kinds: tuple[Literal["appdata", "cache", "state"], ...] = (
        "appdata",
        "cache",
        "state",
    )
    for kind in resource_kinds:
        if not _declared(apprc, kind):
            continue
        child = _resource_group(apprc, handlers, kind)
        extension = (resource_group_extensions or {}).get(kind)
        if extension is not None:
            extension(child)
        if not child.registered_commands and not child.registered_groups:
            continue
        resource_groups[kind] = child
        group_name = "data" if kind == "appdata" else kind
        maintenance.add_typer(
            child, name=group_name, rich_help_panel=maintenance_help_panel
        )
        mounted[f"{maintenance_group_name}.{group_name}"] = child
    if apprc.schema.workspaces is not None:
        workspace = _workspace_group(apprc)
        declaration = apprc.schema.require_workspaces()
        app.add_typer(
            workspace,
            name="workspace",
            short_help=(
                "Register, select, move, archive, or restore workspaces."
                if declaration.registry
                else "Inspect a workspace path or initialize it explicitly."
            ),
            rich_help_panel=maintenance_help_panel,
        )
        mounted["workspace"] = workspace
    order = {
        name: index
        for index, name in enumerate(
            (
                "doctor",
                "paths",
                "install",
                "recover-runtime",
                "uninstall",
                "migrate",
            )
        )
    }
    maintenance.registered_commands.sort(
        key=lambda command: order.get(
            command.name or "",
            len(order),
        )
    )
    app.add_typer(
        maintenance,
        name=maintenance_group_name,
        rich_help_panel=maintenance_help_panel,
    )
    return mounted


def _resource_group(
    apprc: AppRC,
    handlers: MaintenanceHandlers,
    kind: ResourceKind,
) -> typer.Typer:
    """Build only operations explicitly declared for a resource."""
    child = typer.Typer(help=f"Maintain AppRC {kind}.")
    if kind == "appdata":
        provider = handlers.appdata
        if provider is not None and provider.backup is not None:

            @child.command("backup")
            def backup_command(
                ctx: typer.Context,
                destination: Annotated[
                    Path,
                    typer.Argument(
                        help="Destination for the application data backup."
                    ),
                ],
            ) -> None:
                """Create an application-owned AppData backup."""
                try:
                    path = _manager(ctx, apprc, handlers).backup_appdata(
                        destination
                    )
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
                from apprc.interfaces._terminal_console import (
                    cli_line,
                    human_report,
                )

                cli_line(
                    ctx,
                    "Backup saved" if human_report() else "",
                    path=path,
                    style="success",
                )

        if provider is not None and provider.restore is not None:

            @child.command("restore")
            def restore_command(
                ctx: typer.Context,
                source: Annotated[
                    Path,
                    typer.Argument(help="Application data backup to restore."),
                ],
                assume_yes: Annotated[
                    bool,
                    typer.Option(
                        "--yes",
                        "-y",
                        help="Proceed without asking for confirmation.",
                    ),
                ] = False,
            ) -> None:
                """Restore an application-owned AppData backup."""
                from apprc.interfaces._terminal_console import (
                    cli_line,
                    human_report,
                )

                human = human_report()
                if human and not assume_yes:
                    cli_line(ctx, "Backup to restore", path=source)
                if not assume_yes and not typer.confirm(
                    "Restore AppData from this backup?"
                    if human
                    else f"Restore AppData from {source}?"
                ):
                    raise typer.Exit(code=1)
                if human:
                    cli_line(
                        ctx, "1. Restoring Application Data", style="stage"
                    )
                try:
                    _manager(ctx, apprc, handlers).restore_appdata(source)
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
                if human:
                    cli_line(ctx, "Application data restored.", style="success")
    elif kind == "cache":
        provider = handlers.cache
        if provider is not None and provider.prune is not None:
            _add_operation_commands(child, apprc, handlers, "cache", "prune")
        if provider is not None and provider.clear is not None:
            _add_operation_commands(child, apprc, handlers, "cache", "clear")
    elif kind == "state":
        provider = handlers.state
        if provider is not None and provider.prune is not None:
            _add_operation_commands(child, apprc, handlers, "state", "prune")
        if provider is not None and provider.reset is not None:
            _add_operation_commands(child, apprc, handlers, "state", "reset")
    return child


def _add_operation_commands(
    app: typer.Typer,
    apprc: AppRC,
    handlers: MaintenanceHandlers,
    kind: ResourceKind,
    operation_name: str,
) -> None:
    """Register one explicitly supported prune/clear/reset operation."""

    @app.command(operation_name)
    def operation_command(
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
        """Plan, then optionally apply, the declared resource operation."""
        from apprc.interfaces._terminal_console import cli_line, human_report
        from apprc.interfaces.cli._maintenance_output import (
            print_resource_preview,
            print_resource_result,
        )

        human = human_report(json_output)
        manager = _manager(ctx, apprc, handlers)
        try:
            plans = _plan_operation(manager, kind, operation_name)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        if human:
            print_resource_preview(ctx, kind, operation_name, plans)
        results: tuple[RemovalResult, ...] = ()
        failure: dict[str, object] | None = None
        if not dry_run and plans:
            if not assume_yes:
                if not sys.stdin.isatty():
                    raise typer.BadParameter(
                        f"Noninteractive {kind} {operation_name} requires --yes."
                    )
                if not typer.confirm(
                    f"Apply {kind} {operation_name}?", err=True
                ):
                    raise typer.Exit(code=1)
            if human:
                cli_line(
                    ctx,
                    f"1. Applying {kind.title()} {operation_name.title()}",
                    style="stage",
                )
            try:
                results = _apply_operation(manager, kind, operation_name, plans)
            except _MaintenanceApplyError as exc:
                results = (*exc.results, exc.failure_result)
                failure = {
                    "category": exc.failed_plan.category,
                    "root": str(exc.failed_plan.root),
                    "message": str(exc),
                }
                if human:
                    print_resource_result(
                        ctx, kind, operation_name, results, failed=True
                    )
                    cli_line(
                        ctx,
                        "Failed target root",
                        path=exc.failed_plan.root,
                        style="error",
                        error=True,
                    )
                    cli_line(
                        ctx,
                        f"{kind.title()} {operation_name} failed: {exc}",
                        style="error",
                        error=True,
                    )
                else:
                    _emit(
                        _operation_payload(plans, results, failure), json_output
                    )
                raise typer.Exit(code=1) from exc
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
        if human:
            print_resource_result(ctx, kind, operation_name, results)
        else:
            _emit(_operation_payload(plans, results, failure), json_output)
        if any(result.skipped or result.warnings for result in results):
            raise typer.Exit(code=1)


def _workspace_group(apprc: AppRC) -> typer.Typer:
    """Build registry operations, or direct-path setup/inspection only."""
    declaration = apprc.schema.require_workspaces()
    child = typer.Typer(help="Inspect and manage declared workspaces.")
    if declaration.registry:

        @child.command("list")
        def list_workspaces(
            ctx: typer.Context,
            json_output: Annotated[
                bool, typer.Option("--json", help="Emit machine-readable JSON.")
            ] = False,
        ) -> None:
            """List registered workspaces and archived entries."""
            runtime = _context(ctx)
            try:
                inspection = apprc.workspaces(
                    _options(runtime), environment=runtime.environment
                ).inspect_registry()
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            from apprc.interfaces._terminal_console import human_report
            from apprc.interfaces.cli._maintenance_output import (
                print_workspace_registry,
            )

            if human_report(json_output):
                print_workspace_registry(ctx, inspection)
            else:
                _emit(_workspace_registry_payload(inspection), json_output)

        @child.command("add")
        def add_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            root: Annotated[
                Path,
                typer.Argument(
                    help="Directory to register as the workspace root."
                ),
            ],
            assume_yes: Annotated[
                bool,
                typer.Option(
                    "--yes",
                    "-y",
                    help="Proceed without asking for confirmation.",
                ),
            ] = False,
        ) -> None:
            """Register a root, confirming reuse of nonempty uninitialized data."""
            if (
                root.is_dir()
                and any(root.iterdir())
                and not (root / apprc.schema.workspace_dotenv_filename).exists()
                and not assume_yes
            ):
                if not sys.stdin.isatty():
                    raise typer.BadParameter(
                        "Reusing a nonempty workspace requires --yes."
                    )
                if not typer.confirm(
                    "Initialize settings in this nonempty workspace?"
                ):
                    raise typer.Exit(code=1)
            _workspace_manager(ctx, apprc).register_workspace(
                name=name, root=root
            )

        @child.command("select")
        def select_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
        ) -> None:
            """Persist the selected workspace name."""
            _workspace_manager(ctx, apprc).select_workspace(name=name)

        @child.command("rename")
        def rename_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            new_name: Annotated[
                str,
                typer.Argument(help="New name for the registered workspace."),
            ],
        ) -> None:
            """Rename a workspace without moving its files."""
            _workspace_manager(ctx, apprc).rename_workspace(
                old=name, new=new_name
            )

        @child.command("repoint")
        def repoint_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            root: Annotated[
                Path,
                typer.Argument(
                    help="Directory to register as the workspace root."
                ),
            ],
        ) -> None:
            """Change the registered root and create its settings file if missing."""
            _workspace_manager(ctx, apprc).repoint_workspace(
                name=name, root=root
            )

        @child.command("move")
        def move_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            destination: Annotated[
                Path,
                typer.Argument(help="New directory for the workspace."),
            ],
        ) -> None:
            """Move a workspace and update its registered root."""
            from apprc.interfaces._terminal_console import cli_line

            try:
                result = _workspace_manager(ctx, apprc).move_workspace(
                    name=name, root=destination
                )
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            cli_line(
                ctx, "Workspace moved", path=result.destination, style="success"
            )
            for warning in result.warnings:
                cli_line(
                    ctx, f"Warning: {warning}", style="warning", error=True
                )

        @child.command("remove")
        def remove_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
        ) -> None:
            """Unregister a workspace without deleting its files."""
            try:
                _workspace_manager(ctx, apprc).remove_workspace(name=name)
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc

        @child.command("archive")
        def archive_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            destination: Annotated[
                Path,
                typer.Argument(help="Archive file to create."),
            ],
        ) -> None:
            """Archive a registered workspace."""
            try:
                _workspace_manager(ctx, apprc).archive_workspace(
                    name=name, destination=destination
                )
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc

        @child.command("restore")
        def restore_workspace(
            ctx: typer.Context,
            name: Annotated[
                str, typer.Argument(help="Workspace name in the registry.")
            ],
            destination: Annotated[
                Path,
                typer.Argument(help="Directory for the restored workspace."),
            ],
            archive_path: Annotated[
                Path | None,
                typer.Option(
                    "--archive",
                    help="Read this archive instead of the registered workspace archive.",
                ),
            ] = None,
        ) -> None:
            """Restore a named workspace archive."""
            try:
                _workspace_manager(ctx, apprc).restore_workspace(
                    name=name,
                    destination=destination,
                    archive=archive_path,
                )
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
    else:

        @child.command("info")
        def direct_workspace_info(
            ctx: typer.Context,
            path: Annotated[
                Path,
                typer.Argument(
                    help="Direct workspace directory to inspect or initialize."
                ),
            ],
        ) -> None:
            """Inspect one direct workspace path without registry access."""
            root = path.expanduser().absolute()
            if root.is_dir():
                try:
                    selected = _workspace_manager(ctx, apprc).select_workspace(
                        str(root)
                    )
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
                if not isinstance(selected, Path):
                    raise typer.BadParameter(
                        "Direct workspace selection did not return a path."
                    )
                root = selected
            typer.echo(json.dumps({"root": str(root), "exists": root.is_dir()}))

        @child.command("init")
        def direct_workspace_init(
            ctx: typer.Context,
            path: Annotated[
                Path,
                typer.Argument(
                    help="Direct workspace directory to inspect or initialize."
                ),
            ],
        ) -> None:
            """Initialize one direct workspace path without registration."""
            try:
                root = _workspace_manager(ctx, apprc).initialize_workspace(path)
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            from apprc.interfaces._terminal_console import cli_line

            cli_line(ctx, "", path=root)

    return child


def _manager(
    ctx: typer.Context, apprc: AppRC, handlers: MaintenanceHandlers
) -> MaintenanceManager:
    context = _context(ctx)
    return MaintenanceManager(
        apprc.schema,
        options=_options(context),
        environment=context.environment,
        handlers=handlers,
        app_paths=context.paths,
    )


def _workspace_manager(ctx: typer.Context, apprc: AppRC) -> WorkspaceManager:
    runtime = _context(ctx)
    return apprc.workspaces(_options(runtime), environment=runtime.environment)


def _emit(payload: object, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, default=_json_default))
    else:
        typer.echo(json.dumps(payload, indent=2, default=_json_default))


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Value is not JSON-compatible: {type(value).__name__}")


def _workspace_registry_payload(
    inspection: WorkspaceRegistryInspection,
) -> dict[str, object]:
    registry = inspection.registry
    registry_payload: dict[str, object] | None = None
    if registry is not None:
        registry_payload = {
            "path": str(registry.path),
            "schema_version": registry.schema_version,
            "selected_workspace": registry.selected_workspace,
            "workspaces": [
                {"name": record.name, "root": str(record.root)}
                for record in sorted(
                    registry.workspaces.values(), key=lambda item: item.name
                )
            ],
            "archived_workspaces": [
                {
                    "name": record.name,
                    "archive": str(record.archive),
                    "source_root": str(record.source_root),
                }
                for record in sorted(
                    registry.archived_workspaces.values(),
                    key=lambda item: item.name,
                )
            ],
        }
    return {
        "path": str(inspection.path),
        "env_value": inspection.env_value,
        "exists": inspection.exists,
        "error": inspection.error,
        "registry": registry_payload,
        "workspace_count": inspection.workspace_count,
        "issues": list(inspection.issues),
        "warnings": list(inspection.warnings),
    }


def _plan_json(plan: RemovalPlan) -> dict[str, object]:
    return {
        "category": plan.category,
        "root": str(plan.root),
        "targets": [str(path) for path in plan.targets],
        "revision": plan.revision,
        "warnings": list(plan.warnings),
    }


def _operation_payload(
    plans: tuple[RemovalPlan, ...],
    results: tuple[RemovalResult, ...],
    failure: dict[str, object] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "plans": [_plan_json(plan) for plan in plans],
        "results": [
            {
                "category": plan.category,
                "root": str(plan.root),
                "removed": [str(path) for path in result.removed],
                "skipped": [str(path) for path in result.skipped],
                "warnings": list(result.warnings),
            }
            for plan, result in zip(plans, results, strict=False)
        ],
    }
    if failure is not None:
        payload["failure"] = failure
    return payload


def _plan_operation(
    manager: MaintenanceManager,
    kind: ResourceKind,
    name: str,
) -> tuple[RemovalPlan, ...]:
    if kind == "cache":
        if name == "prune":
            return manager.plan_cache_prune()
        if name == "clear":
            return manager.plan_cache_clear()
    if kind == "state":
        if name == "prune":
            return manager.plan_state_prune()
        if name == "reset":
            return manager.plan_state_reset()
    raise ValueError(f"Unsupported AppRC {kind} operation: {name}")


def _apply_operation(
    manager: MaintenanceManager,
    kind: ResourceKind,
    name: str,
    plans: tuple[RemovalPlan, ...],
) -> tuple[RemovalResult, ...]:
    if kind == "cache":
        if name == "prune":
            return manager.apply_cache_prune(plans)
        if name == "clear":
            return manager.apply_cache_clear(plans)
    if kind == "state":
        if name == "prune":
            return manager.apply_state_prune(plans)
        if name == "reset":
            return manager.apply_state_reset(plans)
    raise ValueError(f"Unsupported AppRC {kind} operation: {name}")
