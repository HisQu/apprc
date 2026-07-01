"""App-wide plus named-storage AppRC app."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc

from example_apps._support import config_values, run_isolated


@apprc.env_owner(
    key="app_wide_storage",
    title="App Wide Storage",
    env_prefix="APPRC_EXAMPLE_APP_WIDE_STORAGE_",
    rc_path=("app_wide_storage",),
)
class AppWideStorageConfig(apprc.EnvConfig):
    """Config fields resolved from app-wide and storage layers."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
    )
    region: str = apprc.env_field("REGION", default="local")
    access_token: str = apprc.env_field(
        "ACCESS_TOKEN",
        required=True,
        secret=True,
    )


KIT = apprc.AppConfigKit.app_wide_storage(
    app_name="apprc_example_app_wide_storage",
    display_name="Example App Wide Storage",
    config_package="example_apps",
    envs=(AppWideStorageConfig,),
    storage_env_key="APPRC_EXAMPLE_APP_WIDE_STORAGE_ROOT",
)

OWNERS = (apprc.config_owner_for(AppWideStorageConfig),)


def run(root: Path) -> dict[str, object]:
    """Execute the app-wide storage example app.

    :param root: Temporary run directory.
    :return: JSON-friendly summary of the scenario.
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
            "doctor_status": doctor["status"],
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


if __name__ == "__main__":
    print(run(Path.cwd() / ".apprc-example-app-wide-storage"))
