"""Read and write per-user storage registries.

CLI applications often run globally, but their data lives in user-chosen
project or corpus directories. AppRC solves that with a tiny TOML registry at
``$XDG_CONFIG_HOME/<app>/<registry_filename>``. The registry maps friendly
storage names to absolute storage roots and records which one is the default.

This module owns only that user-level TOML file. Storage-local dotenv values
inside each root are handled by :mod:`apprc.config.local_env`, and process
environment bootstrapping is handled by :mod:`apprc.config.environment`.
"""

from __future__ import annotations

# == Standard Library ========================
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from apprc.config.paths import normalize_storage_root_path

_STORAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class StorageRecord:
    """One named storage root from the user registry.

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

    :param path: Registry file location.
    :param default_storage: Name used when no ``--storage`` is passed.
    :param storages: Named live storage roots by selector.
    :param archived_storages: Last known archive paths by selector.
    """

    path: Path
    default_storage: str | None
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

    def default(self) -> StorageRecord | None:
        """Return the default storage when one is configured."""
        if self.default_storage is None:
            return None
        return self.selected(self.default_storage)


def app_config_dir(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user config directory for one application.

    :param app_name: Directory name below ``$XDG_CONFIG_HOME`` or
        ``~/.config``.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: ``$XDG_CONFIG_HOME/<app_name>`` or ``~/.config/<app_name>``.
    """
    env = os.environ if proc_env is None else proc_env
    xdg_config_home = env.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / app_name
    return Path.home() / ".config" / app_name


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


def default_storage_data_root(
    app_name: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the conventional live storage root for a fresh default."""
    return app_data_dir(app_name, proc_env) / "default"


def default_storage_registry_path(
    *,
    app_name: str,
    registry_filename: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the default user registry path for one application."""
    return app_config_dir(app_name, proc_env) / registry_filename


def config_file_env_key(app_name: str) -> str:
    """Return the environment variable that overrides the registry file.

    :param app_name: Application name from the AppRC integration spec.
    :return: Uppercase ``<APP>_CONFIG_FILE`` variable name.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_name).strip("_").upper()
    if not normalized:
        normalized = "APP"
    return f"{normalized}_CONFIG_FILE"


def configured_storage_registry_path(
    *,
    app_name: str,
    registry_filename: str,
    proc_env: Mapping[str, str] | None = None,
) -> Path:
    """Return the active registry path after applying the env override.

    :param app_name: Application name from the AppRC integration spec.
    :param registry_filename: Default registry filename below the app config
        directory.
    :param proc_env: Environment mapping used for tests and subprocess setup.
    :return: The env-selected registry path, or the default path.
    """
    env = os.environ if proc_env is None else proc_env
    raw_path = env.get(config_file_env_key(app_name), "").strip()
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return default_storage_registry_path(
        app_name=app_name,
        registry_filename=registry_filename,
        proc_env=proc_env,
    )


def load_storage_registry(path: Path) -> StorageRegistry:
    """Read a storage registry if it exists.

    :param path: Registry file location.
    :return: Parsed registry, or an empty registry when the file is absent.
    :raises ValueError: If the registry schema is invalid.
    """
    registry_path = Path(path).expanduser()
    if not registry_path.is_file():
        return StorageRegistry(
            path=registry_path,
            default_storage=None,
            storages={},
            archived_storages={},
        )
    try:
        data = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Failed to parse storage registry {registry_path}: {exc}"
        ) from exc
    return _registry_from_toml(data=data, path=registry_path)


def register_storage(
    *,
    name: str,
    root: Path,
    make_default: bool,
    path: Path,
    local_env_filename: str = ".env.local",
) -> StorageRegistry:
    """Add or update one storage entry and write the registry.

    :param name: Storage selector to create or update.
    :param root: Storage root directory.
    :param make_default: Whether this storage should become the default.
    :param path: Registry file location.
    :param local_env_filename: Storage-local dotenv filename to create.
    :return: Updated registry.
    """
    _validate_storage_name(name)
    resolved_root = normalize_storage_root_path(root).resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    (resolved_root / local_env_filename).touch(exist_ok=True)

    current = load_storage_registry(path)
    storages = dict(current.storages)
    storages[name] = StorageRecord(name=name, root=resolved_root)
    default_storage = current.default_storage
    if make_default or default_storage is None:
        default_storage = name

    updated = StorageRegistry(
        path=current.path,
        default_storage=default_storage,
        storages=storages,
        archived_storages=current.archived_storages,
    )
    write_storage_registry(updated)
    return updated


def set_default_storage(
    *,
    name: str,
    path: Path,
) -> StorageRegistry:
    """Set an existing storage as the default registry entry.

    :param name: Storage selector that should become the registry default.
    :param path: Registry file location.
    :return: Updated registry.
    :raises ValueError: If the registry is invalid or ``name`` is unknown.
    """
    _validate_storage_name(name)
    current = load_storage_registry(path)
    current.selected(name)
    updated = StorageRegistry(
        path=current.path,
        default_storage=name,
        storages=current.storages,
        archived_storages=current.archived_storages,
    )
    write_storage_registry(updated)
    return updated


def replace_default_storage(
    *,
    name: str | None,
    path: Path,
) -> StorageRegistry:
    """Set or clear the default storage.

    :param name: Existing live storage selector, or ``None`` to leave no
        default.
    :param path: Registry file location.
    :return: Updated registry.
    :raises ValueError: If ``name`` is unknown.
    """
    current = load_storage_registry(path)
    if name is not None:
        _validate_storage_name(name)
        current.selected(name)
    updated = StorageRegistry(
        path=current.path,
        default_storage=name,
        storages=current.storages,
        archived_storages=current.archived_storages,
    )
    write_storage_registry(updated)
    return updated


def unregister_storage(
    *,
    name: str,
    path: Path,
    replacement_default: str | None = None,
) -> StorageRegistry:
    """Remove one live storage entry from the registry.

    :param name: Live storage selector to remove.
    :param path: Registry file location.
    :param replacement_default: New default when the removed storage was the
        default. Pass ``None`` to leave no default.
    :return: Updated registry.
    :raises ValueError: If ``name`` or ``replacement_default`` is unknown.
    """
    _validate_storage_name(name)
    current = load_storage_registry(path)
    current.selected(name)
    storages = dict(current.storages)
    storages.pop(name)

    default_storage = current.default_storage
    if current.default_storage == name:
        default_storage = replacement_default
    if default_storage is not None and default_storage not in storages:
        known = ", ".join(sorted(storages)) or "<none>"
        raise ValueError(
            f"Replacement default {default_storage!r} is not configured. "
            f"Known storages: {known}."
        )

    updated = StorageRegistry(
        path=current.path,
        default_storage=default_storage,
        storages=storages,
        archived_storages=current.archived_storages,
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
    current = load_storage_registry(path)
    archived_storages = dict(current.archived_storages)
    archived_storages[name] = ArchivedStorageRecord(
        name=name,
        archive=normalize_storage_root_path(archive).expanduser(),
        source_root=normalize_storage_root_path(source_root).expanduser(),
    )
    updated = StorageRegistry(
        path=current.path,
        default_storage=current.default_storage,
        storages=current.storages,
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
    current = load_storage_registry(path)
    archived_storages = dict(current.archived_storages)
    archived_storages.pop(name, None)
    updated = StorageRegistry(
        path=current.path,
        default_storage=current.default_storage,
        storages=current.storages,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def prune_missing_archived_storages(
    *,
    path: Path,
) -> StorageRegistry:
    """Drop archive records whose last known file no longer exists."""
    current = load_storage_registry(path)
    archived_storages = {
        name: record
        for name, record in current.archived_storages.items()
        if record.archive.is_file()
    }
    if archived_storages == current.archived_storages:
        return current
    updated = StorageRegistry(
        path=current.path,
        default_storage=current.default_storage,
        storages=current.storages,
        archived_storages=archived_storages,
    )
    write_storage_registry(updated)
    return updated


def write_storage_registry(registry: StorageRegistry) -> Path:
    """Write a deterministic TOML storage registry.

    :param registry: Registry object to serialize.
    :return: Written registry path.
    """
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(
        _render_storage_registry(registry), encoding="utf-8"
    )
    return registry.path


def _registry_from_toml(
    *,
    data: Mapping[str, Any],
    path: Path,
) -> StorageRegistry:
    """Build a typed registry from parsed TOML data."""
    raw_default = data.get("default_storage")
    if raw_default is not None and not isinstance(raw_default, str):
        raise ValueError(f"{path}: default_storage must be a string.")

    raw_storages = data.get("storages", {})
    if not isinstance(raw_storages, dict):
        raise ValueError(f"{path}: storages must be a table.")

    storages: dict[str, StorageRecord] = {}
    for name, raw_record in raw_storages.items():
        _validate_storage_name(name)
        if not isinstance(raw_record, dict):
            raise ValueError(f"{path}: storages.{name} must be a table.")
        raw_root = raw_record.get("root")
        if not isinstance(raw_root, str) or not raw_root:
            raise ValueError(f"{path}: storages.{name}.root must be a string.")
        storages[name] = StorageRecord(
            name=name,
            root=normalize_storage_root_path(raw_root),
        )

    raw_archived = data.get("archived_storages", {})
    if not isinstance(raw_archived, dict):
        raise ValueError(f"{path}: archived_storages must be a table.")

    archived_storages: dict[str, ArchivedStorageRecord] = {}
    for name, raw_record in raw_archived.items():
        _validate_storage_name(name)
        if not isinstance(raw_record, dict):
            raise ValueError(
                f"{path}: archived_storages.{name} must be a table."
            )
        raw_archive = raw_record.get("archive")
        raw_source_root = raw_record.get("source_root")
        if not isinstance(raw_archive, str) or not raw_archive:
            raise ValueError(
                f"{path}: archived_storages.{name}.archive must be a string."
            )
        if not isinstance(raw_source_root, str) or not raw_source_root:
            raise ValueError(
                f"{path}: archived_storages.{name}.source_root "
                "must be a string."
            )
        archived_storages[name] = ArchivedStorageRecord(
            name=name,
            archive=normalize_storage_root_path(raw_archive),
            source_root=normalize_storage_root_path(raw_source_root),
        )

    if raw_default is not None and raw_default not in storages:
        known = ", ".join(sorted(storages)) or "<none>"
        raise ValueError(
            f"{path}: default_storage {raw_default!r} is not configured. "
            f"Known storages: {known}."
        )
    return StorageRegistry(
        path=path,
        default_storage=raw_default,
        storages=storages,
        archived_storages=archived_storages,
    )


def _render_storage_registry(registry: StorageRegistry) -> str:
    """Return deterministic TOML text for the supported schema."""
    lines: list[str] = []
    if registry.default_storage is not None:
        lines.append(
            f"default_storage = {_toml_string(registry.default_storage)}"
        )
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
            "Storage names may contain only letters, numbers, "
            "underscores, and hyphens."
        )
