"""Process-wide environment provenance recorded by bootstrap."""

from __future__ import annotations

# == Standard Library ========================
from typing import Mapping

# == Internal ================================
from apprc.runtime_config.provenance.model import (
    ConfigOriginState,
    EnvValueOrigin,
)

_ENV_VALUE_ORIGINS: dict[str, EnvValueOrigin] = {}


def register_env_value_origins(
    origins: Mapping[str, EnvValueOrigin],
    *,
    clear_keys: set[str],
) -> None:
    """Replace bootstrap provenance for one app-owned env-key inventory.

    :param origins: New env-value origin records keyed by env key.
    :param clear_keys: App-owned env keys whose previous records are stale.
    """
    for key in clear_keys:
        _ENV_VALUE_ORIGINS.pop(key, None)
    _ENV_VALUE_ORIGINS.update(origins)


def env_value_origin(env_key: str) -> EnvValueOrigin | None:
    """Return bootstrap provenance for one env key when AppRC knows it.

    :param env_key: Full environment variable name.
    :return: Bootstrap origin metadata, or ``None``.
    """
    return _ENV_VALUE_ORIGINS.get(env_key)


def shell_origin_for_env_value(
    env_key: str,
    value: str,
) -> ConfigOriginState:
    """Return the provenance state for one env value bound by EnvConfig.

    :param env_key: Full environment variable name.
    :param value: Raw string value read by the runtime binder.
    :return: Field origin state with dotenv path when known.
    """
    recorded = env_value_origin(env_key)
    if recorded is None:
        return ConfigOriginState("shell_export_variable", env_key=env_key)
    if recorded.value != value:
        return ConfigOriginState(
            "python_process_environment_mutation",
            env_key=env_key,
        )
    return ConfigOriginState(
        recorded.origin,
        env_key=env_key,
        path=recorded.path,
    )
