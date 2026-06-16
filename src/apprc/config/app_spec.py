"""Application-level configuration contract."""

from __future__ import annotations

from dataclasses import dataclass

# == Internal ================================
from apprc.config.environment import EnvBootstrapSpec
from apprc.config.schema import ConfigOwner


@dataclass(frozen=True, slots=True)
class AppConfigSpec:
    """Complete reusable configuration contract for one application.

    Applications declare this once, then :class:`AppConfigKit` derives the
    optional AppRC TOML registry path, dotenv bootstrap spec, local-env
    behavior, config doctor diagnostics, and optional config CLI from it.

    :param app_name: Lowercase application name used in env var derivation.
    :param display_name: Human-readable application name for terminal output.
    :param config_package: Package containing the packaged shared dotenv file.
    :param owners: Config owner inventory for editable and documented fields.
    :param storage_env_key: Env key that stores the active storage selector.
    :param command_name: Optional executable name shown in generated CLI copy.
    :param apprc_toml_filename: Per-user AppRC TOML filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    owners: tuple[ConfigOwner, ...]
    storage_env_key: str
    command_name: str | None = None
    apprc_toml_filename: str = "app.apprc.toml"
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def config_command_name(self) -> str:
        """Return the executable name shown in generated config commands."""
        return self.command_name or self.app_name

    def env_bootstrap_spec(self) -> EnvBootstrapSpec:
        """Return the narrower dotenv bootstrap contract."""
        return EnvBootstrapSpec(
            app_name=self.app_name,
            display_name=self.display_name,
            config_package=self.config_package,
            storage_env_key=self.storage_env_key,
            apprc_toml_filename=self.apprc_toml_filename,
            shared_env_filename=self.shared_env_filename,
            local_env_filename=self.local_env_filename,
        )
