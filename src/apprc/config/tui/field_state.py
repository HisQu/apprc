"""Pure field-state helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# == Internal ================================
from apprc.config.local_env import normalize_env_value
from apprc.config.schema import (
    CONFIG_MISSING,
    ConfigField,
    ConfigOwner,
    find_field_by_env_key,
)


@dataclass(frozen=True, slots=True)
class SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


type ConfigValueSourceKey = Literal["effective", "shell", "local", "shared"]
type ConfigResolvedSourceKey = Literal["shell", "local", "shared"]


@dataclass(frozen=True, slots=True)
class ConfigValueSource:
    """One raw value source shown in the config value modal.

    ``raw_value=None`` means the source is absent. Empty strings are real
    values because users may intentionally set an env key to an empty value.

    :param key: Stable source identifier used by modal button IDs.
    :param raw_value: Raw string value copied to the clipboard, or ``None``.
    :param origin_key: Concrete source that provided the effective value.
    """

    key: ConfigValueSourceKey
    raw_value: str | None
    origin_key: ConfigResolvedSourceKey | None = None

    @property
    def is_available(self) -> bool:
        """Return whether this source can be copied."""
        return self.raw_value is not None


def selected_field_for_row(
    *,
    owners: Iterable[ConfigOwner],
    row_env_keys: Sequence[str | None],
    row_index: int | None,
) -> SelectedField | None:
    """Return the config field represented by one table row.

    Separator rows and out-of-range indices have no editable field attached.

    :param owners: Declared config sections shown in the table.
    :param row_env_keys: Env key per table row, with ``None`` for separators.
    :param row_index: Current table cursor row.
    :return: Selected field metadata, or ``None`` for non-field rows.
    """
    if row_index is None or row_index < 0 or row_index >= len(row_env_keys):
        return None
    env_key = row_env_keys[row_index]
    if env_key is None:
        return None
    found = find_field_by_env_key(owners, env_key)
    if found is None:
        return None
    owner, spec = found
    return SelectedField(owner=owner, spec=spec)


def config_value_sources(
    *,
    spec: ConfigField,
    env_key: str,
    local_values: Mapping[str, str],
    shell_env: Mapping[str, str],
    shared_values: Mapping[str, str] | None,
) -> tuple[ConfigValueSource, ...]:
    """Return copyable values for one config field in precedence order.

    The effective source mirrors AppRC runtime precedence for layers the
    editor can inspect without running full CLI bootstrap: shell, selected
    storage-local dotenv, then packaged or declared shared default.

    :param spec: Field declaration that owns defaults and type metadata.
    :param env_key: Full env key for the selected row.
    :param local_values: Parsed storage-local dotenv values.
    :param shell_env: Current process environment.
    :param shared_values: Parsed packaged shared dotenv values, when known.
    :return: Effective, shell, local, and shared source rows.
    """
    shell_value = shell_env[env_key] if env_key in shell_env else None
    local_value = local_values[env_key] if env_key in local_values else None
    shared_value = _shared_source_value(
        spec=spec,
        env_key=env_key,
        shared_values=shared_values,
    )
    effective_value, origin_key = _first_available_source(
        ("shell", shell_value),
        ("local", local_value),
        ("shared", shared_value),
    )
    return (
        ConfigValueSource(
            key="effective",
            raw_value=effective_value,
            origin_key=origin_key,
        ),
        ConfigValueSource(key="shell", raw_value=shell_value),
        ConfigValueSource(key="local", raw_value=local_value),
        ConfigValueSource(
            key="shared",
            raw_value=shared_value,
        ),
    )


def _shared_source_value(
    *,
    spec: ConfigField,
    env_key: str,
    shared_values: Mapping[str, str] | None,
) -> str | None:
    """Return a packaged or declared shared-default value."""
    if shared_values is not None and env_key in shared_values:
        return shared_values[env_key]
    value = spec.shared_env_value()
    if value is CONFIG_MISSING:
        return None
    try:
        return normalize_env_value(spec, str(value))
    except (TypeError, ValueError):
        return str(value)


def _first_available_source(
    *sources: tuple[ConfigResolvedSourceKey, str | None],
) -> tuple[str | None, ConfigResolvedSourceKey | None]:
    """Return the first present source while preserving empty strings."""
    for key, value in sources:
        if value is not None:
            return value, key
    return None, None
