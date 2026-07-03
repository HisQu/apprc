"""Env-only AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from apprc_env_only_example.config import EnvOnlyConfig, KIT
from apprc_example_apps._support import (
    build_standard_app,
    config_values,
    run_isolated,
    write_env,
)


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the env-only example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        config_cls=EnvOnlyConfig,
        help_text="Exercise AppRC's env-only capability mode.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact env-only scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        explicit_env = write_env(
            root / ".env",
            {
                "APPRC_EXAMPLE_ENV_ONLY_DEBUG": "true",
            },
        )
        doctor = rc.cli.build_config_doctor_payload(KIT, storage=None)
        bootstrap = KIT.bootstrap(
            env_files=(explicit_env,),
            env_file_overrides_os_environ=True,
            load_dotenv_layers=True,
            storage=None,
        )
        config = EnvOnlyConfig()
        return {
            "mode": "env_only",
            "doctor_status": doctor.status,
            "shared_env": str(bootstrap.shared_env),
            "explicit_env_files": [str(path) for path in bootstrap.env_files],
            "config": config_values(config),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_ENV_ONLY_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the env-only example CLI."""
    app()


if __name__ == "__main__":
    main()
