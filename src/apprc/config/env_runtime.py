"""Private runtime helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import Field
from typing import Any, Mapping

# == Internal ================================
from apprc.config.loading import provided_owner_field_names
from apprc.config.provenance import ConfigFieldSourceKey
from apprc.config.schema import ConfigOwner
from apprc.config.schema_validation import validate_python_field_value
from apprc.config.sentinels import ENV_FIELD_MISSING


def source_for_field(
    owner: ConfigOwner,
    sources: Mapping[str, ConfigFieldSourceKey],
    field_name: str,
) -> ConfigFieldSourceKey:
    """Return the recorded source key or the implicit owner default."""
    owner.field(field_name)
    return sources.get(field_name, "owner_default")


def with_field_source(
    sources: Mapping[str, ConfigFieldSourceKey],
    field_name: str,
    source: ConfigFieldSourceKey,
) -> dict[str, ConfigFieldSourceKey]:
    """Return a copied source map with one updated field."""
    next_sources = dict(sources)
    next_sources[field_name] = source
    return next_sources


def protected_field_names(
    sources: Mapping[str, ConfigFieldSourceKey],
) -> frozenset[str]:
    """Return fields whose Python values should beat normal env binding."""
    return frozenset(
        field_name
        for field_name, source in sources.items()
        if source in {"python_arg", "python_assignment"}
    )


def env_values_for_binding(
    owner: ConfigOwner,
    sources: Mapping[str, ConfigFieldSourceKey],
    *,
    override_python_values: bool,
    values: Mapping[str, str] | None = None,
) -> tuple[Mapping[str, str], list[str]]:
    """Return an env mapping with protected Python fields removed."""
    env_values = os.environ if values is None else values
    if override_python_values:
        return env_values, []
    skipped_fields = sorted(
        provided_owner_field_names(owner, env_values)
        & protected_field_names(sources)
    )
    if not skipped_fields:
        return env_values, []
    skipped_keys = {owner.env_key(field_name) for field_name in skipped_fields}
    return (
        {
            key: value
            for key, value in env_values.items()
            if key not in skipped_keys
        },
        skipped_fields,
    )


def resolve_owner_defaults(
    instance: Any,
    owner: ConfigOwner,
    *,
    dataclass_fields: Mapping[str, Field[Any]],
    field_sources: Mapping[str, ConfigFieldSourceKey],
    copy_value: Any,
) -> dict[str, ConfigFieldSourceKey]:
    """Apply owner defaults to fields not supplied as Python arguments."""
    next_sources = dict(field_sources)
    for spec in owner.fields:
        if source_for_field(owner, next_sources, spec.name) == "python_arg":
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
        next_sources[spec.name] = "owner_default"
    return next_sources


def validate_owner_field_value(
    owner: ConfigOwner,
    field_name: str,
    value: Any,
) -> None:
    """Validate one resolved owner-backed runtime value.

    :param owner: Config owner declaring the field.
    :param field_name: Owner-local runtime field name.
    :param value: Candidate Python or env-loaded value.
    :raises TypeError: If ``value`` is not the declared Python type.
    :raises ValueError: If ``value`` is outside declared choices.
    """
    spec = owner.field(field_name)
    if value is ENV_FIELD_MISSING:
        return
    try:
        validate_python_field_value(spec, value)
    except TypeError as exc:
        env_key = owner.env_key(field_name)
        raise TypeError(
            f"{env_key} must be {spec.python_type.__name__}; got "
            f"{type(value).__name__}."
        ) from exc
    except ValueError as exc:
        if spec.choices and value not in spec.choices:
            choices = ", ".join(spec.choices)
            env_key = owner.env_key(field_name)
            raise ValueError(
                f"{env_key}={value!r} is invalid; {field_name} must be one "
                f"of: {choices}."
            ) from exc
        raise
