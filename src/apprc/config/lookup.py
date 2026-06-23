"""Lookup helpers for normalized AppRC config owner inventories."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable

# == Internal ================================
from apprc.config.schema import ConfigField, ConfigOwner


def iter_config_fields(
    owners: Iterable[ConfigOwner],
) -> Iterable[tuple[ConfigOwner, ConfigField]]:
    """Yield every ``(owner, field)`` pair in declaration order."""
    for owner in owners:
        for spec in owner.fields:
            yield owner, spec


def find_field_by_env_key(
    owners: Iterable[ConfigOwner],
    env_key: str,
) -> tuple[ConfigOwner, ConfigField] | None:
    """Return the owner field addressed by a full env key."""
    normalized = env_key.strip()
    for owner, spec in iter_config_fields(owners):
        if owner.env_key(spec.name) == normalized:
            return owner, spec
    return None


def find_field_by_config_path(
    owners: Iterable[ConfigOwner],
    config_path: str,
) -> tuple[ConfigOwner, ConfigField] | None:
    """Return the owner field addressed by a dotted config path."""
    normalized = config_path.strip()
    for owner, spec in iter_config_fields(owners):
        if owner.config_path_text(spec.name) == normalized:
            return owner, spec
    return None


def resolve_config_field_reference(
    owners: Iterable[ConfigOwner],
    reference: str,
) -> tuple[ConfigOwner, ConfigField]:
    """Resolve an env key, dotted config path, or unique field name.

    :param owners: Owner specs to search.
    :param reference: User input such as ``APP_MODEL_LLM`` or
        ``app.runtime_settings.model``.
    :return: Matching owner and field spec.
    :raises ValueError: If the reference is unknown or ambiguous.
    """
    ref = reference.strip()
    by_env = find_field_by_env_key(owners, ref)
    if by_env is not None:
        return by_env
    by_path = find_field_by_config_path(owners, ref)
    if by_path is not None:
        return by_path

    matches = [
        (owner, spec)
        for owner, spec in iter_config_fields(owners)
        if spec.name == ref
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(
            owner.config_path_text(spec.name) for owner, spec in matches
        )
        raise ValueError(
            f"Config field name {ref!r} is ambiguous. Use one of: {choices}."
        )
    raise ValueError(f"Unknown config key or path: {ref!r}.")
