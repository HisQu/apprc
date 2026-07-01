"""Python dataclass provenance resolution for runtime config objects."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import Field, fields, is_dataclass
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime.provenance.model import (
    ConfigOriginState,
    ConfigProvenance,
    source_for_origin,
)


def public_config_fields(instance: Any) -> tuple[Field[Any], ...]:
    """Return public dataclass fields included in config provenance.

    :param instance: Runtime config object to inspect.
    :return: Public fields, excluding private and AppRC-internal fields.
    """
    if not is_dataclass(instance):
        return ()
    return tuple(
        item
        for item in fields(instance)
        if not item.name.startswith("_") and not item.metadata.get("internal")
    )


def constructor_field_origins(
    config_cls: type[Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> dict[str, ConfigOriginState]:
    """Return provenance origins for public constructor-provided fields.

    :param config_cls: Config class being constructed.
    :param args: Positional constructor arguments passed to ``__new__``.
    :param kwargs: Keyword constructor arguments passed to ``__new__``.
    :return: Field-origin mapping for values supplied by Python callers.
    """
    if not is_dataclass(config_cls):
        return {}
    public_fields = {
        item.name: item
        for item in fields(config_cls)
        if not item.name.startswith("_") and not item.metadata.get("internal")
    }
    positional_init_fields = [
        item.name
        for item in public_fields.values()
        if item.init and not item.kw_only
    ]
    provided_names = set(positional_init_fields[: len(args)]) | set(kwargs)
    return {
        field_name: ConfigOriginState("python_constructor_argument")
        for field_name in provided_names & set(public_fields)
    }


def with_field_origin(
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
    origin: ConfigOriginState,
) -> dict[str, ConfigOriginState]:
    """Return a copied origin map with one updated field.

    :param origins: Existing immutable-by-convention origin map.
    :param field_name: Runtime dataclass field name.
    :param origin: Replacement origin state.
    :return: Copied field-origin mapping.
    """
    next_origins = dict(origins)
    next_origins[field_name] = origin
    return next_origins


def set_field_origin(
    instance: Any,
    field_name: str,
    origin: ConfigOriginState,
) -> None:
    """Record BaseConfig-level provenance for one field.

    :param instance: Config object whose internal origin map should be updated.
    :param field_name: Runtime dataclass field name.
    :param origin: Replacement origin state.
    """
    origins = getattr(instance, "_apprc_provenance_origins", {})
    object.__setattr__(
        instance,
        "_apprc_provenance_origins",
        with_field_origin(origins, field_name, origin),
    )


def base_config_provenance_of(
    instance: Any, field_name: str
) -> ConfigProvenance:
    """Build provenance for one public BaseConfig dataclass field.

    :param instance: Runtime config object.
    :param field_name: Public dataclass field name.
    :return: Resolved provenance metadata.
    :raises KeyError: If ``field_name`` is not public config state.
    """
    field_by_name = {item.name: item for item in public_config_fields(instance)}
    if field_name not in field_by_name:
        raise KeyError(field_name)
    field_def = field_by_name[field_name]
    origins = getattr(instance, "_apprc_provenance_origins", {})
    state = origins.get(
        field_name,
        ConfigOriginState("python_baseconfig_default"),
    )
    return ConfigProvenance(
        field_name=field_name,
        source=source_for_origin(state.origin),
        origin=state.origin,
        value=getattr(instance, field_name),
        secret=not field_def.repr,
        env_key=state.env_key,
        path=state.path,
    )


def provenance_of(instance: Any, field_name: str) -> ConfigProvenance:
    """Return provenance for one config field via the instance resolver hook.

    :param instance: Runtime config object.
    :param field_name: Public dataclass field name.
    :return: Resolved provenance metadata.
    """
    return instance._build_config_provenance(field_name)


def provenance(instance: Any) -> dict[str, ConfigProvenance]:
    """Return provenance for every public config field.

    :param instance: Runtime config object.
    :return: Field-name keyed provenance records.
    """
    return {
        item.name: provenance_of(instance, item.name)
        for item in public_config_fields(instance)
    }
