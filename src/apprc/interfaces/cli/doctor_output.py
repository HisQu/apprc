"""Human-readable AppRC diagnostic output."""

from __future__ import annotations
from collections.abc import Mapping

from rich.console import Console
from rich.text import Text

from apprc.interfaces.cli.diagnostics.payload import ConfigDoctorPayload
from apprc.public.app_rc import AppRC


def print_config_doctor(
    apprc: AppRC,
    payload: ConfigDoctorPayload,
) -> None:
    """Print configuration-only checks with their structured statuses.

    :param apprc: Application config facade.
    :param payload: Configuration diagnostic result.
    """
    console = Console(soft_wrap=True)
    console.print(
        Text(
            f"{apprc.schema.display_name} config doctor: {payload.status}",
            style="bold",
        )
    )
    for check in payload.checks:
        console.print(f"[{check.status}] {check.name}: {check.message}")


def print_config_paths(
    apprc: AppRC,
    payload: ConfigDoctorPayload,
) -> None:
    """Print the config group's read-only diagnostic summary.

    :param apprc: Application config facade.
    :param payload: Configuration diagnostic result.
    """
    console = Console(soft_wrap=True)
    console.print(
        Text(f"{apprc.schema.display_name} config paths", style="bold")
    )
    for check in payload.checks:
        console.print(f"[{check.status}] {check.name}: {check.message}")


def print_doctor_report(payload: dict[str, object]) -> None:
    """Render the aggregate maintenance report for interactive terminal use.

    :param payload: Unified maintenance doctor result.
    """
    console = Console(soft_wrap=True)
    console.print(Text(f"AppRC doctor: {payload['status']}", style="bold"))
    installation = payload.get("installation")
    if isinstance(installation, Mapping):
        console.print(
            Text(
                f"Installation: {installation.get('status')} "
                f"({installation.get('directory')})"
            )
        )
        diagnostics = installation.get("diagnostics")
        if isinstance(diagnostics, list):
            for diagnostic in diagnostics:
                if isinstance(diagnostic, Mapping):
                    console.print(
                        Text(
                            f"[{diagnostic.get('code')}] "
                            f"{diagnostic.get('message')}"
                        )
                    )
                    if diagnostic.get("recovery"):
                        console.print(
                            Text(f"  Recovery: {diagnostic['recovery']}")
                        )
    checks = payload.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, Mapping):
                console.print(
                    Text(
                        f"[{check.get('status')}] {check.get('name')}: "
                        f"{check.get('message')}"
                    )
                )
    details = payload.get("details")
    if not isinstance(details, Mapping):
        return
    paths = details.get("paths")
    if isinstance(paths, Mapping):
        console.print(Text("Paths", style="bold"))
        for key in ("layout", "root", "source"):
            if key in paths:
                console.print(Text(f"{key}: {paths[key]}"))
        path_map = paths.get("paths")
        exists_map = paths.get("exists")
        if isinstance(path_map, Mapping):
            for name, path in path_map.items():
                exists = (
                    exists_map.get(name)
                    if isinstance(exists_map, Mapping)
                    else None
                )
                console.print(Text(f"{name}: {path} (exists: {exists})"))
    configuration = details.get("configuration")
    if isinstance(configuration, Mapping):
        console.print(
            Text(f"Configuration: {configuration.get('status')}", style="bold")
        )
        config_checks = configuration.get("checks")
        if isinstance(config_checks, list):
            for check in config_checks:
                if isinstance(check, Mapping):
                    console.print(
                        Text(
                            f"[{check.get('status')}] {check.get('name')}: "
                            f"{check.get('message')}"
                        )
                    )
    resources = details.get("resources")
    if isinstance(resources, Mapping):
        console.print(Text("Resources", style="bold"))
        for name, resource in resources.items():
            if not isinstance(resource, Mapping):
                continue
            console.print(
                Text(
                    f"{name}: root={resource.get('root')}, "
                    f"exists={resource.get('exists')}, "
                    f"ownership={resource.get('ownership')}, "
                    f"operations={resource.get('operations')}"
                )
            )
            provider = resource.get("provider")
            if isinstance(provider, Mapping):
                for key, value in provider.items():
                    console.print(Text(f"  {key}: {value}"))
    host = details.get("host")
    if isinstance(host, Mapping):
        console.print(Text("Host", style="bold"))
        for key, value in host.items():
            console.print(Text(f"{key}: {value}"))
