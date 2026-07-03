"""App-wide config AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from app_wide_config.config import (
    AppWideConfigExampleConfig,
    CONFIG_SECTIONS,
    KIT,
)
from _example_apps_utils._support import (
    build_standard_app,
    config_values,
    run_isolated,
)


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the app-wide config example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        bundle_cls=AppWideConfigExampleConfig,
        section_getter=lambda config: config.app_wide,
        help_text="Exercise AppRC's app-wide config capability mode.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact app-wide config scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        before = rc.cli.build_config_doctor_payload(KIT, storage=None)
        app_wide_env = KIT.spec.ensure_app_wide_env()
        rc.files.set_env_file_value(
            path=app_wide_env,
            reference="workers",
            raw_value="4",
            owners=CONFIG_SECTIONS,
            layer_name=KIT.spec.app_wide_env_filename,
        )
        after = rc.cli.build_config_doctor_payload(KIT, storage=None)
        KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
        config = AppWideConfigExampleConfig()
        return {
            "mode": "app_wide_config",
            "doctor_before": before.status,
            "doctor_after": after.status,
            "app_wide_env": str(app_wide_env),
            "config": config_values(config.app_wide),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_APP_WIDE_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the app-wide config example CLI."""
    app()


if __name__ == "__main__":
    main()
