"""Private runtime helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import Field
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime_config.fields.loading import provided_owner_field_names
from apprc.runtime_config.provenance import (
    ConfigOriginState,
    PythonProvenanceOrigin,
)
from apprc.runtime_config.contract.schema import ConfigOwner
from apprc.runtime_config.contract.schema_validation import (
    validate_python_field_value,
)
from apprc.runtime_config.contract.sentinels import ENV_FIELD_MISSING

ENV_BINDING_PROTECTED_ORIGINS: frozenset[PythonProvenanceOrigin] = frozenset(
    (
        "python_constructor_argument",
        "python_runtime_assignment",
        "python_scoped_override",
    )
)


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


def protected_field_names(
    origins: Mapping[str, ConfigOriginState],
) -> frozenset[str]:
    """Return fields whose Python values should beat normal env binding.

    :param origins: Recorded origin states by owner field name.
    :return: Field names protected from env binding by default.
    """
    return frozenset(
        field_name
        for field_name, state in origins.items()
        if state.origin in ENV_BINDING_PROTECTED_ORIGINS
    )


def env_values_for_binding(
    owner: ConfigOwner,
    origins: Mapping[str, ConfigOriginState],
    *,
    override_python_values: bool,
    values: Mapping[str, str] | None = None,
) -> tuple[Mapping[str, str], list[str]]:
    """Return an env mapping with protected Python fields removed.

    :param owner: Config owner declaring env-backed fields.
    :param origins: Recorded origin states by owner field name.
    :param override_python_values: Whether env may replace Python-owned values.
    :param values: Optional env-like mapping for tests and internals.
    :return: Filtered env mapping and skipped Python-owned field names.
    """
    env_values = os.environ if values is None else values
    if override_python_values:
        return env_values, []
    skipped_fields = sorted(
        provided_owner_field_names(owner, env_values)
        & protected_field_names(origins)
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
