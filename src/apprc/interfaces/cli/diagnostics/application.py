"""Application doctor aggregation and read-only path diagnostics."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import re
from typing import Any, Callable, Literal, cast
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.installation import (
    EditableCheckout,
    InstallationDiagnostic,
    InstallationIdentity,
    RuntimeSlot,
)
from apprc.definition.paths import ResourceKind
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli.context import (
    CliRuntimeContext,
    cli_runtime_context_from,
    installation_command_context_from,
)
from apprc.public.app_rc import AppRC
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import (
    inspect_ownership,
    validate_category_root_boundaries,
)
from apprc.interfaces.cli.diagnostics.payload import (
    DiagnosticCheck,
    build_config_doctor_payload,
)
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus

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


def _build_runtime_diagnostics(
    ctx: typer.Context,
    apprc: AppRC,
    host_diagnostics: Callable[[], Mapping[str, object]] | None,
    resource_diagnostics: Mapping[
        Literal["appdata", "cache", "state"],
        Callable[[Path], Mapping[str, object]],
    ],
) -> dict[str, object]:
    """Collect application-owned diagnostics inside an active runtime."""
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


def build_application_doctor_payload(
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
        return _build_runtime_diagnostics(
            ctx, apprc, host_diagnostics, resource_diagnostics
        )
    from apprc.interfaces.cli._installation_output import (
        installation_inspection_payload,
    )

    diagnostic = installation_command_context_from(ctx)
    runtime = cli_runtime_context_from(ctx)
    checks: list[DiagnosticCheck] = []
    additional_diagnostics: list[InstallationDiagnostic] = []
    inspection = diagnostic.inspection if diagnostic is not None else None
    if inspection is None and runtime is not None:
        inspection = apprc.installation(
            environment=runtime.environment
        ).inspect()
    if inspection is None:
        raise RuntimeError(
            "AppRC doctor has no installation inspection context."
        )
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
        additional_diagnostics.append(
            InstallationDiagnostic(
                "path-resolution",
                diagnostic.path_error,
                "Inspect saved placement and run explicit migration if needed.",
            )
        )

    paths_detail: dict[str, object] | None = None
    operations_by_kind: dict[str, list[str]] = {}
    if verbose:
        from apprc.interfaces.cli.runtime import _registered_typer_names

        operations_by_kind = {
            kind: _registered_typer_names(group)
            for kind, group in resource_groups.items()
        }
    if runtime is not None:
        paths_detail = _paths_payload(runtime)
    resources, config_detail = _inspect_runtime_paths(
        apprc,
        runtime,
        checks,
        operations_by_kind,
        resource_diagnostics,
        verbose=verbose,
        native_diagnostic=diagnostic is not None
        and diagnostic.native_binding is not None,
    )
    if runtime is not None and diagnostic is None:
        reported = {
            (item.code, item.message) for item in inspection.diagnostics
        }
        for item in runtime.paths.installation.diagnostics:
            key = (item.code, item.message)
            if key in reported:
                continue
            reported.add(key)
            additional_diagnostics.append(item)
            checks.append(
                DiagnosticCheck(
                    "installation",
                    ConfigDoctorStatus.ERROR.value,
                    f"{item.message} Recovery: {item.recovery}",
                )
            )

    installation = installation_inspection_payload(
        inspection, additional_diagnostics=additional_diagnostics
    )
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


def _inspect_runtime_paths(
    apprc: AppRC,
    runtime: CliRuntimeContext[Any] | None,
    checks: list[DiagnosticCheck],
    operations_by_kind: Mapping[str, list[str]],
    resource_diagnostics: Mapping[
        Literal["appdata", "cache", "state"],
        Callable[[Path], Mapping[str, object]],
    ],
    *,
    verbose: bool,
    native_diagnostic: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Check path boundaries and ownership before calling resource providers."""
    resources: dict[str, object] = {}
    config_detail: dict[str, object] | None = None
    boundaries_safe = True
    if runtime is not None:
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
        if (
            apprc.schema.paths.config or apprc.schema.owners
        ) and not native_diagnostic:
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
    return resources, config_detail


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
