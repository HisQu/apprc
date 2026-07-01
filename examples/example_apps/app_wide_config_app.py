"""App-wide AppRC app that requires a config-home dotenv file."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc

from example_apps._support import config_values, run_isolated


@apprc.env_owner(
    key="app_wide",
    title="App Wide",
    env_prefix="APPRC_EXAMPLE_APP_WIDE_",
    rc_path=("app_wide",),
)
class AppWideConfig(apprc.EnvConfig):
    """Config fields resolved from the app-wide dotenv layer."""

    region: str = apprc.env_field("REGION", default="local")
    workers: int = apprc.env_field("WORKERS", default=1)


KIT = apprc.AppConfigKit.app_wide_config(
    app_name="apprc_example_app_wide",
    display_name="Example App Wide",
    config_package="example_apps",
    envs=(AppWideConfig,),
)

OWNERS = (apprc.config_owner_for(AppWideConfig),)


def run(root: Path) -> dict[str, object]:
    """Execute the app-wide config example app.

    :param root: Temporary run directory.
    :return: JSON-friendly summary of the scenario.
    """

    def scenario() -> dict[str, object]:
        before = apprc.build_config_doctor_payload(KIT, storage=None)
        app_wide_env = KIT.spec.ensure_app_wide_env()
        apprc.set_env_file_value(
            path=app_wide_env,
            reference="workers",
            raw_value="4",
            owners=OWNERS,
            layer_name=KIT.spec.app_wide_env_filename,
        )
        after = apprc.build_config_doctor_payload(KIT, storage=None)
        KIT.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
        config = AppWideConfig()
        return {
            "mode": "app_wide_config",
            "doctor_before": before["status"],
            "doctor_after": after["status"],
            "app_wide_env": str(app_wide_env),
            "config": config_values(config),
        }

    return run_isolated(
        root,
        env_prefixes=("APPRC_EXAMPLE_APP_WIDE_",),
        scenario=scenario,
    )


if __name__ == "__main__":
    print(run(Path.cwd() / ".apprc-example-app-wide"))
