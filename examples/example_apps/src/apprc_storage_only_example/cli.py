"""Storage-only AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from apprc_example_apps._support import (
    build_standard_app,
    config_values,
    run_isolated,
)
from apprc_storage_only_example.config import KIT, OWNERS, StorageOnlyConfig


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the storage-only example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        config_cls=StorageOnlyConfig,
        help_text="Exercise AppRC's storage-only capability mode.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute a compact storage-only scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        storage_root = root / "storage"
        storage_root.mkdir(parents=True)
        rc.files.ensure_storage_env_file(storage_root)
        rc.files.set_storage_env_value(
            storage_root=storage_root,
            reference="api_token",
            raw_value="storage-secret",
            owners=OWNERS,
        )
        bootstrap = KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(storage_root),
        )
        config = StorageOnlyConfig()
        return {
            "mode": "storage_only",
            "selected_storage_root": str(bootstrap.storage_root),
            "storage_env": str(bootstrap.storage_env),
            "config": config_values(config),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_STORAGE_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the storage-only example CLI."""
    app()


if __name__ == "__main__":
    main()
