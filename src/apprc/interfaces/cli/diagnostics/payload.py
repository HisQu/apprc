"""Build read-only configuration diagnostics for the CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from apprc.definition.resolution import ResolveOptions
from apprc.public.app_rc import AppRC
from apprc.services.manager import ConfigManager
from apprc.user_files.app_home.application import AppFiles


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One read-only configuration check.

    :param name: Stable check identifier.
    :param status: One of ``ok``, ``warning``, or ``error``.
    :param message: Explanation of the observed condition.
    """

    name: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class ConfigDoctorPayload:
    """Machine-readable results from ``config doctor``.

    :param status: Aggregate ``ok``, ``warning``, or ``error`` status.
    :param checks: Configuration-only checks; no workspace or legacy paths.
    """

    status: str
    checks: tuple[DiagnosticCheck, ...]

    def to_payload(self) -> dict[str, Any]:
        """Return the report using the stable JSON field names."""
        return {
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


def build_config_doctor_payload(
    apprc: "AppRC",
    *,
    manager: ConfigManager | None = None,
    config_group_name: str = "config",
) -> ConfigDoctorPayload:
    """Inspect declared configuration without initializing or migrating files.

    :param apprc: Application config facade.
    :param manager: Invocation-bound manager and captured paths.
    :param config_group_name: Mounted config command name for guidance.
    :return: Structured, zero-write configuration diagnostics.
    """
    del config_group_name
    active_manager = manager or apprc.manage(ResolveOptions())
    spec = apprc.schema
    checks: list[DiagnosticCheck] = []
    config_dir = active_manager.paths.config_dir
    if config_dir is None:
        checks.append(
            DiagnosticCheck(
                "config_directory",
                "ok",
                "No configuration directory is declared.",
            )
        )
    elif config_dir.is_dir():
        checks.append(
            DiagnosticCheck(
                "config_directory",
                "ok",
                f"Configuration directory exists: {config_dir}",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "config_directory",
                "warning",
                f"Configuration directory is not initialized: {config_dir}",
            )
        )

    if spec.uses_user_dotenv():
        user_dotenv = AppFiles(spec, active_manager.paths).user_dotenv_path()
        if user_dotenv.is_file():
            checks.append(
                DiagnosticCheck(
                    "user_dotenv", "ok", f"User dotenv exists: {user_dotenv}"
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    "user_dotenv",
                    "warning",
                    f"User dotenv is not initialized: {user_dotenv}. Run config setup.",
                )
            )

    inspection = active_manager.inspect()
    if inspection.issues:
        checks.append(
            DiagnosticCheck(
                "configuration", "error", "; ".join(inspection.issues)
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "configuration",
                "ok",
                "Declared configuration values are valid.",
            )
        )

    status = (
        "error"
        if any(check.status == "error" for check in checks)
        else "warning"
        if any(check.status == "warning" for check in checks)
        else "ok"
    )
    return ConfigDoctorPayload(status=status, checks=tuple(checks))
