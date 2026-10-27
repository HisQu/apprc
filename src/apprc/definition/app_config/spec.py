"""Application-level configuration and filesystem capability contract."""

from __future__ import annotations

import re
from dataclasses import dataclass

from apprc.definition.app_config._validation import (
    environment_key_prefix,
    resolve_workspace_selector_env_key,
)
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.env_config._validation import (
    validate_config_owner_inventory,
)
from apprc.definition.env_config.schema import ConfigOwner, owner_for
from apprc.definition.paths import Layout, Paths

DEFAULT_DEFAULTS_DOTENV_FILENAME = "apprc.defaults.env"
DEFAULT_USER_DOTENV_FILENAME = "apprc.user.env"
DEFAULT_WORKSPACE_DOTENV_FILENAME = "apprc.workspace.env"
DEFAULT_APPRC_TOML_FILENAME = "apprc.toml"


@dataclass(frozen=True, slots=True, init=False)
class AppConfigSpec:
    """Immutable declaration; files never enable undeclared capabilities."""

    app_id: str
    display_name: str
    config_package: str | None
    owners: tuple[ConfigOwner, ...]
    envs: tuple[type[object], ...]
    paths: Paths
    layout: Layout | None
    bootstrap_env_prefix: str
    layout_env_key: str
    root_env_key: str
    user_dotenv: UserDotenv | None
    workspaces: Workspaces | None
    setup_next_step: str | None
    workspace_selector_env_key: str | None
    command_name: str | None
    defaults_dotenv_filename: str
    user_dotenv_filename: str
    workspace_dotenv_filename: str
    apprc_toml_filename: str

    def __init__(
        self,
        *,
        app_id: str,
        display_name: str,
        config_package: str | None = None,
        envs: tuple[type[object], ...] = (),
        additional_owners: tuple[ConfigOwner, ...] = (),
        paths: Paths = Paths(),
        layout: Layout | None = None,
        bootstrap_env_prefix: str | None = None,
        user_dotenv: UserDotenv | None = None,
        workspaces: Workspaces | None = None,
        setup_next_step: str | None = None,
        command_name: str | None = None,
    ) -> None:
        """Capture explicitly enabled paths, settings and workspace capabilities.

        :param app_id: One safe, nonempty filename segment.
        :param display_name: Human-readable application name.
        :param config_package: Package containing optional defaults.
        :param envs: Registered environment-backed configuration classes.
        :param additional_owners: Parent-owned imported configuration schemas.
        :param paths: Independent filesystem capability declarations.
        :param layout: Declared placement fallback, or native by default.
        :param bootstrap_env_prefix: Optional prefix for layout and workspace keys.
        :param user_dotenv: Optional user preference persistence.
        :param workspaces: Optional external workspace selection.
        :param setup_next_step: Guidance shown after explicit setup.
        :param command_name: Executable name used in guidance.
        """
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None:
            raise ValueError(
                "app_id must be one safe nonempty filename segment."
            )
        if user_dotenv is not None and not paths.config:
            raise ValueError("UserDotenv requires paths.config=True.")
        if workspaces is not None and workspaces.registry and not paths.config:
            raise ValueError(
                "Registry-backed workspaces require paths.config=True."
            )
        prefix = environment_key_prefix(
            app_id if bootstrap_env_prefix is None else bootstrap_env_prefix
        )
        if not prefix:
            raise ValueError(
                "bootstrap_env_prefix must contain letters or digits."
            )
        owners = (*(owner_for(cls) for cls in envs), *additional_owners)
        validate_config_owner_inventory(owners)
        values = {
            "app_id": app_id,
            "display_name": display_name,
            "config_package": config_package,
            "owners": owners,
            "envs": tuple(envs),
            "paths": paths,
            "layout": layout,
            "bootstrap_env_prefix": prefix,
            "layout_env_key": f"{prefix}_LAYOUT",
            "root_env_key": f"{prefix}_ROOT",
            "user_dotenv": user_dotenv,
            "workspaces": workspaces,
            "setup_next_step": setup_next_step,
            "workspace_selector_env_key": (
                resolve_workspace_selector_env_key(
                    app_id=prefix, selector_env_key=workspaces.selector_env_key
                )
                if workspaces is not None
                else None
            ),
            "command_name": command_name,
            "defaults_dotenv_filename": DEFAULT_DEFAULTS_DOTENV_FILENAME,
            "user_dotenv_filename": DEFAULT_USER_DOTENV_FILENAME,
            "workspace_dotenv_filename": DEFAULT_WORKSPACE_DOTENV_FILENAME,
            "apprc_toml_filename": DEFAULT_APPRC_TOML_FILENAME,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def config_command_name(self) -> str:
        """Return the executable name used in generated instructions."""
        return self.command_name or self.app_id

    def uses_workspaces(self) -> bool:
        """Return whether external workspace selection is declared."""
        return self.workspaces is not None

    def uses_user_dotenv(self) -> bool:
        """Return whether user preference persistence is declared."""
        return self.user_dotenv is not None

    def require_workspace_selector_env_key(self) -> str:
        """Return the declared selector key or reject absent workspaces."""
        if self.workspace_selector_env_key is None:
            raise ValueError(
                f"{self.display_name} does not use AppRC workspaces."
            )
        return self.workspace_selector_env_key

    def require_workspaces(self) -> Workspaces:
        """Return the workspace declaration or reject absent workspaces."""
        if self.workspaces is None:
            raise ValueError(
                f"{self.display_name} does not use AppRC workspaces."
            )
        return self.workspaces

    def require_user_dotenv(self) -> UserDotenv:
        """Return the user dotenv declaration or reject absent persistence."""
        if self.user_dotenv is None:
            raise ValueError(
                f"{self.display_name} does not use an AppRC user dotenv."
            )
        return self.user_dotenv
