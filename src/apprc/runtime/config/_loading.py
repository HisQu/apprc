"""Typed loading helpers for normalized AppRC config owners."""

from __future__ import annotations

# == Standard Library ========================
import os
from typing import Any, Mapping

# == 3rd Party ===============================

# == Internal ================================
from apprc.definition.env_config.schema import ConfigOwner
from apprc.definition.env_config.conversion import (
    OwnerMappingLoader,
    load_owner_from_sources,
)


def load_owner_from_env(
    owner: ConfigOwner,
    values: Mapping[str, str] | None = None,
) -> Any:
    """Load one owner from current process OS env variables only.

    Reads values from ``os.environ`` by default. Passing ``values`` is for
    internals that need an env-like current-process snapshot with some keys
    deliberately filtered. This does not load dotenv files or application
    config layers. Explicit resolution supplies a captured mapping when
    application layers should participate in construction.

    :param owner: Owner spec to load.
    :param values: Optional env-like mapping. Defaults to ``os.environ``.
    :return: A generated settings dataclass instance.
    """
    env_values = os.environ if values is None else values
    return load_owner_from_sources(
        owner,
        (
            OwnerMappingLoader(
                owner,
                env_values,
                source_name="process-env",
            ),
        ),
    )


def provided_owner_field_names(
    owner: ConfigOwner,
    values: Mapping[str, str],
) -> set[str]:
    """Return owner-local field names present in an env-like mapping."""
    return {
        spec.name for spec in owner.fields if owner.env_key(spec.name) in values
    }


def owner_env_mapping(
    owner: ConfigOwner,
    values: object,
    *,
    prefixed: bool = True,
    include_empty: bool = False,
) -> dict[str, str]:
    """Serialize owner-backed values as env key/value strings."""

    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    env: dict[str, str] = {}
    for spec in owner.fields:
        value = getattr(values, spec.name)
        if value is None and not include_empty:
            continue
        key = owner.env_key(spec.name) if prefixed else spec.env_var
        env[key] = _stringify(value)
    return env
