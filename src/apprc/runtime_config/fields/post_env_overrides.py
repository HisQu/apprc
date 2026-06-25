"""Post-env Python override policy for resolved runtime configs."""

from __future__ import annotations

# == Standard Library ========================
from typing import Any, Mapping, Protocol, TypeVar, cast

# == Internal ================================
import apprc.runtime_config.provenance as provenance_api
import apprc.runtime_config.fields.state_transfer as state_transfer


class _RuntimeConfigProtocol(Protocol):
    """Runtime config surface consumed by post-env override helpers."""

    def _assign_existing_value(
        self,
        key: str,
        value: Any,
        *,
        origin: provenance_api.PythonProvenanceOrigin,
    ) -> None:
        """Assign an existing field through the config's validation hooks."""


_ConfigT = TypeVar("_ConfigT", bound=_RuntimeConfigProtocol)


def create_or_update(
    config_type: type[_ConfigT],
    cfg: _ConfigT | None = None,
    **overrides: Any,
) -> _ConfigT:
    """Return an effective persistent config instance.

    :param config_type: Runtime config class to construct when ``cfg`` is absent.
    :param cfg: Existing config instance to update, or ``None`` to build one.
    :param overrides: Field-name overrides. ``None`` means no override.
    :return: Created or updated persistent config instance.
    :raises KeyError: If an override names a non-public config field.
    """
    target = config_type if cfg is None else cfg
    diagnostic_type = config_type if cfg is None else type(cfg)
    _validate_matching_config_type(config_type, cfg)
    _validate_public_override_names(diagnostic_type, target, overrides)
    values = _without_skipped_none(overrides)
    if cfg is None:
        constructor = cast(Any, config_type)
        return cast(_ConfigT, constructor(**values))
    for key, value in values.items():
        setattr(cfg, key, value)
    return cfg


def scoped(
    config: _ConfigT,
    overrides: Mapping[str, Any] | None = None,
    *,
    skip_none: bool = True,
    kwargs: Mapping[str, Any] | None = None,
) -> _ConfigT:
    """Return a request-local clone with public field overrides applied.

    :param config: Already resolved runtime config instance.
    :param overrides: Optional mapping of public field-name overrides.
    :param skip_none: Whether ``None`` values mean no override.
    :param kwargs: Additional public field-name overrides; these win over
        ``overrides``.
    :return: Cloned config with scoped override values applied.
    :raises KeyError: If an override names a non-public config field.
    """
    candidate_values = _merge_overrides(overrides, kwargs or {})
    _validate_public_override_names(type(config), config, candidate_values)
    values = _without_skipped_none(candidate_values, skip_none=skip_none)
    clone = state_transfer.isolated_deep_clone(config)
    for key, value in values.items():
        clone._assign_existing_value(
            key,
            value,
            origin="python_scoped_override",
        )
    return clone


def scoped_from(
    config: _ConfigT,
    values: Mapping[str, Any],
    *,
    skip_none: bool = True,
) -> _ConfigT:
    """Return a scoped clone from a larger local-value mapping.

    :param config: Already resolved runtime config instance.
    :param values: Mapping that may contain public config field names.
    :param skip_none: Whether ``None`` values mean no override.
    :return: Cloned config with matching scoped override values applied.
    """
    public_field_names = _public_config_field_names(config)
    return scoped(
        config,
        {
            key: value
            for key, value in values.items()
            if key in public_field_names
        },
        skip_none=skip_none,
    )


def _validate_matching_config_type(
    config_type: type[Any],
    cfg: Any | None,
) -> None:
    """Raise when an existing config does not match the class facade.

    :param config_type: Config class used to call ``create_or_update``.
    :param cfg: Existing config instance, if any.
    :raises TypeError: If ``cfg`` is not an instance of ``config_type``.
    """
    if cfg is None or isinstance(cfg, config_type):
        return
    raise TypeError(
        f"cfg must be an instance of {config_type.__name__}; "
        f"got {type(cfg).__name__}."
    )


def _public_config_field_names(instance: Any) -> frozenset[str]:
    """Return public config field names for override validation.

    :param instance: Runtime config object or config class to inspect.
    :return: Public field names, excluding private and internal state.
    """
    return frozenset(
        item.name for item in provenance_api.public_config_fields(instance)
    )


def _validate_public_override_names(
    config_type: type[Any],
    target: Any,
    values: Mapping[str, Any],
) -> None:
    """Raise when an override does not name public config state.

    :param config_type: Config type used for diagnostics.
    :param target: Config class or instance defining public field names.
    :param values: Candidate override mapping.
    :raises KeyError: If any override name is not a public config field.
    """
    public_field_names = _public_config_field_names(target)
    unknown = sorted(set(values) - public_field_names)
    if not unknown:
        return
    joined = ", ".join(unknown)
    raise KeyError(
        f"{config_type.__name__} has no public config field(s): {joined}"
    )


def _merge_overrides(
    overrides: Mapping[str, Any] | None,
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Return override values with keyword arguments taking precedence.

    :param overrides: Optional mapping of field-name overrides.
    :param kwargs: Keyword field-name overrides.
    :return: Merged override mapping.
    """
    values = dict(overrides or {})
    values.update(kwargs)
    return values


def _without_skipped_none(
    values: Mapping[str, Any],
    *,
    skip_none: bool = True,
) -> dict[str, Any]:
    """Return overrides that survive the configured ``None`` policy.

    :param values: Candidate override mapping.
    :param skip_none: Whether ``None`` means no override.
    :return: Override mapping after applying the ``None`` policy.
    """
    if not skip_none:
        return dict(values)
    return {key: value for key, value in values.items() if value is not None}
