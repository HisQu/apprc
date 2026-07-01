"""Owner-default helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import Field, fields
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime.provenance import ConfigOriginState
from apprc.definition.env_config.schema import ConfigOwner
from apprc.definition.env_config._origins import origin_for_field


def resolve_owner_defaults(
    instance: Any,
    owner: ConfigOwner,
    *,
    dataclass_fields: Mapping[str, Field[Any]],
    field_origins: Mapping[str, ConfigOriginState],
    copy_value: Any,
) -> dict[str, ConfigOriginState]:
    """Apply EnvConfig defaults to fields not supplied by Python callers.

    :param instance: Runtime config instance being initialized.
    :param owner: Config owner declaring env-backed fields.
    :param dataclass_fields: Runtime dataclass fields by name.
    :param field_origins: Existing owner-field provenance map.
    :param copy_value: Value copier used to avoid shared mutable defaults.
    :return: Updated origin map after resolving defaults.
    """
    next_origins = dict(field_origins)
    for spec in owner.fields:
        if (
            origin_for_field(owner, next_origins, spec.name).origin
            == "python_constructor_argument"
        ):
            continue
        if spec.name not in dataclass_fields:
            raise RuntimeError(
                f"{instance.__class__.__name__}.{spec.name} is declared by "
                f"{owner.key} but missing from the runtime dataclass."
            )
        if not spec.has_default():
            continue
        object.__setattr__(
            instance,
            spec.name,
            copy_value(spec.resolve_default(), {}),
        )
        next_origins[spec.name] = ConfigOriginState(
            "python_envconfig_default",
            env_key=owner.env_key(spec.name),
        )
    return next_origins


def resolve_instance_owner_defaults(
    instance: Any,
    owner: ConfigOwner,
    *,
    field_origins: Mapping[str, ConfigOriginState],
    copy_value: Any,
) -> dict[str, ConfigOriginState]:
    """Apply owner defaults using dataclass metadata from ``instance``.

    :param instance: Runtime config instance being initialized.
    :param owner: Config owner declaring env-backed fields.
    :param field_origins: Existing owner-field provenance map.
    :param copy_value: Value copier used to avoid shared mutable defaults.
    :return: Updated origin map after resolving defaults.
    """
    return resolve_owner_defaults(
        instance,
        owner,
        dataclass_fields={item.name: item for item in fields(instance)},
        field_origins=field_origins,
        copy_value=copy_value,
    )
