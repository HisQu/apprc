"""Private runtime helpers for ``EnvConfig`` instances."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import Field, dataclass, fields
from typing import Any, Mapping

# == Internal ================================
from apprc.runtime_config.fields.loading import (
    load_owner_from_env,
    provided_owner_field_names,
)
from apprc.runtime_config.provenance import (
    ConfigOriginState,
    PythonProvenanceOrigin,
    shell_origin_for_env_value,
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


@dataclass(frozen=True, slots=True)
class EnvBoundField:
    """Parsed env-backed value ready to apply to an ``EnvConfig`` instance.

    :param name: Owner-local runtime field name.
    :param value: Parsed Python value.
    :param origin: Provenance state for the env value.
    """

    name: str
    value: Any
    origin: ConfigOriginState


@dataclass(frozen=True, slots=True)
class EnvBindingResult:
    """Result of resolving current process env for one owner.

    :param values: Parsed values that should be applied to the runtime config.
    :param skipped_python_fields: Python-owned fields protected from env binding.
    """

    values: tuple[EnvBoundField, ...]
    skipped_python_fields: tuple[str, ...] = ()


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


def resolve_owner_defaults_for_instance(
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
    :return: Parsed env values and protected Python field names.
    """
    binding_env, skipped_python_fields = env_values_for_binding(
        owner,
        origins,
        override_python_values=override_python_values,
    )
    loaded = load_owner_from_env(owner, binding_env)
    provided_fields = provided_owner_field_names(owner, binding_env)
    values: list[EnvBoundField] = []
    for spec in owner.fields:
        env_key = owner.env_key(spec.name)
        if spec.name not in provided_fields or not hasattr(loaded, spec.name):
            continue
        loaded_value = getattr(loaded, spec.name)
        validate_owner_field_value(owner, spec.name, loaded_value)
        values.append(
            EnvBoundField(
                name=spec.name,
                value=loaded_value,
                origin=shell_origin_for_env_value(
                    env_key, binding_env[env_key]
                ),
            )
        )
    return EnvBindingResult(
        values=tuple(values),
        skipped_python_fields=tuple(skipped_python_fields),
    )


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
