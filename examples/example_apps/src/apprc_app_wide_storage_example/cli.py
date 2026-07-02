"""App-wide storage AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc
from apprc_app_wide_storage_example.config import (
    AppWideStorageConfig,
    KIT,
    OWNERS,
)
from apprc_example_apps._support import (
    build_standard_app,
    config_values,
    run_isolated,
)


def build_app(
    *,
    args_provider: apprc.CliArgvProvider | None = None,
    editor_app_cls: type[apprc.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the app-wide storage example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        config_cls=AppWideStorageConfig,
        help_text="Exercise AppRC's app-wide storage capability mode.",
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
        app_wide_env = KIT.spec.ensure_app_wide_env()
        apprc.set_env_file_value(
            path=app_wide_env,
            reference="region",
            raw_value="eu",
            owners=OWNERS,
            layer_name=KIT.spec.app_wide_env_filename,
        )
        index_path = KIT.spec.ensure_index_file()
        storage_root = root / "named-storage"
        apprc.register_storage(
            name="alpha",
            root=storage_root,
            path=index_path,
            storage_env_filename=KIT.spec.storage_env_filename,
        )
        apprc.set_storage_env_value(
            storage_root=storage_root,
            reference="access_token",
            raw_value="named-storage-secret",
            owners=OWNERS,
            storage_env_filename=KIT.spec.storage_env_filename,
        )
        doctor = apprc.build_config_doctor_payload(KIT, storage="alpha")
        bootstrap = KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="alpha",
        )
        config = AppWideStorageConfig()
        return {
            "mode": "app_wide_storage",
            "doctor_status": doctor.status,
            "index_path": str(index_path),
            "selected_storage_name": bootstrap.storage_name,
            "selected_storage_root": str(bootstrap.storage_root),
            "config": config_values(config),
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
