"""Human-readable AppRC diagnostic output."""

from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING

from rich.text import Text

from apprc.interfaces._terminal_console import cli_console
from apprc.interfaces._terminal_styles import (
    ERROR_STYLE,
    SUCCESS_STYLE,
    WARNING_STYLE,
    LABEL_STYLE,
    STAGE_STYLE,
    path_text,
)
from apprc.interfaces.cli.diagnostics.payload import ConfigDoctorPayload

if TYPE_CHECKING:
    from typer import Context

from apprc.public.app_rc import AppRC


def _status(status: object) -> Text:
    """Render a literal diagnostic label and its severity."""
    state = str(status)
    if state in {"ok", "ready", "valid"}:
        style = SUCCESS_STYLE
    elif state in {"error", "invalid", "incomplete", "provisional"}:
        style = ERROR_STYLE
    elif state == "warning":
        style = WARNING_STYLE
    else:
        style = LABEL_STYLE
    return Text(state, style=style)


def _check(status: object, name: object, message: object) -> Text:
    return Text.assemble("[", _status(status), f"] {name}: {message}")


def _path(value: object) -> Text:
    return path_text(value) if isinstance(value, str) else Text(str(value))


def print_config_doctor(
    apprc: AppRC,
    payload: ConfigDoctorPayload,
) -> None:
    """Print configuration-only checks with their structured statuses.

    :param apprc: Application config facade.
    :param payload: Configuration diagnostic result.
    """
    console = cli_console()
    console.print(
        Text.assemble(
            (f"{apprc.schema.display_name} config doctor: ", STAGE_STYLE),
            _status(payload.status),
        )
    )
    for check in payload.checks:
        console.print(_check(check.status, check.name, check.message))


def print_config_paths(
    apprc: AppRC,
    payload: ConfigDoctorPayload,
) -> None:
    """Print the config group's read-only diagnostic summary.

    :param apprc: Application config facade.
    :param payload: Configuration diagnostic result.
    """
    console = cli_console()
    console.print(
        Text(f"{apprc.schema.display_name} config paths", style=STAGE_STYLE)
    )
    for check in payload.checks:
        console.print(_check(check.status, check.name, check.message))


def print_doctor_report(
    payload: dict[str, object], *, ctx: Context | None = None
) -> None:
    """Render the aggregate maintenance report for interactive terminal use.

    :param payload: Unified maintenance doctor result.
    """
    console = cli_console(ctx)
    console.print(
        Text.assemble(
            ("AppRC doctor: ", STAGE_STYLE), _status(payload["status"])
        )
    )
    installation = payload.get("installation")
    if isinstance(installation, Mapping):
        console.print(
            Text.assemble(
                "Installation: ",
                _status(installation.get("status")),
                " (",
                _path(installation.get("directory")),
                ")",
            )
        )
        diagnostics = installation.get("diagnostics")
        if isinstance(diagnostics, list):
            for diagnostic in diagnostics:
                if isinstance(diagnostic, Mapping):
                    console.print(
                        Text(
                            f"[{diagnostic.get('code')}] {diagnostic.get('message')}",
                            style=ERROR_STYLE,
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
                    _check(
                        check.get("status"),
                        check.get("name"),
                        check.get("message"),
                    )
                )
    details = payload.get("details")
    if not isinstance(details, Mapping):
        return
    paths = details.get("paths")
    if isinstance(paths, Mapping):
        console.print(Text("Paths", style=STAGE_STYLE))
        for key in ("layout", "root", "source"):
            if key in paths:
                console.print(
                    Text.assemble(
                        f"{key}: ",
                        _path(paths[key]) if key == "root" else str(paths[key]),
                    )
                )
        path_map = paths.get("paths")
        exists_map = paths.get("exists")
        if isinstance(path_map, Mapping):
            for name, path in path_map.items():
                exists = (
                    exists_map.get(name)
                    if isinstance(exists_map, Mapping)
                    else None
                )
                console.print(
                    Text.assemble(
                        f"{name}: ", _path(path), f" (exists: {exists})"
                    )
                )
    configuration = details.get("configuration")
    if isinstance(configuration, Mapping):
        console.print(
            Text.assemble(
                ("Configuration: ", STAGE_STYLE),
                _status(configuration.get("status")),
            )
        )
        config_checks = configuration.get("checks")
        if isinstance(config_checks, list):
            for check in config_checks:
                if isinstance(check, Mapping):
                    console.print(
                        _check(
                            check.get("status"),
                            check.get("name"),
                            check.get("message"),
                        )
                    )
    resources = details.get("resources")
    if isinstance(resources, Mapping):
        console.print(Text("Resources", style=STAGE_STYLE))
        for name, resource in resources.items():
            if not isinstance(resource, Mapping):
                continue
            console.print(
                Text.assemble(
                    f"{name}: root=",
                    _path(resource.get("root")),
                    f", exists={resource.get('exists')}, "
                    f"ownership={resource.get('ownership')}, "
                    f"operations={resource.get('operations')}",
                )
            )
            provider = resource.get("provider")
            if isinstance(provider, Mapping):
                for key, value in provider.items():
                    console.print(Text(f"  {key}: {value}"))
    host = details.get("host")
    if isinstance(host, Mapping):
        console.print(Text("Host", style=STAGE_STYLE))
        for key, value in host.items():
            console.print(Text(f"{key}: {value}"))
