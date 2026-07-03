"""Explicit env-file precedence AppRC example CLI."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc as rc
from apprc_example_apps._support import (
    build_standard_app,
    run_isolated,
    write_env,
)
from apprc_explicit_env_precedence_example.config import (
    ExplicitEnvPrecedenceConfig,
    KIT,
)


def build_app(
    *,
    args_provider: rc.cli.CliArgvProvider | None = None,
    editor_app_cls: type[rc.cli.ConfigEditorApp] | None = None,
) -> typer.Typer:
    """Return the explicit env precedence example CLI.

    :param args_provider: Optional command-token provider for tests.
    :param editor_app_cls: Optional editor replacement for tests.
    :return: Typer application.
    """
    return build_standard_app(
        kit=KIT,
        config_cls=ExplicitEnvPrecedenceConfig,
        help_text="Exercise explicit env-file storage selector precedence.",
        args_provider=args_provider,
        editor_app_cls=editor_app_cls,
    )


app = build_app()


def run_demo(root: Path) -> dict[str, object]:
    """Execute the explicit env-file precedence scenario.

    :param root: Temporary run directory.
    :return: JSON-friendly scenario summary.
    """

    def scenario() -> dict[str, object]:
        shell_root = root / "shell-storage"
        explicit_root = root / "explicit-storage"
        shell_root.mkdir(parents=True)
        explicit_root.mkdir(parents=True)
        rc.files.ensure_storage_env_file(shell_root)
        rc.files.ensure_storage_env_file(explicit_root)
        selector_env = write_env(
            root / ".env",
            {"APPRC_EXAMPLE_PRECEDENCE_ROOT": str(explicit_root)},
        )
        os.environ["APPRC_EXAMPLE_PRECEDENCE_ROOT"] = str(shell_root)
        shell_wins = KIT.bootstrap(
            env_files=(selector_env,),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
        explicit_wins = KIT.bootstrap(
            env_files=(selector_env,),
            env_file_overrides_os_environ=True,
            load_dotenv_layers=True,
            storage=None,
        )
        return {
            "mode": "explicit_env_precedence",
            "shell_wins": str(shell_wins.storage_root),
            "explicit_wins": str(explicit_wins.storage_root),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_PRECEDENCE_",),
        scenario=scenario,
    )


def main() -> None:
    """Run the explicit env precedence example CLI."""
    app()


if __name__ == "__main__":
    main()
