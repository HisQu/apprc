"""Pure field-state helpers for the Textual config editor."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

# == Internal ================================
from apprc.user_files.env_files.values import stringify_env_value
from apprc.runtime.resolution import ResolvedConfig
from apprc.definition.env_config.lookup import find_field_by_env_key
from apprc.definition.env_config.schema import ConfigField, ConfigOwner


@dataclass(frozen=True, slots=True)
class SelectedField:
    """One field selected by env key in the editor table."""

    owner: ConfigOwner
    spec: ConfigField


type EditableConfigValueSourceKey = Literal[
    "effective", "shell", "explicit", "user", "storage", "defaults"
]
type ConfigResolvedSourceKey = Literal[
    "shell", "explicit", "user", "storage", "defaults"
]
type ConfigWriteScope = Literal["user", "storage"]


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
    raw_value: str | None = field(repr=False)
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
    resolved: ResolvedConfig,
    include_user_dotenv: bool,
    include_storage: bool,
) -> tuple[EditableConfigValueSource, ...]:
    """Present captured sources without implementing precedence in the UI.

    :param spec: Selected field declaration.
    :param env_key: Full field environment key.
    :param resolved: Shared runtime resolution for the inspected storage.
    :param include_user_dotenv: Whether to show the user layer.
    :param include_storage: Whether to show the storage layer.
    :return: Copyable effective value and individual source rows.
    """
    source_keys: dict[str, ConfigResolvedSourceKey] = {
        "shell_export_variable": "shell",
        "shell_dotenv_explicit": "explicit",
        "shell_dotenv_user": "user",
        "shell_dotenv_storage": "storage",
        "shell_dotenv_defaults": "defaults",
        "shell_storage_selector": "shell",
    }
    values: dict[ConfigResolvedSourceKey, str | None] = {
        "shell": None,
        "explicit": None,
        "user": None,
        "storage": None,
        "defaults": stringify_env_value(spec.resolve_default())
        if spec.has_default()
        else None,
    }
    for layer in resolved.layers:
        if env_key in layer.source.values:
            values[source_keys[layer.origin]] = layer.source.values[env_key]
    origin = resolved.source.origins.get(env_key)
    effective = resolved.values.get(env_key, values["defaults"])
    sources = [
        EditableConfigValueSource(
            "effective",
            effective,
            source_keys[origin.origin] if origin is not None else "defaults",
        ),
        EditableConfigValueSource("shell", values["shell"]),
    ]
    if resolved.options.env_files:
        sources.append(
            EditableConfigValueSource("explicit", values["explicit"])
        )
    if include_user_dotenv:
        sources.append(EditableConfigValueSource("user", values["user"]))
    if include_storage:
        sources.append(EditableConfigValueSource("storage", values["storage"]))
    sources.append(EditableConfigValueSource("defaults", values["defaults"]))
    return tuple(sources)
