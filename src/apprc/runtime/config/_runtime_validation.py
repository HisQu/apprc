"""Owner-backed runtime value validation helpers."""

from __future__ import annotations

# == Standard Library ========================
from typing import Any, Mapping

# == Internal ================================
from apprc.definition.env_config.schema import (
    ConfigField,
    ConfigOwner,
    field_env_key,
)
from apprc.definition.env_config._validation import (
    validate_python_field_value,
)
from apprc.definition.env_config.sentinels import ENV_FIELD_MISSING
from apprc.runtime.provenance import ConfigOriginState


def validate_python_constructor_fields(
    instance: Any,
    owner: ConfigOwner,
    field_origins: Mapping[str, ConfigOriginState],
) -> None:
    """Validate constructor-provided values against owner metadata.

    :param instance: Runtime config instance being initialized.
    :param owner: Config owner declaring env-backed fields.
    :param field_origins: Current owner-backed provenance map.
    """
    specs = {spec.name: spec for spec in owner.fields}
    for field_name, state in field_origins.items():
        if state.origin != "python_constructor_argument":
            continue
        validate_resolved_field(
            owner,
            specs[field_name],
            getattr(instance, field_name),
        )


def validate_required_fields(instance: Any, owner: ConfigOwner) -> None:
    """Raise when required owner-backed fields remain unresolved.

    :param instance: Runtime config instance to inspect.
    :param owner: Config owner declaring env-backed fields.
    :raises RuntimeError: If any required env value is missing.
    """
    missing_keys = [
        field_env_key(owner, spec)
        for spec in owner.fields
        if getattr(instance, spec.name) is ENV_FIELD_MISSING
    ]
    if not missing_keys:
        return
    joined = ", ".join(missing_keys)
    raise RuntimeError(
        f"Missing required config value(s) for {instance.__class__.__name__}: "
        f"{joined}. Provide Python constructor values or current-process "
        "os.environ values before constructing this config."
    )


def validate_all_owner_values(instance: Any, owner: ConfigOwner) -> None:
    """Validate all resolved owner-backed values on ``instance``.

    :param instance: Runtime config instance to inspect.
    :param owner: Config owner declaring env-backed fields.
    """
    for spec in owner.fields:
        value = getattr(instance, spec.name)
        validate_resolved_field(owner, spec, value)


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
    validate_resolved_field(owner, owner.field(field_name), value)


def validate_resolved_field(
    owner: ConfigOwner, spec: ConfigField, value: Any
) -> None:
    """Validate a value using its resolved field and the owner's env key."""
    if value is ENV_FIELD_MISSING:
        return
    try:
        validate_python_field_value(spec, value)
    except TypeError as exc:
        env_key = field_env_key(owner, spec)
        raise TypeError(
            f"{env_key} must be {spec.python_type.__name__}; got "
            f"{type(value).__name__}."
        ) from exc
    except ValueError as exc:
        if spec.choices and value not in spec.choices:
            choices = ", ".join(spec.choices)
            env_key = field_env_key(owner, spec)
            raise ValueError(
                f"{env_key}={value!r} is invalid; {spec.name} must be one "
                f"of: {choices}."
            ) from exc
        raise
