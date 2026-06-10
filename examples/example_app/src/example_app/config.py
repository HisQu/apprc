"""Example-app config contract for the standalone ``apprc`` command."""

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
    config_field,
    iter_config_fields,
)


EXAMPLE_APP_OWNER = ConfigOwner(
    key="app",
    title="App",
    env_prefix="EXAMPLE_APP_",
    rc_path=("app",),
    fields=(
        config_field(
            "storage_root",
            "D_STORAGE",
            Path,
            default=CONFIG_MISSING,
            title="Storage root",
            explanation_short="Active storage root.",
            explanation_long=(
                "Selected through the example-app storage registry and written "
                "automatically when a storage is registered."
            ),
            editable=False,
            required=True,
        ),
        config_field(
            "profile",
            "PROFILE",
            str,
            default="default",
            title="Profile",
            explanation="Named profile used by the example app.",
        ),
        config_field(
            "mode",
            "MODE",
            str,
            default="AUTO",
            title="Mode",
            explanation="Operating mode selected for example-app commands.",
            choices=("AUTO", "MANUAL"),
        ),
        config_field(
            "enabled",
            "ENABLED",
            bool,
            default=True,
            title="Enabled",
            explanation="Turns the example app on or off.",
        ),
        config_field(
            "retry_count",
            "RETRY_COUNT",
            int,
            default=3,
            title="Retry count",
            explanation="Maximum number of retry attempts.",
        ),
        config_field(
            "cache_dir",
            "CACHE_DIR",
            Path,
            default=Path("cache"),
            title="Cache directory",
            explanation="Storage-local cache directory used by the example app.",
        ),
        config_field(
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
EXAMPLE_APP_OWNERS = (EXAMPLE_APP_OWNER,)

EXAMPLE_APP_KIT = AppConfigKit(
    app_name="example-app",
    display_name="Example App",
    config_package="example_app",
    owners=EXAMPLE_APP_OWNERS,
    storage_root_env_key="EXAMPLE_APP_D_STORAGE",
    command_name="apprc",
    registry_filename="example-app.toml",
    local_env_filename=".env.example-app",
)


@dataclass(slots=True)
class ExampleAppState:
    """Root CLI state for the standalone ``apprc`` example command."""

    env_bootstrap: EnvBootstrapResult | None = None
    storage: str | None = None


def example_config_payload(state: ExampleAppState) -> dict[str, object]:
    """Return bootstrap and config values for ``apprc config show``.

    :param state: Root command state populated during CLI bootstrap.
    :return: JSON-friendly payload with secret values redacted.
    """
    return {
        "app_name": EXAMPLE_APP_KIT.spec.app_name,
        "command_name": EXAMPLE_APP_KIT.spec.config_command_name(),
        "display_name": EXAMPLE_APP_KIT.spec.display_name,
        "bootstrap": _bootstrap_payload(state.env_bootstrap),
        "config": _config_values(),
    }


def _bootstrap_payload(
    bootstrap: EnvBootstrapResult | None,
) -> dict[str, object]:
    """Return JSON-friendly bootstrap state for the current invocation."""
    if bootstrap is None:
        return {
            "shared_env": None,
            "local_env": None,
            "env_file": None,
            "registry_path": str(EXAMPLE_APP_KIT.registry_path()),
            "storage_name": None,
            "storage_root": None,
            "used_default_storage": False,
            "storage_count": 0,
        }
    return {
        "shared_env": _path_text(bootstrap.shared_env),
        "local_env": _path_text(bootstrap.local_env),
        "env_file": _path_text(bootstrap.env_file),
        "registry_path": str(bootstrap.registry_path),
        "storage_name": bootstrap.storage_name,
        "storage_root": _path_text(bootstrap.storage_root),
        "used_default_storage": bootstrap.used_default_storage,
        "storage_count": bootstrap.storage_count,
    }


def _config_values() -> dict[str, object]:
    """Return current process config values declared by the example owner."""
    values: dict[str, object] = {}
    for owner, spec in iter_config_fields(EXAMPLE_APP_OWNERS):
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
    """Coerce dotenv strings into the value type shown by example output."""
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
