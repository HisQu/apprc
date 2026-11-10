"""Owner-field origin tracking helpers for AppRC config instances."""

from __future__ import annotations

# == Standard Library ========================
from typing import Mapping

# == Internal ================================
from apprc.runtime.provenance import ConfigOriginState
from apprc.definition.env_config.schema import ConfigOwner


def origin_for_field(
    owner: ConfigOwner,
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
) -> ConfigOriginState:
    """Return the stored owner-field origin or the implicit default origin.

    :param owner: Config owner declaring the field.
    :param origins: Recorded origin states by owner field name.
    :param field_name: Owner-local runtime field name.
    :return: Stored origin state, or the config default origin.
    """
    owner.field(field_name)
    return origins.get(
        field_name,
        ConfigOriginState(
            "python_config_default",
            env_key=owner.env_key(field_name),
        ),
    )
