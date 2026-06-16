"""Example App config contract for the standalone ``apprc`` command."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.config import (
    CONFIG_MISSING,
    AppConfigKit,
    ConfigField,
    ConfigOwner,
    EnvBootstrapResult,
    iter_config_fields,
)


APPRC_EXAMPLE_APP_OWNER = ConfigOwner(
    key="app",
    title="App",
    env_prefix="APPRC_EXAMPLE_APP_",
    rc_path=("app",),
    fields=(
        ConfigField(
            "storage_root",
            "STORAGE",
            Path,
            default=CONFIG_MISSING,
            title="Storage root",
            explanation_short="Active storage root.",
            explanation_long=(
                "Selected through APPRC_EXAMPLE_APP_STORAGE and written "
                "automatically during runtime bootstrap."
            ),
            editable=False,
            required=True,
        ),
        ConfigField(
            "profile",
            "PROFILE",
            str,
            default="default",
            title="Profile",
            explanation_short="Named profile used by the example app.",
        ),
        ConfigField(
            "mode",
            "MODE",
            str,
            default="AUTO",
            title="Mode",
            explanation_short=(
                "Operating mode selected for Example App commands."
            ),
            choices=("AUTO", "MANUAL"),
        ),
        ConfigField(
            "enabled",
            "ENABLED",
            bool,
            default=True,
            title="Enabled",
            explanation_short="Turns the example app on or off.",
        ),
        ConfigField(
            "retry_count",
            "RETRY_COUNT",
            int,
            default=3,
            title="Retry count",
            explanation_short="Maximum number of retry attempts.",
        ),
        ConfigField(
            "cache_dir",
            "CACHE_DIR",
            Path,
            default=Path("cache"),
            title="Cache directory",
            explanation_short=(
                "Storage-local cache directory used by the example app."
            ),
        ),
        ConfigField(
            "access_token",
            "ACCESS_TOKEN",
            str,
            default=CONFIG_MISSING,
            title="Access token",
            explanation_short="Required secret token.",
            explanation_long=(
                "Secret token used to verify that AppRC editors and example "
                "payloads redact sensitive values."
            ),
            secret=True,
            required=True,
        ),
    ),
)
APPRC_EXAMPLE_APP_OWNERS = (APPRC_EXAMPLE_APP_OWNER,)

APPRC_EXAMPLE_APP_KIT = AppConfigKit(
    app_name="apprc_example_app",
    display_name="Example App",
    config_package="apprc_example_app",
    owners=APPRC_EXAMPLE_APP_OWNERS,
    storage_env_key="APPRC_EXAMPLE_APP_STORAGE",
    command_name="apprc",
    apprc_toml_filename="apprc_example_app.apprc.toml",
    local_env_filename=".env.apprc_example_app",
)


@dataclass(slots=True)
class ApprcExampleAppState:
    """Root CLI state for the standalone ``apprc`` Example App command."""

    env_bootstrap: EnvBootstrapResult | None = None
    storage: str | None = None


def apprc_example_app_config_payload(
    state: ApprcExampleAppState,
) -> dict[str, object]:
    """Return bootstrap and config values for ``apprc config show``.

    :param state: Root command state populated during CLI bootstrap.
    :return: JSON-friendly payload with secret values redacted.
    """
    return {
        "app_name": APPRC_EXAMPLE_APP_KIT.spec.app_name,
        "command_name": APPRC_EXAMPLE_APP_KIT.spec.config_command_name(),
        "display_name": APPRC_EXAMPLE_APP_KIT.spec.display_name,
        "bootstrap": _bootstrap_payload(state.env_bootstrap),
        "config": _config_values(),
    }


def _bootstrap_payload(
    bootstrap: EnvBootstrapResult | None,
) -> dict[str, object]:
    """Return JSON-friendly bootstrap state for the current invocation."""
    apprc_toml_path = APPRC_EXAMPLE_APP_KIT.spec.optional_apprc_toml_path()
    if bootstrap is None:
        return {
            "shared_env": None,
            "local_env": None,
            "env_file": None,
            "apprc_toml_path": str(apprc_toml_path)
            if apprc_toml_path
            else None,
            "storage_selector_source": None,
            "storage_selector_value": None,
            "storage_name": None,
            "storage_root": None,
            "storage_count": 0,
        }
    return {
        "shared_env": _path_text(bootstrap.shared_env),
        "local_env": _path_text(bootstrap.local_env),
        "env_file": _path_text(bootstrap.env_file),
        "apprc_toml_path": _path_text(bootstrap.apprc_toml_path),
        "storage_selector_source": bootstrap.storage_selector_source,
        "storage_selector_value": bootstrap.storage_selector_value,
        "storage_name": bootstrap.storage_name,
        "storage_root": _path_text(bootstrap.storage_root),
        "storage_count": bootstrap.storage_count,
    }


def _config_values() -> dict[str, object]:
    """Return current process config values declared by the Example App owner."""
    values: dict[str, object] = {}
    for owner, spec in iter_config_fields(APPRC_EXAMPLE_APP_OWNERS):
        env_key = owner.env_key(spec.name)
        values[spec.name] = _display_value(spec, os.environ.get(env_key))
    return values


def _display_value(spec: ConfigField, raw_value: str | None) -> object:
    """Return one config value with defaults and secret redaction applied."""
    if spec.secret:
        if raw_value:
            return "<redacted>"
        if spec.required:
            return "<required>"
        return None
    if raw_value is not None:
        return _coerce_display_value(spec, raw_value)
    if spec.default is CONFIG_MISSING:
        return "<required>" if spec.required else None
    return _json_value(spec.default)


def _coerce_display_value(spec: ConfigField, raw_value: str) -> object:
    """Coerce dotenv strings into the value type shown by Example App output."""
    if spec.python_type is bool:
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        return raw_value
    if spec.python_type is int:
        try:
            return int(raw_value)
        except ValueError:
            return raw_value
    if spec.python_type is float:
        try:
            return float(raw_value)
        except ValueError:
            return raw_value
    if spec.python_type is Path:
        return raw_value
    return raw_value


def _json_value(value: object) -> object:
    """Return a JSON-friendly representation of one field default."""
    if isinstance(value, Path):
        return str(value)
    return value


def _path_text(path: Path | None) -> str | None:
    """Return a path as text while preserving missing values."""
    return str(path) if path is not None else None
