"""Human-readable ``config doctor`` output."""

from __future__ import annotations

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.config.diagnostics import ConfigDoctorPayload
from apprc.config.install_state import ConfigInstallState
from apprc.config.kit import AppConfigKit


def print_config_doctor(
    kit: AppConfigKit,
    payload: ConfigDoctorPayload,
) -> None:
    """Print a human-readable ``config doctor`` report."""
    status_labels = {
        ConfigInstallState.NOT_INSTALLED.value: "not installed",
        ConfigInstallState.INSTALLED_UNHEALTHY.value: (
            "installed but unhealthy"
        ),
        ConfigInstallState.INSTALLED_HEALTHY.value: "installed and healthy",
    }
    status = status_labels[str(payload["install_state"])]
    typer.echo(f"{kit.spec.display_name} config doctor: {status}")
    typer.echo("")
    typer.echo(f"apprc_toml_env_key: {payload['apprc_toml_env_key']}")
    typer.echo(
        f"apprc_toml_env_value: {payload['apprc_toml_env_value'] or '<none>'}"
    )
    typer.echo(f"apprc_toml_path: {payload['apprc_toml_path'] or '<none>'}")
    typer.echo(f"apprc_toml_exists: {payload['apprc_toml_exists']}")
    typer.echo(f"apprc_toml_parse_ok: {payload['apprc_toml_parse_ok']}")
    typer.echo(f"storage_count: {payload['storage_count']}")
    typer.echo(f"default_storage: {payload['default_storage'] or '<none>'}")
    typer.echo(f"selected_storage: {payload['selected_storage'] or '<none>'}")
    typer.echo(
        "selected_storage_source: "
        f"{payload['selected_storage_source'] or '<none>'}"
    )
    typer.echo(
        f"selected_storage_root: {payload['selected_storage_root'] or '<none>'}"
    )
    typer.echo(
        f"selected_local_env: {payload['selected_local_env'] or '<none>'}"
    )

    issues = payload["issues"]
    if issues:
        typer.echo("")
        typer.echo("Issues:")
        for issue in issues:
            typer.echo(f"- {issue}")

        typer.echo("")
        typer.echo("Next steps:")
        for step in payload["next_steps"]:
            typer.echo(f"  {step}")
