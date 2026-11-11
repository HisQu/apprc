"""Private normalization of public config declarations."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import fields
from typing import Any, TypeGuard, cast, get_type_hints

import apprc.utils as ut
from apprc.definition.env_config._validation import validate_config_owner
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.public.config import Config, ConfigBase
from apprc.public.field import (
    _FIELD_DECLARATION_METADATA_KEY,
    _FieldDeclaration,
)


def _validate_config_class(config_type: type[object]) -> None:
    """Reject classes outside the public config inheritance model."""
    if not isinstance(config_type, type):
        raise TypeError("@MyRC.config(...) can only decorate classes.")
    if not issubclass(config_type, ConfigBase):
        raise TypeError(
            f"{config_type.__name__} must inherit from rc.Config or "
            "rc.ConfigBase before it can be registered with "
            "@MyRC.config(...)."
        )


def _is_env_config(config_type: type[object]) -> TypeGuard[type[Config]]:
    """Return whether ``config_type`` reads env-backed AppRC fields."""
    return issubclass(config_type, Config)


def _ensure_dataclass(
    cls: type[Any],
    *,
    init: bool = True,
    repr: bool = True,
) -> type[Any]:
    """Return ``cls`` as a dataclass without reprocessing subclasses."""
    if "__dataclass_fields__" in cls.__dict__:
        return cls
    return dataclasses.dataclass(
        slots=ut.dataclass_slots_preserving_class_identity(cls),
        init=init,
        repr=repr,
    )(cls)


def _collect_field_declarations(
    config_type: type[ConfigBase],
) -> dict[str, _FieldDeclaration]:
    """Collect ``rc.field(...)`` markers from one dataclass."""
    declared_fields: dict[str, _FieldDeclaration] = {}
    for item in fields(config_type):
        spec = item.metadata.get(_FIELD_DECLARATION_METADATA_KEY)
        if spec is None:
            continue
        if not isinstance(spec, _FieldDeclaration):
            raise TypeError(
                f"{_FIELD_DECLARATION_METADATA_KEY!r} metadata must contain "
                f"an AppRC field declaration, got {type(spec).__name__}."
            )
        declared_fields[item.name] = spec
    return declared_fields


def _validate_prefix(
    *,
    config_type: type[ConfigBase],
    config_key: str,
    prefix: str,
    fields: Mapping[str, _FieldDeclaration],
) -> None:
    """Ensure every public env key starts with the config prefix."""
    for field_name, spec in fields.items():
        if spec.env_key.startswith(prefix) and spec.env_key != prefix:
            continue
        raise ValueError(
            f"{config_type.__name__}.{field_name} uses env key "
            f'{spec.env_key}, but config "{config_key}" requires prefix '
            f"{prefix}. Use an env key starting with {prefix} or change the "
            "config prefix."
        )


def _derive_internal_env_suffix(
    *,
    full_env_key: str,
    prefix: str,
) -> str:
    """Return the owner-local env suffix for a public full env key."""
    return full_env_key.removeprefix(prefix)


def _derive_config_fields(
    *,
    config_type: type[ConfigBase],
    prefix: str,
    declared_fields: Mapping[str, _FieldDeclaration],
) -> tuple[ConfigField, ...]:
    """Normalize field declarations after class types become available."""
    type_hints = get_type_hints(config_type, include_extras=True)
    derived: list[ConfigField] = []
    for field_name, spec in declared_fields.items():
        python_type = spec.python_type or type_hints.get(field_name, Any)
        if python_type is Any:
            raise TypeError(
                f"{config_type.__name__}.{field_name} must have a type "
                "annotation or rc.field(..., python_type=...)."
            )
        derived.append(
            ConfigField(
                name=field_name,
                env_var=_derive_internal_env_suffix(
                    full_env_key=spec.env_key,
                    prefix=prefix,
                ),
                python_type=cast(type[Any], python_type),
                default=spec.default,
                default_factory=spec.default_factory,
                packaged_default=spec.packaged_default,
                title=spec.title or "",
                explanation_short=spec.explanation_short,
                explanation_long=spec.explanation_long,
                secret=spec.secret,
                editable=spec.editable,
                required=spec.inferred_required(),
                choices=spec.choices,
                restart_required=spec.restart_required,
            )
        )
    return tuple(derived)


def _humanize_title(key: str) -> str:
    """Return a simple human display title from a config key."""
    words = key.replace("-", "_").split("_")
    return " ".join(word.capitalize() for word in words if word) or key


def _validate_python_only_registration(
    config_type: type[ConfigBase],
    *,
    prefix: str | None,
    declared_fields: Mapping[str, _FieldDeclaration],
) -> None:
    """Validate a ``ConfigBase`` registration."""
    if prefix is not None:
        raise ValueError(
            f"{config_type.__name__} inherits rc.ConfigBase, so it is "
            "Python-only config. Do not pass prefix=... unless the class "
            "inherits rc.Config."
        )
    if not declared_fields:
        return
    field_name = next(iter(declared_fields))
    raise TypeError(
        f"{config_type.__name__}.{field_name} uses rc.field(...), but "
        f"{config_type.__name__} inherits rc.ConfigBase. Use rc.Config "
        "for env-backed config, or use normal Python/dataclass defaults "
        "for rc.ConfigBase."
    )


def _build_owner(
    config_type: type[ConfigBase],
    *,
    key: str,
    title: str,
    prefix: str | None,
    rc_path: tuple[str, ...],
    declared_fields: Mapping[str, _FieldDeclaration],
    requires_workspace: bool,
) -> ConfigOwner:
    """Build an internal owner from registered field declarations."""
    if prefix is None or not prefix:
        raise ValueError(
            f"{config_type.__name__} inherits rc.Config, so "
            f'@MyRC.config("{key}", ...) requires prefix="...".'
        )
    _validate_prefix(
        config_type=config_type,
        config_key=key,
        prefix=prefix,
        fields=declared_fields,
    )
    owner = ConfigOwner(
        key=key,
        title=title,
        env_prefix=prefix,
        rc_path=rc_path,
        fields=_derive_config_fields(
            config_type=config_type,
            prefix=prefix,
            declared_fields=declared_fields,
        ),
        requires_workspace=requires_workspace,
    )
    validate_config_owner(owner)
    return owner
