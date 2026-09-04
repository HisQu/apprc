"""Storage-backed AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from _example_apps_utils._support import (
    build_standard_app,
    config_values,
    run_isolated,
)
from config_with_storage.config import (
    CONFIG_SECTIONS,
    KIT,
    ConfigWithStorageExampleConfig,
)


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the config-with-storage example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        bundle_cls=ConfigWithStorageExampleConfig,
        section_getter=lambda config: config.app,
        help_text="Exercise AppRC with one selected storage path.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact config-with-storage scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        os.environ[KIT.spec.apprc_dir_env_key] = str(root / "apprc")
        storage_root = root / "storage"
        storage_root.mkdir(parents=True)
        rc.files.ensure_storage_dotenv_file(storage_root)
        rc.files.set_storage_dotenv_value(
            storage_root=storage_root,
            reference="api_token",
            raw_value="storage-secret",
            owners=CONFIG_SECTIONS,
        )
        rc.storage.register_storage(
            name="default",
            root=storage_root,
            path=KIT.spec.preferred_apprc_toml_path(),
        )
        bootstrap = KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="default",
        )
        config = ConfigWithStorageExampleConfig()
        return {
            "scenario": "config_with_storage",
            "selected_storage_root": str(bootstrap.storage_root),
            "storage_dotenv": str(bootstrap.storage_dotenv),
            "config": config_values(config.app),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_STORAGE_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the config-with-storage example CLI."""
    app()


if __name__ == "__main__":
    main()
