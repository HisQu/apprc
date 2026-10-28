"""Registry for repository-local AppRC example apps."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass

from cache_only.config.app import MyRC as CACHE_ONLY_RC
from cli_runtime.config.app import MyRC as CLI_RUNTIME_RC
from explicit_env_precedence.config.app import MyRC as PRECEDENCE_RC
from library_client.config.app import MyRC as LIBRARY_CLIENT_RC
from process_env.config.app import MyRC as PROCESS_ENV_RC
from user_dotenv.config.app import MyRC as USER_DOTENV_RC
from user_dotenv_with_workspace.config.app import MyRC as BOTH_RC
from workspace.config.app import MyRC as WORKSPACE_RC

# == Internal ===================================================
import apprc as rc


@dataclass(frozen=True, slots=True)
class ExampleAppSpec:
    """Identify one installed example command and its AppRC environment.

    :param name: Short selector accepted by the lab command.
    :param command_name: Installed console-script name.
    :param app_id: Stable AppRC application identifier.
    :param root_env_key: Environment key that relocates managed files.
    :param env_prefix: Prefix removed from inherited lab environments.
    :param uses_user_dotenv: Whether setup manages a user dotenv.
    :param uses_workspace: Whether the application declares workspace support.
    :param has_managed_paths: Whether any removable AppRC paths are enabled.
    :param required_workspace_key: Required workspace field populated by smoke
        runs, or ``None`` for workspace-free examples.
    """

    name: str
    command_name: str
    app_id: str
    root_env_key: str
    env_prefix: str
    uses_user_dotenv: bool
    uses_workspace: bool
    has_managed_paths: bool
    required_workspace_key: str | None = None


def _spec(
    name: str,
    command_name: str,
    app_rc: rc.AppRC,
    *,
    env_prefix: str,
    required_workspace_key: str | None = None,
) -> ExampleAppSpec:
    """Build a registry row from one public AppRC facade."""
    spec = app_rc.schema
    return ExampleAppSpec(
        name=name,
        command_name=command_name,
        app_id=spec.app_id,
        root_env_key=spec.root_env_key,
        env_prefix=env_prefix,
        uses_user_dotenv=spec.uses_user_dotenv(),
        uses_workspace=spec.uses_workspaces(),
        has_managed_paths=any(
            (
                spec.paths.config,
                spec.paths.appdata,
                spec.paths.cache,
                spec.paths.state,
            )
        ),
        required_workspace_key=required_workspace_key,
    )


EXAMPLE_APPS = (
    _spec(
        "cache-only",
        "apprc-cache-only",
        CACHE_ONLY_RC,
        env_prefix="APPRC_EXAMPLE_CACHE_ONLY_",
    ),
    _spec(
        "process-env",
        "apprc-process-env",
        PROCESS_ENV_RC,
        env_prefix="APPRC_EXAMPLE_PROCESS_",
    ),
    _spec(
        "user-dotenv",
        "apprc-user-dotenv",
        USER_DOTENV_RC,
        env_prefix="APPRC_EXAMPLE_USER_",
    ),
    _spec(
        "workspace",
        "apprc-workspace",
        WORKSPACE_RC,
        env_prefix="APPRC_EXAMPLE_WORKSPACE_",
        required_workspace_key="api_token",
    ),
    _spec(
        "user-dotenv-with-workspace",
        "apprc-user-dotenv-with-workspace",
        BOTH_RC,
        env_prefix="APPRC_EXAMPLE_BOTH_",
        required_workspace_key="api_token",
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
        required_workspace_key="api_token",
    ),
    _spec(
        "library-client",
        "apprc-library-client",
        LIBRARY_CLIENT_RC,
        env_prefix="APPRC_EXAMPLE_LIBRARY_",
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
