"""Read and write AppRC dotenv override files.

App-wide and storage-specific dotenv files use the same validation and write
rules: values are checked against declared ``ConfigField`` metadata, known
keys are written in declaration order, and unknown keys are preserved after
known AppRC keys.
"""

from __future__ import annotations

# == Standard Library ========================
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

# == 3rd Party ===============================
from dotenv import dotenv_values
from typed_settings.exceptions import InvalidSettingsError

# == Internal ================================
from apprc.runtime_config._env_loading import parse_env_field_value
from apprc.runtime_config.config_home import (
    ConfigHomeError,
    ensure_text_file,
    write_text_atomic,
)
from apprc.runtime_config.contract.lookup import (
    iter_config_fields,
    resolve_config_field_reference,
)
from apprc.runtime_config.contract.schema import ConfigField, ConfigOwner
from apprc.runtime_config.contract.schema_validation import (
    validate_python_field_value,
)


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


def storage_env_path(
    storage_root: Path,
    filename: str = ".env.apprc-storage",
) -> Path:
    """Return the dotenv override file owned by one storage root.

    :param storage_root: Storage root that owns the dotenv file.
    :param filename: Dotenv filename inside the storage root.
    :return: Resolved storage dotenv path.
    """
    return Path(storage_root).expanduser().resolve() / filename


def ensure_storage_env_file(
    storage_root: Path,
    filename: str = ".env.apprc-storage",
) -> Path:
    """Create the storage dotenv file when it is missing.

    :param storage_root: Directory that owns the storage dotenv file.
    :param filename: Dotenv filename inside the storage root.
    :return: Path to the existing dotenv file.
    :raises StorageRootPathError: If the root is missing or not a directory.
    """
    from apprc.runtime_config.storage.paths import StorageRootPathError

    root = _require_existing_storage_root(storage_root)
    path = root / filename
    try:
        return ensure_text_file(path)
    except ConfigHomeError as exc:
        raise StorageRootPathError(str(exc)) from exc


def ensure_env_file(path: Path) -> Path:
    """Create an AppRC dotenv override file when it is missing.

    :param path: Dotenv path to create.
    :return: Path to the existing dotenv file.
    """
    return ensure_text_file(path)


def read_env_file(path: Path | None) -> dict[str, str]:
    """Parse an optional AppRC dotenv file into string key/value pairs.

    :param path: Dotenv file path, or ``None`` for an inactive layer.
    :return: Parsed string values. Missing files return an empty mapping.
    """
    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    values = dotenv_values(env_path)
    return {
        key: value for key, value in values.items() if isinstance(value, str)
    }


def write_env_file(
    path: Path,
    values: Mapping[str, str],
    *,
    owners: Iterable[ConfigOwner],
) -> Path:
    """Write deterministic AppRC dotenv values.

    :param path: Dotenv file path to replace.
    :param values: Env values keyed by concrete environment variable.
    :param owners: Config owners that define known AppRC env keys.
    :return: Written dotenv path.
    """
    env_path = Path(path).expanduser()
    ordered_keys = _ordered_env_keys(owners)
    known_key_set = set(ordered_keys)
    known = [key for key in ordered_keys if key in values]
    unknown = sorted(key for key in values if key not in known_key_set)
    lines = [
        f"{key}={_dotenv_quote(values[key])}" for key in (*known, *unknown)
    ]
    return write_text_atomic(env_path, "\n".join(lines).rstrip() + "\n")


def set_storage_env_value(
    *,
    storage_root: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    storage_env_filename: str = ".env.apprc-storage",
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
    from apprc.runtime_config.storage.paths import StorageRootPathError

    root = _require_existing_storage_root(storage_root)
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
    storage_env_filename: str = ".env.apprc-storage",
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
    from apprc.runtime_config.storage.paths import StorageRootPathError

    root = _require_existing_storage_root(storage_root)
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


def normalize_env_value(spec: ConfigField, raw_value: str) -> str:
    """Validate and normalize one user-entered dotenv value."""
    value = raw_value.strip()
    if value == "" and (spec.required or not spec.has_default()):
        raise ValueError(f"{spec.name} is required and cannot be empty.")
    try:
        parsed = parse_env_field_value(spec, value)
    except InvalidSettingsError as exc:
        raise ValueError(str(exc)) from exc
    validate_python_field_value(spec, parsed)
    return _stringify_env_value(parsed)


def _require_existing_storage_root(storage_root: Path) -> Path:
    """Return ``storage_root`` after proving it already exists.

    :param storage_root: Storage root expected to own a dotenv file.
    :return: Resolved existing storage root.
    :raises StorageRootPathError: If the root is missing or not a directory.
    """
    from apprc.runtime_config.storage.paths import StorageRootPathError

    root = Path(storage_root).expanduser().resolve()
    if not root.exists():
        raise StorageRootPathError(f"Storage root does not exist: {root!s}")
    if not root.is_dir():
        raise StorageRootPathError(f"Storage root is not a directory: {root!s}")
    return root


def _ordered_env_keys(owners: Iterable[ConfigOwner]) -> tuple[str, ...]:
    """Return known env keys in owner declaration order."""
    return tuple(
        owner.env_key(spec.name) for owner, spec in iter_config_fields(owners)
    )


def _stringify_env_value(value: object) -> str:
    """Return a deterministic dotenv string for a parsed runtime value."""
    if isinstance(value, bool):
        if value:
            return "true"
        return "false"
    return str(value)


def _dotenv_quote(value: str) -> str:
    """Quote one value for deterministic dotenv output."""
    return json.dumps(value)
