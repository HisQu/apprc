"""Owner-default and provenance helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import Field, fields
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime_config.provenance import ConfigOriginState
from apprc.runtime_config.contract.schema import ConfigOwner


def origin_for_field(
    owner: ConfigOwner,
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
) -> ConfigOriginState:
    """Return the recorded origin state or the implicit EnvConfig default.

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
    """Return a copied origin map with one updated field.

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
    """Return owner-backed fields provided to the Python constructor.

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
