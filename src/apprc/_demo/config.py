"""Demo config contract for the standalone ``apprc`` command."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


APPRC_DEMO_OWNER = ConfigOwner(
    key="runtime",
    title="Runtime",
    env_prefix="APPRC_DEMO_",
    rc_path=("runtime",),
    runtime_cls=None,
    fields=(
        config_field(
            "storage_root",
            "D_STORAGE",
            Path,
            default=CONFIG_MISSING,
            title="Storage root",
            explanation_short="Active storage root.",
            explanation_long=(
                "Selected through the AppRC demo storage registry and written "
                "automatically when a storage is registered."
            ),
            editable=False,
            required=True,
        ),
        config_field(
            "model",
            "MODEL",
            str,
            default="demo-model",
            title="Model",
            explanation="Model name used by the demo runtime payload.",
        ),
        config_field(
            "strategy",
            "STRATEGY",
            str,
            default="VECTOR",
            title="Strategy",
            explanation="Selection strategy used by demo commands.",
            choices=("VECTOR", "WEIGHT"),
        ),
        config_field(
            "enabled",
            "ENABLED",
            bool,
            default=True,
            title="Enabled",
            explanation="Turns the demo runtime on or off.",
        ),
        config_field(
            "retry_count",
            "RETRY_COUNT",
            int,
            default=3,
            title="Retry count",
            explanation="Maximum number of demo retries.",
        ),
        config_field(
            "cache_dir",
            "CACHE_DIR",
            Path,
            default=Path("cache"),
            title="Cache directory",
            explanation="Storage-local cache directory used by the demo.",
        ),
        config_field(
            "api_token",
            "API_TOKEN",
            str,
            default=CONFIG_MISSING,
            title="API token",
            explanation_short="Required provider token.",
            explanation_long=(
                "Secret token used to verify that AppRC editors and runtime "
                "payloads redact sensitive values."
            ),
            secret=True,
            required=True,
        ),
    ),
)
APPRC_DEMO_OWNERS = (APPRC_DEMO_OWNER,)

APPRC_DEMO_KIT = AppConfigKit(
    app_name="apprc-demo",
    display_name="AppRC Demo",
    config_package="apprc._demo",
    owners=APPRC_DEMO_OWNERS,
    storage_root_env_key="APPRC_DEMO_D_STORAGE",
    command_name="apprc",
    registry_filename="apprc-demo.toml",
    local_env_filename=".env.apprc-demo",
)


@dataclass(slots=True)
class AppRcDemoState:
    """Root CLI state for the standalone ``apprc`` demo command."""

    env_bootstrap: EnvBootstrapResult | None = None
    storage: str | None = None


def demo_runtime_payload(state: AppRcDemoState) -> dict[str, Any]:
    """Return bootstrap and runtime values for ``apprc config show``.

    :param state: Root command state populated during CLI bootstrap.
    :return: JSON-friendly payload with secret values redacted.
    """
    return {
        "app_name": APPRC_DEMO_KIT.spec.app_name,
        "command_name": APPRC_DEMO_KIT.spec.config_command_name(),
        "display_name": APPRC_DEMO_KIT.spec.display_name,
        "bootstrap": _bootstrap_payload(state.env_bootstrap),
        "runtime": _runtime_values(),
    }


def _bootstrap_payload(
    bootstrap: EnvBootstrapResult | None,
) -> dict[str, Any]:
    """Return JSON-friendly bootstrap state for the current invocation."""
    if bootstrap is None:
        return {
            "shared_env": None,
            "local_env": None,
            "env_file": None,
            "registry_path": str(APPRC_DEMO_KIT.registry_path()),
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


def _runtime_values() -> dict[str, Any]:
    """Return current process config values declared by the demo owner."""
    values: dict[str, Any] = {}
    for owner, spec in iter_config_fields(APPRC_DEMO_OWNERS):
        env_key = owner.env_key(spec.name)
        values[spec.name] = _display_value(spec, os.environ.get(env_key))
    return values


def _display_value(spec: ConfigField, raw_value: str | None) -> Any:
    """Return one runtime value with defaults and secret redaction applied."""
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


def _coerce_display_value(spec: ConfigField, raw_value: str) -> Any:
    """Coerce dotenv strings into the runtime type shown by demo output."""
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


def _json_value(value: Any) -> Any:
    """Return a JSON-friendly representation of one field default."""
    if isinstance(value, Path):
        return str(value)
    return value


def _path_text(path: Path | None) -> str | None:
    """Return a path as text while preserving missing values."""
    return str(path) if path is not None else None
