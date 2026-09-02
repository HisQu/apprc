"""App-wide storage AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from app_wide_storage.config import (
    AppWideStorageExampleConfig,
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
    """Return the app-wide storage example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        bundle_cls=AppWideStorageExampleConfig,
        section_getter=lambda config: config.app_wide_storage,
        help_text="Exercise per-user and storage-local AppRC config.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact app-wide storage scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        app_env = KIT.spec.ensure_app_env()
        rc.files.set_env_file_value(
            path=app_env,
            reference="region",
            raw_value="eu",
            owners=CONFIG_SECTIONS,
            layer_name=KIT.spec.app_env_filename,
        )
        apprc_toml = KIT.spec.ensure_apprc_toml()
        storage_root = root / "named-storage"
        rc.storage.register_storage(
            name="alpha",
            root=storage_root,
            path=apprc_toml,
            storage_env_filename=KIT.spec.require_storage().env_filename,
        )
        rc.files.set_storage_env_value(
            storage_root=storage_root,
            reference="access_token",
            raw_value="named-storage-secret",
            owners=CONFIG_SECTIONS,
            storage_env_filename=KIT.spec.require_storage().env_filename,
        )
        doctor = rc.cli.build_config_doctor_payload(KIT, storage="alpha")
        bootstrap = KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="alpha",
        )
        config = AppWideStorageExampleConfig()
        return {
            "mode": "app_wide_storage",
            "doctor_status": doctor.status,
            "apprc_toml": str(apprc_toml),
            "selected_storage_name": bootstrap.storage_name,
            "selected_storage_root": str(bootstrap.storage_root),
            "config": config_values(config.app_wide_storage),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_APP_WIDE_STORAGE_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the app-wide storage example CLI."""
    app()


if __name__ == "__main__":
    main()
