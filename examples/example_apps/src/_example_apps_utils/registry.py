"""Registry for repository-local AppRC example apps."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass

# == Internal ===================================================
import apprc as rc
from cli_runtime.config import MyRC as CLI_RUNTIME_RC
from config_only.config import MyRC as CONFIG_ONLY_RC
from config_with_storage.config import MyRC as CONFIG_WITH_STORAGE_RC
from explicit_env_precedence.config import MyRC as PRECEDENCE_RC


@dataclass(frozen=True, slots=True)
class ExampleAppSpec:
    """Identify one installed example command and its AppRC environment.

    :param name: Short selector accepted by the lab command.
    :param command_name: Installed console-script name.
    :param app_id: Stable AppRC application identifier.
    :param apprc_dir_env_key: Environment key that relocates managed files.
    :param env_prefix: Prefix removed from inherited lab environments.
    :param uses_storage: Whether the application declares storage support.
    :param required_storage_key: Required storage field populated by smoke
        runs, or ``None`` for storage-free examples.
    """

    name: str
    command_name: str
    app_id: str
    apprc_dir_env_key: str
    env_prefix: str
    uses_storage: bool
    required_storage_key: str | None = None


def _spec(
    name: str,
    command_name: str,
    app_rc: rc.AppRC,
    *,
    env_prefix: str,
    required_storage_key: str | None = None,
) -> ExampleAppSpec:
    """Build a registry row from one public AppRC facade."""
    spec = app_rc.spec
    return ExampleAppSpec(
        name=name,
        command_name=command_name,
        app_id=spec.app_id,
        apprc_dir_env_key=spec.apprc_dir_env_key,
        env_prefix=env_prefix,
        uses_storage=spec.uses_storage(),
        required_storage_key=required_storage_key,
    )


EXAMPLE_APPS = (
    _spec(
        "config-only",
        "apprc-config-only",
        CONFIG_ONLY_RC,
        env_prefix="APPRC_EXAMPLE_CONFIG_",
    ),
    _spec(
        "config-with-storage",
        "apprc-config-with-storage",
        CONFIG_WITH_STORAGE_RC,
        env_prefix="APPRC_EXAMPLE_STORAGE_",
        required_storage_key="api_token",
    ),
    _spec(
        "explicit-env-precedence",
        "apprc-explicit-env-precedence",
        PRECEDENCE_RC,
        env_prefix="APPRC_EXAMPLE_PRECEDENCE_",
    ),
    _spec(
        "cli-runtime",
        "apprc-cli-runtime",
        CLI_RUNTIME_RC,
        env_prefix="APPRC_EXAMPLE_RUNTIME_",
        required_storage_key="api_token",
    ),
)


def example_app_specs() -> tuple[ExampleAppSpec, ...]:
    """Return all repository-local example app definitions."""
    return EXAMPLE_APPS


def example_app(name: str) -> ExampleAppSpec:
    """Return the selected example definition.

    :param name: Lab selector.
    :return: Matching example definition.
    :raises KeyError: If no example has that selector.
    """
    return {spec.name: spec for spec in EXAMPLE_APPS}[name]
