"""Read and write optional multi-storage tables inside an AppRC TOML.

CLI applications often run globally, but their data lives in user-chosen
project or corpus directories. The required ``<APP>_STORAGE`` selector points
at the active path. When users opt into ``<APP>_APPRC_TOML``, the storage
registry maps friendly storage names to absolute storage roots for
multi-storage management.

AppRC TOML path selection lives in :mod:`apprc.config.app_spec`, storage
selector resolution lives in :mod:`apprc.config.storage.selector`, and
storage-local dotenv value handling lives in :mod:`apprc.config.local_env`.
"""

from __future__ import annotations

# == Standard Library ========================
import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from apprc.config.local_env import ensure_local_env_file
from apprc.config.paths import normalize_storage_root_path

_STORAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_REGISTRY_TOP_LEVEL_KEYS = frozenset({"archived_storages", "storages"})


@dataclass(frozen=True, slots=True)
class StorageRecord:
    """One named storage root from the multi-storage registry.

    :param name: Stable storage selector used by ``--storage``.
    :param root: Root directory that owns user data and ``.env.local``.
    """

    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class ArchivedStorageRecord:
    """Last known archive for one storage selector.

    Archive records are restore conveniences only. Runtime bootstrap still
    selects live :class:`StorageRecord` entries from ``storages``.

    :param name: Storage selector the archive was last associated with.
    :param archive: Archive path last written by the editor.
    :param source_root: Source directory that was compressed into the archive.
    """

    name: str
    archive: Path
    source_root: Path


@dataclass(frozen=True, slots=True)
class StorageRegistry:
    """Parsed storage registry.

    :param path: AppRC TOML location.
    :param storages: Named live storage roots by selector.
    :param archived_storages: Last known archive paths by selector.
    """

    path: Path
    storages: Mapping[str, StorageRecord]
    archived_storages: Mapping[str, ArchivedStorageRecord] = field(
        default_factory=dict
    )

    def selected(self, name: str) -> StorageRecord:
        """Return one named storage or raise a readable error.

        :param name: Storage selector requested by CLI or config.
        :return: Matching storage record.
        :raises ValueError: If the storage does not exist.
        """
        try:
            return self.storages[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.storages)) or "<none>"
            raise ValueError(
                f"Unknown storage {name!r} in {self.path}. "
                f"Known storages: {known}."
            ) from exc


def app_data_dir(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user data directory for one application.

    :param app_name: Directory name below ``$XDG_DATA_HOME`` or
        ``~/.local/share``.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: ``$XDG_DATA_HOME/<app_name>`` or ``~/.local/share/<app_name>``.
    """
    env = os.environ if proc_env is None else proc_env
    xdg_data_home = env.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / app_name
    return Path.home() / ".local" / "share" / app_name


def suggested_storage_root(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the conventional active storage root for a fresh setup."""
    return app_data_dir(app_name, proc_env) / suggested_storage_name(app_name)


def suggested_storage_name(app_name: str) -> str:
    """Return the conventional name for a first storage.

    :param app_name: Application name from the AppRC integration spec.
    :return: Host-specific selector that does not reuse the UI term
        ``default``.
    """
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_-")
    base_name = normalized or "apprc"
    return f"{base_name}_stor-1"


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
            archived_storages={},
        )
    try:
        data = tomllib.loads(apprc_toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Failed to parse storage registry {apprc_toml_path}: {exc}"
        ) from exc
    return _registry_from_toml(data=data, path=apprc_toml_path)


def register_storage(
    *,
    name: str,
    root: Path,
    path: Path,
    local_env_filename: str = ".env.local",
) -> StorageRegistry:
    """Add or update one storage entry and write the registry.

    :param name: Storage selector to create or update.
    :param root: Storage root directory.
    :param path: AppRC TOML location.
    :param local_env_filename: Storage-local dotenv filename to create.
    :return: Updated registry.
    """
    _validate_storage_name(name)
    resolved_root = normalize_storage_root_path(root).resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    ensure_local_env_file(resolved_root, filename=local_env_filename)

    current = load_storage_registry_or_empty(path)
    storages = dict(current.storages)
    storages[name] = StorageRecord(name=name, root=resolved_root)

    updated = replace(
        current,
        storages=storages,
    )
    write_storage_registry(updated)
    return updated


def unregister_storage(
    *,
    name: str,
    path: Path,
) -> StorageRegistry:
    """Remove one live storage entry from the registry.

    :param name: Live storage selector to remove.
    :param path: AppRC TOML location.
    :return: Updated registry.
    :raises ValueError: If ``name`` is unknown.
    """
    _validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    current.selected(name)
    storages = dict(current.storages)
    storages.pop(name)

    updated = replace(
        current,
        storages=storages,
    )
    write_storage_registry(updated)
    return updated


def record_archived_storage(
    *,
    name: str,
    archive: Path,
    source_root: Path,
    path: Path,
) -> StorageRegistry:
    """Remember the last archive path for one storage selector."""
    _validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    archived_storages = dict(current.archived_storages)
    archived_storages[name] = ArchivedStorageRecord(
        name=name,
        archive=normalize_storage_root_path(archive).expanduser(),
        source_root=normalize_storage_root_path(source_root).expanduser(),
    )
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def remove_archived_storage(
    *,
    name: str,
    path: Path,
) -> StorageRegistry:
    """Remove one stale or restored archive convenience entry."""
    _validate_storage_name(name)
    current = load_storage_registry_or_empty(path)
    archived_storages = dict(current.archived_storages)
    archived_storages.pop(name, None)
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def prune_missing_archived_storages(
    *,
    path: Path,
) -> StorageRegistry:
    """Drop archive records whose last known file no longer exists."""
    current = load_storage_registry_or_empty(path)
    archived_storages = {
        name: record
        for name, record in current.archived_storages.items()
        if record.archive.is_file()
    }
    if archived_storages == current.archived_storages:
        return current
    updated = replace(
        current,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def write_storage_registry(registry: StorageRegistry) -> Path:
    """Write a deterministic TOML storage registry.

    :param registry: Registry object to serialize.
    :return: Written AppRC TOML path.
    """
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(
        _render_storage_registry(registry), encoding="utf-8"
    )
    return registry.path


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

    raw_storages = _toml_table(data=data, key="storages", path=path)
    storages: dict[str, StorageRecord] = {}
    for name, raw_record in raw_storages.items():
        _validate_storage_name(name)
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
            root=normalize_storage_root_path(raw_root),
        )

    raw_archived = _toml_table(
        data=data,
        key="archived_storages",
        path=path,
    )
    archived_storages: dict[str, ArchivedStorageRecord] = {}
    for name, raw_record in raw_archived.items():
        _validate_storage_name(name)
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
            archive=normalize_storage_root_path(raw_archive),
            source_root=normalize_storage_root_path(raw_source_root),
        )

    return StorageRegistry(
        path=path,
        storages=storages,
        archived_storages=archived_storages,
    )


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


def _render_storage_registry(registry: StorageRegistry) -> str:
    """Return deterministic TOML text for the supported schema."""
    lines: list[str] = []
    for name in sorted(registry.storages):
        record = registry.storages[name]
        if lines:
            lines.append("")
        lines.append(f"[storages.{name}]")
        lines.append(f"root = {_toml_string(str(record.root))}")
    for name in sorted(registry.archived_storages):
        record = registry.archived_storages[name]
        if lines:
            lines.append("")
        lines.append(f"[archived_storages.{name}]")
        lines.append(f"archive = {_toml_string(str(record.archive))}")
        lines.append(f"source_root = {_toml_string(str(record.source_root))}")
    return "\n".join(lines).rstrip() + "\n"


def _toml_string(value: str) -> str:
    """Return a TOML-compatible basic string."""
    return json.dumps(value)


def _validate_storage_name(name: str) -> None:
    """Reject storage names that cannot be written as simple TOML keys."""
    if not _STORAGE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Storage names may contain only letters, numbers, underscores, "
            "and hyphens; they must not include `/` or `\\`. Use "
            "<APP>_STORAGE or --storage-root for path values."
        )
