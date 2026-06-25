"""Owner-field origin tracking helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import fields
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime_config.provenance import ConfigOriginState
from apprc.runtime_config.contract.schema import ConfigOwner


def origin_for_field(
    owner: ConfigOwner,
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
) -> ConfigOriginState:
    """Return the stored owner-field origin or the implicit default origin.

    :param owner: Config owner declaring the field.
    :param origins: Recorded origin states by owner field name.
    :param field_name: Owner-local runtime field name.
    :return: Stored origin state, or the EnvConfig default origin.
    """
    owner.field(field_name)
    return origins.get(
        field_name,
        ConfigOriginState(
            "python_envconfig_default",
            env_key=owner.env_key(field_name),
        ),
    )


def with_field_origin(
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
    origin: ConfigOriginState,
) -> dict[str, ConfigOriginState]:
    """Return a copied owner-field origin map with one replacement.

    :param origins: Existing immutable-by-convention origin map.
    :param field_name: Runtime dataclass field name.
    :param origin: Replacement origin state.
    :return: Copied origin map.
    """
    next_origins = dict(origins)
    next_origins[field_name] = origin
    return next_origins


def python_constructor_field_names(
    config_cls: type[Any],
    owner: ConfigOwner,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> frozenset[str]:
    """Return owner-backed fields supplied directly by Python construction.

    :param config_cls: Runtime config class being constructed.
    :param owner: Config owner declaring env-backed fields.
    :param args: Positional constructor arguments passed to ``__new__``.
    :param kwargs: Keyword constructor arguments passed to ``__new__``.
    :return: Owner-backed field names supplied directly by Python code.
    """
    owner_field_names = frozenset(spec.name for spec in owner.fields)
    positional_init_fields = [
        item.name
        for item in fields(config_cls)
        if item.init and not item.kw_only
    ]
    positional_names = set(positional_init_fields[: len(args)])
    keyword_names = set(kwargs)
    return frozenset((positional_names | keyword_names) & owner_field_names)
