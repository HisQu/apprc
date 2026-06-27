"""Pure field-state helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# == Internal ================================
from apprc.runtime_config.env_file import normalize_env_value
from apprc.runtime_config.contract.lookup import find_field_by_env_key
from apprc.runtime_config.contract.schema import ConfigField, ConfigOwner
from apprc.runtime_config.contract.sentinels import CONFIG_MISSING


@dataclass(frozen=True, slots=True)
class SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


type EditableConfigValueSourceKey = Literal[
    "effective", "shell", "app", "storage", "shared"
]
type ConfigResolvedSourceKey = Literal["shell", "app", "storage", "shared"]
type ConfigWriteScope = Literal["app", "storage"]


@dataclass(frozen=True, slots=True)
class EditableConfigValueSource:
    """One raw value source shown in the config value modal.

    ``raw_value=None`` means the source is absent. Empty strings are real
    values because users may intentionally set an env key to an empty value.

    :param key: Stable source identifier used by modal button IDs.
    :param raw_value: Raw string value copied to the clipboard, or ``None``.
    :param origin_key: Concrete source that provided the effective value.
    """

    key: EditableConfigValueSourceKey
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
    app_values: Mapping[str, str],
    storage_values: Mapping[str, str],
    shell_env: Mapping[str, str],
    shared_values: Mapping[str, str] | None,
    include_app: bool,
    include_storage: bool,
) -> tuple[EditableConfigValueSource, ...]:
    """Return copyable values for one config field in precedence order.

    The effective source mirrors AppRC runtime precedence for layers the
    editor can inspect without running full CLI bootstrap: shell, storage,
    app-wide config, then packaged or declared shared default.

    :param spec: Field declaration that owns defaults and type metadata.
    :param env_key: Full env key for the selected row.
    :param app_values: Parsed app-wide dotenv values.
    :param storage_values: Parsed storage dotenv values.
    :param shell_env: Current process environment.
    :param shared_values: Parsed packaged shared dotenv values, when known.
    :param include_app: Whether the app-wide layer is active in the editor.
    :param include_storage: Whether a storage layer is selected in the editor.
    :return: Effective, shell, active persistence layers, and shared source rows.
    """
    shell_value = shell_env[env_key] if env_key in shell_env else None
    app_value = app_values[env_key] if env_key in app_values else None
    storage_value = (
        storage_values[env_key] if env_key in storage_values else None
    )
    shared_value = _shared_source_value(
        spec=spec,
        env_key=env_key,
        shared_values=shared_values,
    )
    effective_value, origin_key = _first_available_source(
        ("shell", shell_value),
        ("storage", storage_value if include_storage else None),
        ("app", app_value if include_app else None),
        ("shared", shared_value),
    )
    sources: list[EditableConfigValueSource] = [
        EditableConfigValueSource(
            key="effective",
            raw_value=effective_value,
            origin_key=origin_key,
        ),
        EditableConfigValueSource(key="shell", raw_value=shell_value),
    ]
    if include_app:
        sources.append(
            EditableConfigValueSource(key="app", raw_value=app_value)
        )
    if include_storage:
        sources.append(
            EditableConfigValueSource(key="storage", raw_value=storage_value)
        )
    sources.append(
        EditableConfigValueSource(
            key="shared",
            raw_value=shared_value,
        )
    )
    return tuple(sources)


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
