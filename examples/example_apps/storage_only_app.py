"""Storage-required AppRC app selected by a direct storage path."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == Internal ================================
import apprc

from example_apps._support import config_values, run_isolated


@apprc.env_owner(
    key="storage_only",
    title="Storage Only",
    env_prefix="APPRC_EXAMPLE_STORAGE_",
    rc_path=("storage_only",),
)
class StorageOnlyConfig(apprc.EnvConfig):
    """Config fields resolved from a selected storage root."""

    storage_root: Path = apprc.env_field(
        "ROOT",
        editable=False,
        required=True,
    )
    profile: str = apprc.env_field("PROFILE", default="default")
    api_token: str = apprc.env_field("API_TOKEN", required=True, secret=True)


KIT = apprc.AppConfigKit.storage_only(
    app_name="apprc_example_storage_only",
    display_name="Example Storage Only",
    config_package="example_apps",
    envs=(StorageOnlyConfig,),
    storage_env_key="APPRC_EXAMPLE_STORAGE_ROOT",
)

OWNERS = (apprc.config_owner_for(StorageOnlyConfig),)


def run(root: Path) -> dict[str, object]:
    """Execute the direct-path storage example app.

    :param root: Temporary run directory.
    :return: JSON-friendly summary of the scenario.
    """

    def scenario() -> dict[str, object]:
        storage_root = root / "storage"
        storage_root.mkdir(parents=True)
        apprc.ensure_storage_env_file(storage_root)
        apprc.set_storage_env_value(
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


if __name__ == "__main__":
    print(run(Path.cwd() / ".apprc-example-storage-only"))
