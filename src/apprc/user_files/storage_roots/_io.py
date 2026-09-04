"""TOML IO for AppRC multi-storage registries."""

from __future__ import annotations

# == Standard Library ========================
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

# == Internal ================================
from apprc.user_files.app_home.locations import write_text_atomic
from apprc.user_files.storage_roots.model import (
    ArchivedStorageRecord,
    StorageRecord,
    StorageRegistry,
)
from apprc.user_files.storage_roots._naming import validate_storage_name
from apprc.user_files.storage_roots.paths import resolve_storage_root_path

_REGISTRY_TOP_LEVEL_KEYS = frozenset(
    {"archived_storages", "selected_storage", "storages"}
)


def load_storage_registry_or_empty(path: Path) -> StorageRegistry:
    """Read a storage registry, or return an empty registry when absent.

    :param path: AppRC TOML location.
    :return: Parsed registry, or an empty registry when the file is absent.
    :raises ValueError: If the registry schema is invalid.
    """
    apprc_toml_path = Path(path).expanduser()
    if not apprc_toml_path.is_file():
        return StorageRegistry(
            path=apprc_toml_path,
            storages={},
            selected_storage=None,
            archived_storages={},
        )
    try:
        data = tomllib.loads(apprc_toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Failed to parse storage registry {apprc_toml_path}: {exc}"
        ) from exc
    return _registry_from_toml(data=data, path=apprc_toml_path)


def write_storage_registry(registry: StorageRegistry) -> Path:
    """Write a deterministic TOML storage registry.

    :param registry: Registry object to serialize.
    :return: Written AppRC TOML path.
    """
    return write_text_atomic(registry.path, render_storage_registry(registry))


def ordered_storage_names(registry: StorageRegistry) -> list[str]:
    """Return registered storage names by name.

    :param registry: Registry whose storage names should be ordered.
    :return: Stable display order for CLIs and TUIs.
    """
    return sorted(registry.storages)


def _registry_from_toml(
    *,
    data: Mapping[str, object],
    path: Path,
) -> StorageRegistry:
    """Build a typed registry from parsed TOML data."""
    unknown_keys = sorted(set(data) - _REGISTRY_TOP_LEVEL_KEYS)
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        supported_text = ", ".join(sorted(_REGISTRY_TOP_LEVEL_KEYS))
        raise ValueError(
            f"{path}: unsupported top-level registry key(s): {unknown_text}. "
            f"Supported keys: {supported_text}."
        )

    selected_storage = _optional_toml_string(
        data=data,
        key="selected_storage",
        path=path,
    )
    raw_storages = _toml_table(data=data, key="storages", path=path)
    storages: dict[str, StorageRecord] = {}
    for name, raw_record in raw_storages.items():
        validate_storage_name(name)
        record = _toml_record_table(
            raw_record=raw_record,
            path=path,
            section="storages",
            name=name,
        )
        raw_root = _toml_string_field(
            record=record,
            path=path,
            section="storages",
            name=name,
            field="root",
        )
        storages[name] = StorageRecord(
            name=name,
            root=resolve_storage_root_path(raw_root, base=path.parent),
        )

    if selected_storage is not None and selected_storage not in storages:
        raise ValueError(
            f"{path}: selected_storage {selected_storage!r} is not registered."
        )

    raw_archived = _toml_table(
        data=data,
        key="archived_storages",
        path=path,
    )
    archived_storages: dict[str, ArchivedStorageRecord] = {}
    for name, raw_record in raw_archived.items():
        validate_storage_name(name)
        record = _toml_record_table(
            raw_record=raw_record,
            path=path,
            section="archived_storages",
            name=name,
        )
        raw_archive = _toml_string_field(
            record=record,
            path=path,
            section="archived_storages",
            name=name,
            field="archive",
        )
        raw_source_root = _toml_string_field(
            record=record,
            path=path,
            section="archived_storages",
            name=name,
            field="source_root",
        )
        archived_storages[name] = ArchivedStorageRecord(
            name=name,
            archive=resolve_storage_root_path(raw_archive, base=path.parent),
            source_root=resolve_storage_root_path(
                raw_source_root,
                base=path.parent,
            ),
        )

    return StorageRegistry(
        path=path,
        storages=storages,
        selected_storage=selected_storage,
        archived_storages=archived_storages,
    )


def _optional_toml_string(
    *,
    data: Mapping[str, object],
    key: str,
    path: Path,
) -> str | None:
    """Return one optional non-empty top-level string.

    :param data: Parsed TOML mapping.
    :param key: Field name to inspect.
    :param path: Registry path used in errors.
    :return: String value, or ``None`` when absent.
    :raises ValueError: If the field is not a non-empty string.
    """
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {key} must be a non-empty string.")
    return value


def _toml_table(
    *,
    data: Mapping[str, object],
    key: str,
    path: Path,
) -> Mapping[str, object]:
    """Return one top-level TOML table or raise a registry schema error."""
    raw_table = data.get(key, {})
    if not isinstance(raw_table, Mapping):
        raise ValueError(f"{path}: {key} must be a table.")
    return cast(Mapping[str, object], raw_table)


def _toml_record_table(
    *,
    raw_record: object,
    path: Path,
    section: str,
    name: str,
) -> Mapping[str, object]:
    """Return one nested record table or raise a registry schema error."""
    if not isinstance(raw_record, Mapping):
        raise ValueError(f"{path}: {section}.{name} must be a table.")
    return cast(Mapping[str, object], raw_record)


def _toml_string_field(
    *,
    record: Mapping[str, object],
    path: Path,
    section: str,
    name: str,
    field: str,
) -> str:
    """Return one required string field or raise a registry schema error."""
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {section}.{name}.{field} must be a string.")
    return value


def render_storage_registry(registry: StorageRegistry) -> str:
    """Return deterministic TOML text for the supported schema.

    :param registry: Registry to serialize.
    :return: Complete TOML text.
    """
    lines: list[str] = []
    if registry.selected_storage is not None:
        lines.append(
            f"selected_storage = {_toml_string(registry.selected_storage)}"
        )
    for name in sorted(registry.storages):
        record = registry.storages[name]
        if lines:
            lines.append("")
        lines.append(f"[storages.{name}]")
        lines.append(
            f"root = {_toml_string(_stored_path(record.root, registry.path))}"
        )
    for name in sorted(registry.archived_storages):
        record = registry.archived_storages[name]
        if lines:
            lines.append("")
        lines.append(f"[archived_storages.{name}]")
        lines.append(
            f"archive = {_toml_string(_stored_path(record.archive, registry.path))}"
        )
        lines.append(
            "source_root = "
            f"{_toml_string(_stored_path(record.source_root, registry.path))}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _stored_path(path: Path, registry_path: Path) -> str:
    """Return an internal path relative to ``apprc.toml`` when possible.

    :param path: Resolved storage or archive path.
    :param registry_path: AppRC TOML path.
    :return: Portable registry spelling.
    """
    resolved = path.expanduser().absolute()
    base = registry_path.parent.expanduser().absolute()
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        return str(resolved)


def _toml_string(value: str) -> str:
    """Return a TOML-compatible basic string."""
    return json.dumps(value)
