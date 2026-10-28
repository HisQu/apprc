"""Human-readable ``config doctor`` output."""

from __future__ import annotations

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
