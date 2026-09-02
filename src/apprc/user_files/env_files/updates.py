"""Validated set and clear operations for AppRC dotenv files."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# == Internal ================================
from apprc.definition.env_config.lookup import resolve_config_field_reference
from apprc.definition.env_config.schema import ConfigOwner
from apprc.user_files.app_home.locations import ConfigHomeError
from apprc.user_files.env_files.files import (
    ensure_env_file,
    read_env_file,
    require_existing_storage_root,
    storage_env_path,
    write_env_file,
)
from apprc.user_files.env_files.values import normalize_env_value
from apprc.user_files.storage_roots.paths import StorageRootPathError


@dataclass(frozen=True, slots=True)
class EnvFileUpdate:
    """Result of one dotenv edit.

    :param path: Dotenv file that was written.
    :param env_key: Concrete env key written to the file.
    :param value: Normalized string value stored in the file.
    """

    path: Path
    env_key: str
    value: str


def set_storage_env_value(
    *,
    storage_root: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    storage_env_filename: str = "apprc.storage.env",
) -> EnvFileUpdate:
    """Set one value in a storage dotenv file.

    :param storage_root: Active storage root from the application selector.
    :param reference: Full env key, dotted config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param storage_env_filename: Storage dotenv filename.
    :return: Written file, key, and normalized value.
    :raises ValueError: If the key is unknown, read-only, or invalid.
    :raises StorageRootPathError: If the storage root cannot be used.
    """
    root = require_existing_storage_root(storage_root)
    path = storage_env_path(root, filename=storage_env_filename)
    try:
        return set_env_file_value(
            path=path,
            reference=reference,
            raw_value=raw_value,
            owners=owners,
            layer_name=storage_env_filename,
        )
    except (ConfigHomeError, OSError) as exc:
        raise StorageRootPathError(str(exc)) from exc


def set_env_file_value(
    *,
    path: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    layer_name: str,
) -> EnvFileUpdate:
    """Set one override value in an AppRC dotenv file.

    :param path: Dotenv file to update.
    :param reference: Full env key, dotted config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param layer_name: Human-readable layer name for read-only errors.
    :return: Written file, key, and normalized value.
    :raises ValueError: If the key is unknown, read-only, or invalid.
    """
    owner, spec = resolve_config_field_reference(owners, reference)
    if not spec.editable:
        raise ValueError(
            f"{owner.env_key(spec.name)} is managed outside {layer_name}."
        )
    value = normalize_env_value(spec, raw_value)
    env_key = owner.env_key(spec.name)
    path = ensure_env_file(path)
    values = read_env_file(path)
    values[env_key] = value
    written_path = write_env_file(path, values, owners=owners)
    return EnvFileUpdate(path=written_path, env_key=env_key, value=value)


def clear_storage_env_value(
    *,
    storage_root: Path,
    reference: str,
    owners: Iterable[ConfigOwner],
    storage_env_filename: str = "apprc.storage.env",
) -> EnvFileUpdate | None:
    """Remove one override value from a storage dotenv file.

    :param storage_root: Active storage root from the application selector.
    :param reference: Full env key, dotted config path, or unique field name.
    :param owners: Config owners to search.
    :param storage_env_filename: Storage dotenv filename.
    :return: Written file and removed key, or ``None`` when the key was absent.
    :raises ValueError: If the key is unknown or read-only.
    :raises StorageRootPathError: If the storage root cannot be used.
    """
    root = require_existing_storage_root(storage_root)
    path = storage_env_path(root, filename=storage_env_filename)
    try:
        return clear_env_file_value(
            path=path,
            reference=reference,
            owners=owners,
            layer_name=storage_env_filename,
        )
    except (ConfigHomeError, OSError) as exc:
        raise StorageRootPathError(str(exc)) from exc


def clear_env_file_value(
    *,
    path: Path,
    reference: str,
    owners: Iterable[ConfigOwner],
    layer_name: str,
) -> EnvFileUpdate | None:
    """Remove one override value from an AppRC dotenv file.

    :param path: Dotenv file to update.
    :param reference: Full env key, dotted config path, or unique field name.
    :param owners: Config owners to search.
    :param layer_name: Human-readable layer name for read-only errors.
    :return: Written file and removed key, or ``None`` when the key was absent.
    :raises ValueError: If the key is unknown or read-only.
    """
    owner, spec = resolve_config_field_reference(owners, reference)
    if not spec.editable:
        raise ValueError(
            f"{owner.env_key(spec.name)} is managed outside {layer_name}."
        )
    env_key = owner.env_key(spec.name)
    path = Path(path).expanduser()
    if not path.is_file():
        return None
    values = read_env_file(path)
    if env_key not in values:
        return None
    values.pop(env_key)
    written_path = write_env_file(path, values, owners=owners)
    return EnvFileUpdate(path=written_path, env_key=env_key, value="")
