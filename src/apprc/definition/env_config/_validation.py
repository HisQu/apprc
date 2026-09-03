"""Validation helpers for normalized AppRC config schema objects."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Any

# == Internal ================================
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.env_config.sentinels import CONFIG_MISSING

SUPPORTED_ENV_FIELD_TYPES: tuple[type[Any], ...] = (
    str,
    bool,
    int,
    float,
    Path,
)


def validate_config_owner(owner: ConfigOwner) -> None:
    """Reject one malformed owner schema.

    :param owner: Normalized owner derived from an ``EnvConfig`` class.
    :raises TypeError: If field types are unsupported.
    :raises ValueError: If owner or field identifiers collide or are empty.
    """
    _require_non_empty(owner.key, "ConfigOwner.key")
    _require_non_empty(owner.title, f"{owner.key}.title")
    _require_non_empty(owner.env_prefix, f"{owner.key}.env_prefix")
    if not owner.rc_path or any(not item for item in owner.rc_path):
        raise ValueError(f"{owner.key}.rc_path must contain non-empty parts.")

    field_names: set[str] = set()
    env_vars: set[str] = set()
    config_paths: set[tuple[str, ...]] = set()
    for spec in owner.fields:
        validate_config_field(spec)
        _check_unique(field_names, spec.name, f"{owner.key} field")
        _check_unique(env_vars, spec.env_var, f"{owner.key} env var")
        _check_unique(
            config_paths,
            owner.config_path(spec.name),
            f"{owner.key} config path",
        )


def validate_config_owner_inventory(owners: tuple[ConfigOwner, ...]) -> None:
    """Reject duplicate owner, env-key, or config-path declarations.

    :param owners: Full normalized owner inventory for one application.
    :raises ValueError: If two owners declare the same owner key, env key, or
        structured config path.
    """
    owner_keys: set[str] = set()
    env_keys: set[str] = set()
    config_paths: set[tuple[str, ...]] = set()
    for owner in owners:
        validate_config_owner(owner)
        _check_unique(owner_keys, owner.key, "owner key")
        for spec in owner.fields:
            _check_unique(env_keys, owner.env_key(spec.name), "env key")
            _check_unique(
                config_paths,
                owner.config_path(spec.name),
                "config path",
            )


def validate_config_field(spec: ConfigField) -> None:
    """Reject one malformed field schema.

    :param spec: Normalized field declaration.
    :raises TypeError: If its runtime type is unsupported.
    :raises ValueError: If identifiers, defaults, or choices are invalid.
    """
    _require_non_empty(spec.name, "ConfigField.name")
    _require_non_empty(spec.env_var, f"{spec.name}.env_var")
    if spec.python_type not in SUPPORTED_ENV_FIELD_TYPES:
        supported = ", ".join(
            item.__name__ for item in SUPPORTED_ENV_FIELD_TYPES
        )
        raise TypeError(
            f"{spec.name} uses unsupported env field type "
            f"{spec.python_type!r}; supported types are: {supported}."
        )
    if (
        spec.default is not CONFIG_MISSING
        and spec.default_factory is not CONFIG_MISSING
    ):
        raise ValueError(
            f"{spec.name} cannot declare both default and default_factory."
        )
    if spec.required and spec.has_default():
        raise ValueError(
            f"{spec.name} is required and cannot declare a Python default or "
            "default_factory. Use packaged_default to describe a value "
            "shipped in apprc.defaults.env."
        )
    if spec.default is not CONFIG_MISSING:
        validate_python_field_value(spec, spec.default)
    if spec.choices:
        if spec.python_type is not str:
            raise TypeError(
                f"{spec.name} choices are supported only for str fields."
            )
        if any(not isinstance(choice, str) for choice in spec.choices):
            raise TypeError(f"{spec.name} choices must all be strings.")


def validate_python_field_value(spec: ConfigField, value: Any) -> None:
    """Validate a direct Python value without coercing it.

    :param spec: Field whose Python type and choices should be enforced.
    :param value: Candidate value supplied by constructor, assignment, or owner
        default.
    :raises TypeError: If ``value`` is not the declared Python type.
    :raises ValueError: If ``value`` is outside declared choices.
    """
    if value is CONFIG_MISSING:
        return
    if not _matches_python_type(spec.python_type, value):
        raise TypeError(
            f"{spec.name} must be {spec.python_type.__name__}; got "
            f"{type(value).__name__}."
        )
    if spec.choices and value not in spec.choices:
        choices = ", ".join(spec.choices)
        raise ValueError(f"{spec.name} must be one of: {choices}.")


def _matches_python_type(python_type: type[Any], value: Any) -> bool:
    """Return whether ``value`` is exactly compatible with ``python_type``."""
    if python_type is bool:
        return type(value) is bool
    if python_type is int:
        return type(value) is int
    if python_type is float:
        return type(value) is float
    return isinstance(value, python_type)


def _require_non_empty(value: str, label: str) -> None:
    """Raise when a schema identifier is empty or whitespace-only."""
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{label} must be a non-empty string.")


def _check_unique[T](seen: set[T], value: T, label: str) -> None:
    """Raise when ``value`` already appeared in ``seen``."""
    if value in seen:
        raise ValueError(f"Duplicate {label}: {value!r}.")
    seen.add(value)
