"""Owner-backed runtime value validation helpers."""

from __future__ import annotations

# == Standard Library ========================
from typing import Any, Mapping

# == Internal ================================
from apprc.definition.env_config.schema import ConfigOwner
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
    for field_name, state in field_origins.items():
        if state.origin != "python_constructor_argument":
            continue
        validate_owner_field_value(
            owner,
            field_name,
            getattr(instance, field_name),
        )


def validate_required_fields(instance: Any, owner: ConfigOwner) -> None:
    """Raise when required owner-backed fields remain unresolved.

    :param instance: Runtime config instance to inspect.
    :param owner: Config owner declaring env-backed fields.
    :raises RuntimeError: If any required env value is missing.
    """
    missing_keys = [
        owner.env_key(spec.name)
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
        if value is ENV_FIELD_MISSING:
            continue
        validate_owner_field_value(owner, spec.name, value)


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
