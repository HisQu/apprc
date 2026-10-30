"""Fixed Typer commands for AppRC paths and resource maintenance."""

from __future__ import annotations

# == Standard Library ========================
import json
import sys
from pathlib import Path
from typing import Annotated, Any, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.maintenance import (
    MaintenanceHandlers,
    RemovalPlan,
    RemovalResult,
)
from apprc.definition.paths import PathKind, ResourceKind
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli.context import (
    CliRuntimeContext,
    cli_runtime_context_from,
)
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
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import (
    inspect_ownership,
    validate_category_root_boundaries,
)
from apprc.user_files.workspace_roots._loading import (
    WorkspaceRegistryInspection,
)

_CATEGORIES = ("config", "appdata", "cache", "state", "logs")
_RESOURCE_CATEGORIES: tuple[ResourceKind, ...] = (
    "config",
    "appdata",
    "cache",
    "state",
)
_RESOURCE_CATEGORY_BY_NAME: dict[str, ResourceKind] = {
    kind: kind for kind in _RESOURCE_CATEGORIES
}


def mount_maintenance_groups(
    app: typer.Typer,
    apprc: AppRC,
    *,
    handlers: MaintenanceHandlers = MaintenanceHandlers(),
    maintenance_help_panel: str = "Maintenance",
) -> dict[str, typer.Typer]:
    """Mount fixed path/maintenance commands and declared resource groups."""
    names = _registered_names(app)
    reserved = {"paths", "doctor", "purge", "installation"}
    reserved.update(
        kind
        for kind in ("appdata", "cache", "state")
        if getattr(apprc.schema.paths, kind)
    )
    if apprc.schema.workspaces is not None:
        reserved.add("workspace")
    collisions = reserved & names
    if collisions:
        raise RuntimeError(
            "AppRC maintenance cannot mount because these names are already "
            "in use: " + ", ".join(sorted(collisions))
        )
    mounted: dict[str, typer.Typer] = {}
    mounted["installation"] = mount_installation_group(
        app, maintenance_help_panel=maintenance_help_panel
    )

    @app.command("paths", rich_help_panel=maintenance_help_panel)
    def paths_command(
        ctx: typer.Context,
        category: Annotated[str | None, typer.Argument()] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        open_path: Annotated[bool, typer.Option("--open")] = False,
    ) -> None:
        """Show selected AppRC locations without creating them."""
        runtime = _context(ctx)
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
                typer.echo(str(path))
            if open_path:
                if not exists:
                    raise typer.BadParameter(
                        f"Directory does not exist: {path}"
                    )
                typer.launch(str(path))
            return
        locations = _locations(runtime)
        exists = {
            key: path.is_dir() if path is not None else None
            for key, path in locations.items()
        }
        payload = {
            "layout": runtime.paths.layout.mode,
            "root": str(runtime.paths.layout.root)
            if runtime.paths.layout.root
            else None,
            "source": runtime.paths.source,
            "paths": {
                key: str(path) if path is not None else None
                for key, path in locations.items()
            },
            "exists": exists,
        }
        if json_output:
            _emit(payload, True)
        else:
            typer.echo(f"layout: {payload['layout']}")
            typer.echo(f"root: {payload['root'] or '(native)'}")
            typer.echo(f"source: {payload['source']}")
            for key, path in locations.items():
                if path is not None:
                    typer.echo(f"{key}: {path} (exists: {exists[key]})")

    @app.command("doctor", rich_help_panel=maintenance_help_panel)
    def doctor_command(
        ctx: typer.Context,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Check declared AppRC paths without initializing application data."""
        diagnostic = installation_context(ctx)
        if diagnostic is not None:
            inspection = diagnostic.inspection
            unusable = inspection.status in {
                "invalid",
                "provisional",
                "incomplete",
            }
            failed = unusable or diagnostic.path_error is not None
            diagnostics = [
                {
                    "code": item.code,
                    "message": item.message,
                    "recovery": item.recovery,
                }
                for item in inspection.diagnostics
            ]
            if diagnostic.path_error is not None and all(
                item["message"] != diagnostic.path_error for item in diagnostics
            ):
                diagnostics.append(
                    {
                        "code": "path-resolution",
                        "message": diagnostic.path_error,
                        "recovery": "Inspect installation and reconcile placement or run explicit migration.",
                    }
                )
            _emit(
                {
                    "status": inspection.status
                    if unusable or not failed
                    else "error",
                    "installation": {
                        "app_id": inspection.app_id,
                        "status": inspection.status,
                        "directory": str(inspection.directory),
                        "revision": inspection.revision,
                        "diagnostics": diagnostics,
                    },
                },
                json_output,
            )
            if failed:
                raise typer.Exit(code=1)
            return
        runtime = _context(ctx)
        checks: list[dict[str, str]] = [
            {"name": "installation", "status": "error", "message": item.message}
            for item in runtime.paths.installation.diagnostics
        ]
        for key, path in _locations(runtime).items():
            if path is None:
                continue
            category: ResourceKind = (
                "state" if key == "logs" else cast(ResourceKind, key)
            )
            ownership_root = path
            state_root = runtime.paths.state_dir
            if (
                key == "logs"
                and state_root is not None
                and path.is_relative_to(state_root)
            ):
                ownership_root = state_root
            try:
                assert_no_links(path)
                ownership = inspect_ownership(
                    ownership_root, apprc.schema.app_id, category
                )
                if not path.exists():
                    status, message = (
                        "warning",
                        f"Directory is not initialized: {path}",
                    )
                elif ownership == "unowned":
                    status, message = "warning", f"Directory is unowned: {path}"
                elif ownership == "missing":
                    status, message = (
                        "warning",
                        f"Owning path is not initialized: {ownership_root}",
                    )
                else:
                    status, message = "ok", f"Owned directory exists: {path}"
            except (OSError, ValueError) as exc:
                status, message = "error", str(exc)
            checks.append({"name": key, "status": status, "message": message})
        if any(
            (
                apprc.schema.paths.config,
                apprc.schema.paths.appdata,
                apprc.schema.paths.cache,
                apprc.schema.paths.state,
            )
        ):
            try:
                validate_category_root_boundaries(apprc.schema, runtime.paths)
            except (OSError, ValueError) as exc:
                checks.append(
                    {
                        "name": "path_boundaries",
                        "status": "error",
                        "message": str(exc),
                    }
                )
            else:
                checks.append(
                    {
                        "name": "path_boundaries",
                        "status": "ok",
                        "message": "Declared paths are non-overlapping and link-free.",
                    }
                )
        if apprc.schema.paths.config or apprc.schema.owners:
            try:
                inspection = apprc._manage_with_paths(
                    _options(runtime), runtime.environment, runtime.paths
                ).inspect()
                if inspection.issues:
                    checks.append(
                        {
                            "name": "configuration",
                            "status": "error",
                            "message": "; ".join(inspection.issues),
                        }
                    )
                else:
                    checks.append(
                        {
                            "name": "configuration",
                            "status": "ok",
                            "message": "Declared configuration is valid.",
                        }
                    )
            except (OSError, ValueError) as exc:
                checks.append(
                    {
                        "name": "configuration",
                        "status": "error",
                        "message": str(exc),
                    }
                )
        status = (
            "error"
            if any(check["status"] == "error" for check in checks)
            else "warning"
            if any(check["status"] == "warning" for check in checks)
            else "ok"
        )
        _emit({"status": status, "checks": checks}, json_output)
        if status == "error":
            raise typer.Exit(code=1)

    @app.command("purge", rich_help_panel=maintenance_help_panel)
    def purge_command(
        ctx: typer.Context,
        scope: Annotated[list[str] | None, typer.Option("--scope")] = None,
        all_scopes: Annotated[bool, typer.Option("--all")] = False,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Preview or remove exact AppRC-managed resource files."""
        if (not scope and not all_scopes) or (scope and all_scopes):
            raise typer.BadParameter(
                "Choose one or more --scope values or --all."
            )
        scopes: tuple[ResourceKind, ...]
        if all_scopes:
            scopes = tuple(
                kind for kind in _RESOURCE_CATEGORIES if _declared(apprc, kind)
            )
        else:
            invalid = [
                item for item in scope or () if item not in _RESOURCE_CATEGORIES
            ]
            if invalid:
                raise typer.BadParameter(f"Unknown purge scope: {invalid[0]}")
            scopes = tuple(
                dict.fromkeys(
                    _RESOURCE_CATEGORY_BY_NAME[item] for item in scope or ()
                )
            )
        manager = _manager(ctx, apprc, handlers)
        try:
            plans = manager.plan_purge(scopes)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        results: tuple[RemovalResult, ...] = ()
        if not dry_run and plans:
            if not assume_yes:
                if not sys.stdin.isatty():
                    raise typer.BadParameter(
                        "Noninteractive purge requires --yes."
                    )
                if not typer.confirm(
                    "Remove the planned AppRC resources?", err=True
                ):
                    _emit_purge(json_output, plans, results)
                    raise typer.Exit(code=1)
            try:
                results = manager.apply_purge(plans)
            except _MaintenanceApplyError as exc:
                _emit_purge(
                    json_output,
                    plans,
                    (*exc.results, exc.failure_result),
                    failure={
                        "category": exc.failed_plan.category,
                        "root": str(exc.failed_plan.root),
                        "message": str(exc),
                    },
                )
                raise typer.Exit(code=1) from exc
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
        _emit_purge(json_output, plans, results)
        if any(result.skipped or result.warnings for result in results):
            raise typer.Exit(code=1)

    for kind in ("appdata", "cache", "state"):
        if not getattr(apprc.schema.paths, kind):
            continue
        child = _resource_group(apprc, handlers, kind)
        app.add_typer(child, name=kind, rich_help_panel=maintenance_help_panel)
        mounted[kind] = child
    if apprc.schema.workspaces is not None:
        workspace = _workspace_group(apprc)
        app.add_typer(
            workspace, name="workspace", rich_help_panel=maintenance_help_panel
        )
        mounted["workspace"] = workspace
    return mounted


def _resource_group(
    apprc: AppRC,
    handlers: MaintenanceHandlers,
    kind: ResourceKind,
) -> typer.Typer:
    """Build info/init and only the named operations declared for a category."""
    child = typer.Typer(help=f"Inspect and initialize AppRC {kind}.")

    @child.command("info")
    def info_command(
        ctx: typer.Context,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show resource root existence and ownership."""
        try:
            payload = _manager(ctx, apprc, handlers).info(kind)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        _emit(payload, json_output)

    @child.command("init")
    def init_command(
        ctx: typer.Context,
        adopt: Annotated[bool, typer.Option("--adopt")] = False,
        logs: Annotated[bool, typer.Option("--logs")] = False,
    ) -> None:
        """Initialize the selected resource directory privately."""
        path_kind: PathKind = "logs" if kind == "state" and logs else kind
        try:
            path = _manager(ctx, apprc, handlers).ensure_path(
                path_kind, adopt=adopt
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(str(path))

    provider = getattr(handlers, kind)
    if kind == "appdata":
        if provider is not None and provider.backup is not None:

            @child.command("backup")
            def backup_command(ctx: typer.Context, destination: Path) -> None:
                """Create an application-owned AppData backup."""
                try:
                    path = _manager(ctx, apprc, handlers).backup_appdata(
                        destination
                    )
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
                typer.echo(str(path))

        if provider is not None and provider.restore is not None:

            @child.command("restore")
            def restore_command(
                ctx: typer.Context,
                source: Path,
                assume_yes: Annotated[
                    bool, typer.Option("--yes", "-y")
                ] = False,
            ) -> None:
                """Restore an application-owned AppData backup."""
                if not assume_yes and not typer.confirm(
                    f"Restore AppData from {source}?"
                ):
                    raise typer.Exit(code=1)
                try:
                    _manager(ctx, apprc, handlers).restore_appdata(source)
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
    elif kind == "cache" and provider is not None:
        if provider.prune is not None:
            _add_operation_commands(child, apprc, handlers, "cache", "prune")
        if provider.clear is not None:
            _add_operation_commands(child, apprc, handlers, "cache", "clear")
    elif kind == "state" and provider is not None:
        if provider.prune is not None:
            _add_operation_commands(child, apprc, handlers, "state", "prune")
        if provider.reset is not None:
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
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Plan, then optionally apply, the declared resource operation."""
        manager = _manager(ctx, apprc, handlers)
        try:
            plans = _plan_operation(manager, kind, operation_name)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
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
            try:
                results = _apply_operation(manager, kind, operation_name, plans)
            except _MaintenanceApplyError as exc:
                results = (*exc.results, exc.failure_result)
                failure = {
                    "category": exc.failed_plan.category,
                    "root": str(exc.failed_plan.root),
                    "message": str(exc),
                }
                _emit(_operation_payload(plans, results, failure), json_output)
                raise typer.Exit(code=1) from exc
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
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
            json_output: Annotated[bool, typer.Option("--json")] = False,
        ) -> None:
            """List registered workspaces and archived entries."""
            runtime = _context(ctx)
            try:
                inspection = apprc.workspaces(
                    _options(runtime), environment=runtime.environment
                ).inspect_registry()
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            _emit(_workspace_registry_payload(inspection), json_output)

        @child.command("add")
        def add_workspace(
            ctx: typer.Context,
            name: str,
            root: Path,
            assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
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
        def select_workspace(ctx: typer.Context, name: str) -> None:
            """Persist the selected workspace name."""
            _workspace_manager(ctx, apprc).select_workspace(name=name)

        @child.command("rename")
        def rename_workspace(
            ctx: typer.Context, name: str, new_name: str
        ) -> None:
            """Rename a workspace without moving its files."""
            _workspace_manager(ctx, apprc).rename_workspace(
                old=name, new=new_name
            )

        @child.command("repoint")
        def repoint_workspace(
            ctx: typer.Context, name: str, root: Path
        ) -> None:
            """Change a workspace's registered path."""
            _workspace_manager(ctx, apprc).repoint_workspace(
                name=name, root=root
            )

        @child.command("move")
        def move_workspace(
            ctx: typer.Context, name: str, destination: Path
        ) -> None:
            """Move a workspace and update its registered root."""
            _workspace_manager(ctx, apprc).move_workspace(
                name=name, root=destination
            )

        @child.command("remove")
        def remove_workspace(ctx: typer.Context, name: str) -> None:
            """Unregister a workspace without deleting its files."""
            _workspace_manager(ctx, apprc).remove_workspace(name=name)

        @child.command("archive")
        def archive_workspace(
            ctx: typer.Context, name: str, destination: Path
        ) -> None:
            """Archive a registered workspace."""
            _workspace_manager(ctx, apprc).archive_workspace(
                name=name, destination=destination
            )

        @child.command("restore")
        def restore_workspace(
            ctx: typer.Context,
            name: str,
            destination: Path,
            archive_path: Annotated[
                Path | None, typer.Option("--archive")
            ] = None,
        ) -> None:
            """Restore a named workspace archive."""
            _workspace_manager(ctx, apprc).restore_workspace(
                name=name,
                destination=destination,
                archive=archive_path,
            )
    else:

        @child.command("info")
        def direct_workspace_info(ctx: typer.Context, path: Path) -> None:
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
        def direct_workspace_init(ctx: typer.Context, path: Path) -> None:
            """Initialize one direct workspace path without registration."""
            try:
                root = _workspace_manager(ctx, apprc).initialize_workspace(path)
            except (OSError, ValueError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            typer.echo(str(root))

    return child


def _context(ctx: typer.Context) -> CliRuntimeContext[Any]:
    """Return captured root context, including on runtime-independent actions."""
    context = cli_runtime_context_from(ctx)
    if context is None:
        raise RuntimeError("AppRC CLI runtime context is not initialized.")
    return context


def _options(context: CliRuntimeContext[Any]) -> ResolveOptions:
    options = context.runtime_options
    return ResolveOptions(
        env_files=options.env_files,
        env_file_overrides_os_environ=options.env_file_overrides_os_environ,
        load_dotenv_layers=options.load_dotenv_layers,
        workspace=options.workspace,
        layout=options.layout,
    )


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


def _locations(context: CliRuntimeContext[Any]) -> dict[str, Path | None]:
    paths = context.paths
    return {
        "config": paths.config_dir,
        "appdata": paths.appdata_dir,
        "cache": paths.cache_dir,
        "state": paths.state_dir,
        "logs": paths.logs_dir,
    }


def _declared(apprc: AppRC, kind: ResourceKind) -> bool:
    return (
        apprc.schema.paths.config
        if kind == "config"
        else getattr(apprc.schema.paths, kind)
    )


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


def _emit_purge(
    json_output: bool,
    plans: tuple[RemovalPlan, ...],
    results: tuple[RemovalResult, ...],
    *,
    failure: dict[str, object] | None = None,
) -> None:
    _emit(_operation_payload(plans, results, failure), json_output)


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
    manager: MaintenanceManager, kind: ResourceKind, name: str
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


def _registered_names(app: typer.Typer) -> set[str]:
    names = {group.name for group in app.registered_groups if group.name}
    for command in app.registered_commands:
        if command.name:
            names.add(command.name)
        elif command.callback is not None:
            names.add(typer.main.get_command_name(command.callback.__name__))
    return names
