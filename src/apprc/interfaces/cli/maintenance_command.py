"""Fixed Typer commands for AppRC paths and resource maintenance."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import sys
from typing import Annotated, Any, Callable, Literal, cast
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.installation import (
    EditableCheckout,
    InstallationHooks,
    InstallationIdentity,
    RuntimeSlot,
)
from apprc.definition.maintenance import (
    MaintenanceHandlers,
    RemovalPlan,
    RemovalResult,
)
from apprc.definition.paths import ResourceKind
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
from apprc.interfaces.cli._root_help import _AppRCMaintenanceGroup
from apprc.user_files.app_home.ownership import (
    inspect_ownership,
    validate_category_root_boundaries,
)
from apprc.user_files.workspace_roots._loading import (
    WorkspaceRegistryInspection,
)
from apprc.interfaces.cli.diagnostics.payload import (
    DiagnosticCheck,
    build_config_doctor_payload,
)
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus
from apprc.interfaces.cli.doctor_output import print_doctor_report

_APPLICATION_DIAGNOSTICS: ContextVar[bool] = ContextVar(
    "apprc_application_diagnostics", default=False
)


@contextmanager
def application_diagnostics_scope() -> Iterator[None]:
    """Restrict doctor to application providers for one in-process invocation."""
    token = _APPLICATION_DIAGNOSTICS.set(True)
    try:
        yield
    finally:
        _APPLICATION_DIAGNOSTICS.reset(token)


def _validate_native_runtime_observations(
    observations: Mapping[str, object],
    *,
    directory: Path,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    command_name: str,
) -> None:
    """Require live probe observations to match the saved runtime authority.

    :param observations: Metadata returned by the target interpreter probe.
    :param directory: Installation directory containing the active runtime.
    :param identity: Saved application and distribution identity.
    :param runtime: Active managed slot or editable checkout.
    :param command_name: Saved primary console command.
    """
    fields = {
        "distribution",
        "version",
        "prefix",
        "interpreter",
        "python_version",
        "commands",
    }
    if set(observations) != fields:
        raise ValueError("Runtime probe returned an invalid observation shape.")
    distribution = observations["distribution"]
    version = observations["version"]
    prefix = observations["prefix"]
    interpreter = observations["interpreter"]
    python_version = observations["python_version"]
    commands = observations["commands"]
    if (
        not isinstance(distribution, str)
        or re.sub(r"[-_.]+", "-", distribution).lower() != identity.distribution
        or not isinstance(version, str)
        or not version
        or (isinstance(runtime, RuntimeSlot) and version != runtime.version)
        or not isinstance(prefix, str)
        or not Path(prefix).is_absolute()
        or not isinstance(interpreter, str)
        or not Path(interpreter).is_absolute()
        or not isinstance(python_version, str)
        or not python_version
        or not isinstance(commands, dict)
        or set(commands) != set(identity.commands)
        or command_name not in commands
        or not all(
            isinstance(value, str) and value for value in commands.values()
        )
    ):
        raise ValueError(
            "Runtime probe observations differ from saved authority."
        )
    from apprc.distribution.runtime.backend import (
        runtime_interpreter,
        runtime_prefix,
    )

    try:
        observed_prefix = Path(prefix).resolve(strict=True)
        observed_interpreter = Path(interpreter).resolve(strict=True)
        expected_prefix = runtime_prefix(directory, runtime).resolve(
            strict=True
        )
        expected_interpreter = runtime_interpreter(directory, runtime).resolve(
            strict=True
        )
    except OSError as exc:
        raise ValueError("Runtime probe paths are unavailable.") from exc
    if (
        observed_prefix != expected_prefix
        or observed_interpreter != expected_interpreter
    ):
        raise ValueError(
            "Runtime probe prefix or interpreter differs from authority."
        )


def _doctor_payload(
    ctx: typer.Context,
    apprc: AppRC,
    *,
    verbose: bool,
    host_diagnostics: Callable[[], Mapping[str, object]] | None,
    resource_diagnostics: Mapping[
        Literal["appdata", "cache", "state"],
        Callable[[Path], Mapping[str, object]],
    ],
    resource_groups: Mapping[Literal["appdata", "cache", "state"], typer.Typer],
) -> dict[str, object]:
    """Aggregate local installation, path, configuration, and provider checks."""
    if _APPLICATION_DIAGNOSTICS.get():
        application_checks: list[dict[str, str]] = []
        application_details: dict[str, object] = {"resources": {}, "host": {}}
        runtime = cli_runtime_context_from(ctx)
        if runtime is not None:
            if apprc.schema.paths.config or apprc.schema.owners:
                try:
                    config_manager = apprc._manage_with_paths(
                        _options(runtime), runtime.environment, runtime.paths
                    )
                    config_payload = build_config_doctor_payload(
                        apprc, manager=config_manager
                    )
                    application_details["configuration"] = (
                        config_payload.to_payload()
                    )
                    application_checks.extend(
                        {
                            "name": item.name,
                            "status": item.status,
                            "message": item.message,
                        }
                        for item in config_payload.checks
                    )
                except (OSError, ValueError) as exc:
                    application_checks.append(
                        {
                            "name": "configuration",
                            "status": "error",
                            "message": str(exc),
                        }
                    )
            application_resources = cast(
                dict[str, object], application_details["resources"]
            )
            for kind, callback in resource_diagnostics.items():
                path = getattr(runtime.paths, f"{kind}_dir")
                if path is None or not path.is_dir():
                    continue
                try:
                    application_resources[kind] = dict(callback(path))
                    application_checks.append(
                        {
                            "name": f"resource_{kind}_provider",
                            "status": "ok",
                            "message": "Provider inspection completed.",
                        }
                    )
                except (OSError, ValueError) as exc:
                    application_checks.append(
                        {
                            "name": f"resource_{kind}_provider",
                            "status": "error",
                            "message": str(exc),
                        }
                    )
        if host_diagnostics is not None:
            try:
                application_details["host"] = dict(host_diagnostics())
            except (OSError, ValueError) as exc:
                application_checks.append(
                    {
                        "name": "host_provider",
                        "status": "error",
                        "message": str(exc),
                    }
                )
        status = (
            "error"
            if any(item["status"] == "error" for item in application_checks)
            else "warning"
            if any(item["status"] == "warning" for item in application_checks)
            else "ok"
        )
        return {
            "status": status,
            "checks": application_checks,
            "details": application_details,
        }
    from apprc.interfaces.cli.installation_command import _inspection_payload

    diagnostic = installation_context(ctx)
    runtime = cli_runtime_context_from(ctx)
    checks: list[DiagnosticCheck] = []
    installation_diagnostics: list[dict[str, str]] = []
    inspection = diagnostic.inspection if diagnostic is not None else None
    if inspection is None and runtime is not None:
        inspection = apprc.installation(
            environment=runtime.environment
        ).inspect()
    if inspection is None:
        raise RuntimeError(
            "AppRC doctor has no installation inspection context."
        )
    installation = _inspection_payload(inspection)
    installation_diagnostics = [
        {
            "code": item.code,
            "message": item.message,
            "recovery": item.recovery,
        }
        for item in inspection.diagnostics
    ]
    unusable = inspection.status in {"invalid", "provisional", "incomplete"}
    path_diagnostics = (
        runtime.paths.installation.diagnostics if runtime is not None else ()
    )
    path_diagnostic_keys = {
        (item.code, item.message) for item in path_diagnostics
    }
    for item in inspection.diagnostics:
        checks.append(
            DiagnosticCheck(
                "installation",
                ConfigDoctorStatus.ERROR.value
                if unusable or (item.code, item.message) in path_diagnostic_keys
                else ConfigDoctorStatus.WARNING.value,
                f"{item.message} Recovery: {item.recovery}",
            )
        )
    checks.append(
        DiagnosticCheck(
            "installation",
            ConfigDoctorStatus.ERROR.value
            if unusable or path_diagnostics
            else ConfigDoctorStatus.WARNING.value
            if inspection.diagnostics
            else ConfigDoctorStatus.OK.value,
            inspection.status,
        )
    )
    if diagnostic is not None and diagnostic.path_error is not None:
        checks.append(
            DiagnosticCheck(
                "path_resolution",
                ConfigDoctorStatus.ERROR.value,
                diagnostic.path_error,
            )
        )
        installation_diagnostics.append(
            {
                "code": "path-resolution",
                "message": diagnostic.path_error,
                "recovery": "Inspect saved placement and run explicit migration if needed.",
            }
        )
        installation["diagnostics"] = installation_diagnostics

    paths_detail: dict[str, object] | None = None
    config_detail: dict[str, object] | None = None
    resources: dict[str, object] = {}
    operations_by_kind: dict[str, list[str]] = {}
    if verbose:
        from apprc.interfaces.cli.runtime import _registered_typer_names

        operations_by_kind = {
            kind: _registered_typer_names(group)
            for kind, group in resource_groups.items()
        }
    boundaries_safe = True
    if runtime is not None:
        paths_detail = _paths_payload(runtime)
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
                boundaries_safe = False
                checks.append(
                    DiagnosticCheck(
                        "path_boundaries",
                        ConfigDoctorStatus.ERROR.value,
                        str(exc),
                    )
                )
            else:
                checks.append(
                    DiagnosticCheck(
                        "path_boundaries",
                        ConfigDoctorStatus.OK.value,
                        "Declared paths are non-overlapping and link-free.",
                    )
                )
        for key, path in _locations(runtime).items():
            if path is None:
                continue
            kind: ResourceKind = (
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
                    ownership_root, apprc.schema.app_id, kind
                )
                status = (
                    ConfigDoctorStatus.WARNING.value
                    if not path.exists() or ownership != "owned"
                    else ConfigDoctorStatus.OK.value
                )
                message = f"{key} is {ownership}."
            except (OSError, ValueError) as exc:
                ownership = None
                status = ConfigDoctorStatus.ERROR.value
                message = str(exc)
            checks.append(DiagnosticCheck(key, status, message))
            if key in {"appdata", "cache", "state"}:
                resource_kind = cast(Literal["appdata", "cache", "state"], key)
                resource: dict[str, object] = {
                    "root": str(path),
                    "exists": path.is_dir(),
                    "ownership": ownership,
                    "operations": operations_by_kind.get(resource_kind, []),
                }
                callback = resource_diagnostics.get(resource_kind)
                if (
                    verbose
                    and boundaries_safe
                    and callback is not None
                    and path.is_dir()
                    and ownership == "owned"
                ):
                    try:
                        resource["provider"] = dict(callback(path))
                    except (OSError, ValueError) as exc:
                        checks.append(
                            DiagnosticCheck(
                                f"resource_{key}_provider",
                                ConfigDoctorStatus.ERROR.value,
                                str(exc),
                            )
                        )
                resources[key] = resource
        for key in ("appdata", "cache", "state"):
            kind = cast(Literal["appdata", "cache", "state"], key)
            if _declared(apprc, kind) and key not in resources:
                resources[key] = {
                    "root": None,
                    "exists": None,
                    "ownership": None,
                    "operations": operations_by_kind.get(kind, []),
                }
        if (apprc.schema.paths.config or apprc.schema.owners) and not (
            diagnostic is not None and diagnostic.native_binding is not None
        ):
            try:
                config_manager = apprc._manage_with_paths(
                    _options(runtime), runtime.environment, runtime.paths
                )
                payload = build_config_doctor_payload(
                    apprc, manager=config_manager
                )
                config_detail = payload.to_payload()
                checks.extend(payload.checks)
            except (OSError, ValueError) as exc:
                checks.append(
                    DiagnosticCheck(
                        "configuration",
                        ConfigDoctorStatus.ERROR.value,
                        str(exc),
                    )
                )
    else:
        for key in ("appdata", "cache", "state"):
            kind = cast(Literal["appdata", "cache", "state"], key)
            if _declared(apprc, kind):
                resources[key] = {
                    "root": None,
                    "exists": None,
                    "ownership": None,
                    "operations": operations_by_kind.get(kind, []),
                }
    if runtime is not None and diagnostic is None:
        reported = {
            (item["code"], item["message"]) for item in installation_diagnostics
        }
        for item in runtime.paths.installation.diagnostics:
            key = (item.code, item.message)
            if key in reported:
                continue
            reported.add(key)
            installation_diagnostics.append(
                {
                    "code": item.code,
                    "message": item.message,
                    "recovery": item.recovery,
                }
            )
            checks.append(
                DiagnosticCheck(
                    "installation",
                    ConfigDoctorStatus.ERROR.value,
                    f"{item.message} Recovery: {item.recovery}",
                )
            )
        installation["diagnostics"] = installation_diagnostics

    details: dict[str, object] | None = None
    if verbose:
        host: Mapping[str, object] = {}
        if host_diagnostics is not None:
            try:
                host = host_diagnostics()
            except (OSError, ValueError) as exc:
                checks.append(
                    DiagnosticCheck(
                        "host_provider",
                        ConfigDoctorStatus.ERROR.value,
                        str(exc),
                    )
                )
        details = {
            "paths": paths_detail,
            "configuration": config_detail,
            "resources": resources,
            "host": dict(host),
        }
    status = (
        ConfigDoctorStatus.ERROR.value
        if any(
            check.status == ConfigDoctorStatus.ERROR.value for check in checks
        )
        else ConfigDoctorStatus.WARNING.value
        if any(
            check.status == ConfigDoctorStatus.WARNING.value for check in checks
        )
        else ConfigDoctorStatus.OK.value
    )
    if inspection is not None and inspection.status in {
        "invalid",
        "provisional",
        "incomplete",
    }:
        status = inspection.status
    result: dict[str, object] = {
        "status": status,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "message": check.message,
            }
            for check in checks
        ],
        "installation": installation,
    }
    if details is not None:
        result["details"] = details
    return result


_CATEGORIES = ("config", "appdata", "cache", "state", "logs")


def mount_maintenance_groups(
    app: typer.Typer,
    apprc: AppRC,
    *,
    handlers: MaintenanceHandlers = MaintenanceHandlers(),
    maintenance_help_panel: str = "AppRC: Commands",
    maintenance_group_name: str = "app",
    installation_management: bool = False,
    installation_hooks: InstallationHooks = InstallationHooks(),
    host_diagnostics: Callable[[], Mapping[str, object]] | None = None,
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
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
        installation_management=installation_management,
        installer_entrypoint=installer_entrypoint,
        installation_hooks=installation_hooks,
    )

    @maintenance.command("paths", rich_help_panel=maintenance_help_panel)
    def paths_command(
        ctx: typer.Context,
        category: Annotated[str | None, typer.Argument()] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        open_path: Annotated[bool, typer.Option("--open")] = False,
    ) -> None:
        """Show selected AppRC locations without creating them."""
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
            _emit(
                {"category": category, "path": str(path), "exists": exists},
                json_output,
            ) if json_output else typer.echo(str(path))
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
            typer.echo(f"root: {payload['root'] or '(native)'}")
            typer.echo(f"source: {payload['source']}")
            exists = cast(dict[str, bool | None], payload["exists"])
            for key, path in _locations(runtime).items():
                if path is not None:
                    typer.echo(f"{key}: {path} (exists: {exists[key]})")

    @maintenance.command("doctor", rich_help_panel=maintenance_help_panel)
    def doctor_command(
        ctx: typer.Context,
        verbose: Annotated[bool, typer.Option("--verbose")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Check installation authority, paths, and declared configuration."""
        payload = _doctor_payload(
            ctx,
            apprc,
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
                    cast(list[object], payload["checks"]).extend(
                        [
                            {
                                "name": "runtime_health",
                                "status": "error",
                                "message": f"Active runtime probe failed: {exc}",
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
            print_doctor_report(payload)
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
            ("doctor", "paths", "install", "repair", "uninstall", "migrate")
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


def _paths_payload(context: CliRuntimeContext[Any]) -> dict[str, object]:
    """Return the stable all-category path report for commands and doctor."""
    locations = _locations(context)
    return {
        "layout": context.paths.layout.mode,
        "root": str(context.paths.layout.root)
        if context.paths.layout.root
        else None,
        "source": context.paths.source,
        "paths": {
            key: str(path) if path is not None else None
            for key, path in locations.items()
        },
        "exists": {
            key: path.is_dir() if path is not None else None
            for key, path in locations.items()
        },
    }


def _declared(apprc: AppRC, kind: ResourceKind) -> bool:
    paths = apprc.schema.paths
    if kind == "config":
        return paths.config
    if kind == "appdata":
        return paths.appdata
    if kind == "cache":
        return paths.cache
    return paths.state


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
