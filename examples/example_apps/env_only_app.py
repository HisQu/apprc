"""Minimal setup-free AppRC app using only packaged/env values."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc

from example_apps._support import config_values, run_isolated, write_env


@apprc.env_owner(
    key="env_only",
    title="Env Only",
    env_prefix="APPRC_EXAMPLE_ENV_ONLY_",
    rc_path=("env_only",),
)
class EnvOnlyConfig(apprc.EnvConfig):
    """Config fields resolved without AppRC-managed user files."""

    profile: str = apprc.env_field("PROFILE", default="default")
    debug: bool = apprc.env_field("DEBUG", default=False)


KIT = apprc.AppConfigKit.env_only(
    app_name="apprc_example_env_only",
    display_name="Example Env Only",
    config_package="example_apps",
    envs=(EnvOnlyConfig,),
)


def run(root: Path) -> dict[str, object]:
    """Execute the env-only example app.

    :param root: Temporary run directory.
    :return: JSON-friendly summary of the scenario.
    """

    def scenario() -> dict[str, object]:
        explicit_env = write_env(
            root / "profile.env",
            {
                "APPRC_EXAMPLE_ENV_ONLY_DEBUG": "true",
            },
        )
        before = apprc.build_config_doctor_payload(KIT, storage=None)
        bootstrap = KIT.bootstrap(
            env_files=(explicit_env,),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
        config = EnvOnlyConfig()
        return {
            "mode": "env_only",
            "doctor_status": before["status"],
            "shared_env": str(bootstrap.shared_env),
            "explicit_env_files": [str(path) for path in bootstrap.env_files],
            "config": config_values(config),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_ENV_ONLY_",),
        scenario=scenario,
    )


if __name__ == "__main__":
    print(run(Path.cwd() / ".apprc-example-env-only"))
