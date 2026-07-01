"""Explicit env-file precedence example for storage selectors."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path

# == Internal ================================
import apprc

from example_apps._support import run_isolated, write_env


@apprc.env_owner(
    key="precedence",
    title="Precedence",
    env_prefix="APPRC_EXAMPLE_PRECEDENCE_",
    rc_path=("precedence",),
)
class PrecedenceConfig(apprc.EnvConfig):
    """Config fields used to demonstrate selector precedence."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
    )
    label: str = apprc.env_field("LABEL", default="default")


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc_example_precedence",
    display_name="Example Precedence",
    config_package="example_apps",
    envs=(PrecedenceConfig,),
    storage_env_key="APPRC_EXAMPLE_PRECEDENCE_ROOT",
)


def run(root: Path) -> dict[str, object]:
    """Execute the explicit-env precedence edge case.

    :param root: Temporary run directory.
    :return: JSON-friendly summary of the scenario.
    """

    def scenario() -> dict[str, object]:
        shell_root = root / "shell-storage"
        explicit_root = root / "explicit-storage"
        shell_root.mkdir(parents=True)
        explicit_root.mkdir(parents=True)
        apprc.ensure_storage_env_file(shell_root)
        apprc.ensure_storage_env_file(explicit_root)
        selector_env = write_env(
            root / "selector.env",
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


if __name__ == "__main__":
    print(run(Path.cwd() / ".apprc-example-precedence"))
