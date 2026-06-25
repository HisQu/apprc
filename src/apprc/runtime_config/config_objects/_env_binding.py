"""Current-process env binding helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from typing import Mapping

# == Internal ================================
from apprc.runtime_config.config_objects._env_validation import (
    validate_owner_field_value,
)
from apprc.runtime_config._env_loading import (
    load_owner_from_env,
    provided_owner_field_names,
)
from apprc.runtime_config.provenance import (
    ConfigOriginState,
    PythonProvenanceOrigin,
    shell_origin_for_env_value,
)
from apprc.runtime_config.contract.schema import ConfigOwner

ENV_BINDING_PROTECTED_ORIGINS: frozenset[PythonProvenanceOrigin] = frozenset(
    (
        "python_constructor_argument",
        "python_runtime_assignment",
        "python_scoped_override",
    )
)


@dataclass(frozen=True, slots=True)
class EnvBoundField:
    """Parsed env-backed field ready to apply to an ``EnvConfig`` instance.

    :param name: Owner-local runtime field name.
    :param value: Parsed Python value.
    :param origin: Provenance state for the env value.
    """

    name: str
    value: object
    origin: ConfigOriginState


@dataclass(frozen=True, slots=True)
class EnvBindingResult:
    """Result of resolving current process env for one owner.

    :param bound_fields: Parsed fields that should be applied to the runtime
        config.
    :param skipped_python_fields: Python-owned fields protected from env binding.
    """

    bound_fields: tuple[EnvBoundField, ...]
    skipped_python_fields: tuple[str, ...] = ()


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


def bind_owner_from_env(
    owner: ConfigOwner,
    origins: Mapping[str, ConfigOriginState],
    *,
    override_python_values: bool,
) -> EnvBindingResult:
    """Resolve env-provided values for an owner without mutating config state.

    :param owner: Config owner declaring env-backed fields.
    :param origins: Current owner-backed provenance map.
    :param override_python_values: Whether env may replace Python-owned values.
    :return: Parsed env fields and protected Python field names.
    """
    binding_env, skipped_python_fields = env_values_for_binding(
        owner,
        origins,
        override_python_values=override_python_values,
    )
    loaded = load_owner_from_env(owner, binding_env)
    provided_fields = provided_owner_field_names(owner, binding_env)
    bound_fields: list[EnvBoundField] = []
    for spec in owner.fields:
        if spec.name not in provided_fields:
            continue
        env_key = owner.env_key(spec.name)
        loaded_value = getattr(loaded, spec.name)
        validate_owner_field_value(owner, spec.name, loaded_value)
        bound_fields.append(
            EnvBoundField(
                name=spec.name,
                value=loaded_value,
                origin=shell_origin_for_env_value(
                    env_key, binding_env[env_key]
                ),
            )
        )
    return EnvBindingResult(
        bound_fields=tuple(bound_fields),
        skipped_python_fields=tuple(skipped_python_fields),
    )
