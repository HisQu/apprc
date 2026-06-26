"""Read and write AppRC dotenv override files.

Storage-enabled apps use storage-local dotenv files. Storage-free apps use one
app-global dotenv file in the AppRC config home. Both files validate values
against the same ``ConfigField`` declarations used by runtime loading, write
keys in declaration order, and preserve unknown dotenv keys after known AppRC
keys.

It intentionally does not mutate ``os.environ``. Entrypoints use
:mod:`apprc.runtime_config.bootstrap.orchestrator` to decide which dotenv
layers enter the current process.
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
from apprc.runtime_config.config_home import ensure_text_file, write_text_atomic
from apprc.runtime_config._env_loading import (
    parse_env_field_value,
)
from apprc.runtime_config.storage.paths import StorageRootPathError
from apprc.runtime_config.contract.lookup import (
    iter_config_fields,
    resolve_config_field_reference,
)
from apprc.runtime_config.contract.schema import ConfigField, ConfigOwner
from apprc.runtime_config.contract.schema_validation import (
    validate_python_field_value,
)


@dataclass(frozen=True, slots=True)
class LocalEnvUpdate:
    """Result of one storage-local env edit.

    :param path: Dotenv file that was written.
    :param env_key: Concrete env key written to the file.
    :param value: Normalized string value stored in the file.
    """

    path: Path
    env_key: str
    value: str


def local_env_path(
    storage_root: Path,
    filename: str = ".env.local",
) -> Path:
    """Return the override file owned by one storage root."""
    return Path(storage_root).expanduser().resolve() / filename


def ensure_local_env_file(
    storage_root: Path,
    filename: str = ".env.local",
) -> Path:
    """Create the storage-local dotenv file when it is missing.

    :param storage_root: Directory that owns the local override file.
    :param filename: Dotenv filename inside the storage root.
    :return: Path to the existing dotenv file.
    """
    root = _require_existing_storage_root(storage_root)
    path = root / filename
    return ensure_text_file(path)


def ensure_env_file(path: Path) -> Path:
    """Create an AppRC dotenv override file when it is missing.

    :param path: Dotenv path to create.
    :return: Path to the existing dotenv file.
    """
    return ensure_text_file(path)


def read_local_env(path: Path) -> dict[str, str]:
    """Parse an optional dotenv file into string key/value pairs."""
    return read_env_file(path)


def read_env_file(path: Path) -> dict[str, str]:
    """Parse an optional AppRC dotenv file into string key/value pairs."""
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    values = dotenv_values(env_path)
    return {
        key: value for key, value in values.items() if isinstance(value, str)
    }


def write_local_env(
    path: Path,
    values: Mapping[str, str],
    *,
    owners: Iterable[ConfigOwner],
) -> Path:
    """Write deterministic storage-local dotenv values.

    Known app keys are written in owner declaration order. Unknown keys are
    preserved and sorted afterward so user-owned extras do not disappear.
    """
    env_path = Path(path).expanduser()
    _require_existing_storage_root(env_path.parent)
    return write_env_file(env_path, values, owners=owners)


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


def _require_existing_storage_root(storage_root: Path) -> Path:
    """Return ``storage_root`` after proving it already exists.

    :param storage_root: Storage root expected to own a local dotenv file.
    :return: Resolved existing storage root.
    :raises StorageRootPathError: If the root is missing or not a directory.
    """
    root = Path(storage_root).expanduser().resolve()
    if not root.exists():
        raise StorageRootPathError(f"Storage root does not exist: {root!s}")
    if not root.is_dir():
        raise StorageRootPathError(f"Storage root is not a directory: {root!s}")
    return root


def set_local_env_value(
    *,
    storage_root: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    local_env_filename: str = ".env.local",
) -> LocalEnvUpdate:
    """Set one override value in ``<storage-root>/.env.local``.

    :param storage_root: Active storage root from the application registry.
    :param reference: Full env key, dotted config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param local_env_filename: Storage-local dotenv filename.
    :return: Written file, key, and normalized value.
    :raises ValueError: If the key is unknown, read-only, or invalid.
    """
    path = local_env_path(storage_root, filename=local_env_filename)
    return set_env_file_value(
        path=path,
        reference=reference,
        raw_value=raw_value,
        owners=owners,
        layer_name=".env.local",
    )


def set_env_file_value(
    *,
    path: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    layer_name: str,
) -> LocalEnvUpdate:
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
    return LocalEnvUpdate(path=written_path, env_key=env_key, value=value)


def clear_local_env_value(
    *,
    storage_root: Path,
    reference: str,
    owners: Iterable[ConfigOwner],
    local_env_filename: str = ".env.local",
) -> LocalEnvUpdate | None:
    """Remove one override value from ``<storage-root>/.env.local``.

    :param storage_root: Active storage root from the application registry.
    :param reference: Full env key, dotted config path, or unique field name.
    :param owners: Config owners to search.
    :param local_env_filename: Storage-local dotenv filename.
    :return: Written file and removed key, or ``None`` when the key was absent.
    :raises ValueError: If the key is unknown or read-only.
    """
    path = local_env_path(storage_root, filename=local_env_filename)
    return clear_env_file_value(
        path=path,
        reference=reference,
        owners=owners,
        layer_name=".env.local",
    )


def clear_env_file_value(
    *,
    path: Path,
    reference: str,
    owners: Iterable[ConfigOwner],
    layer_name: str,
) -> LocalEnvUpdate | None:
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
    path = ensure_env_file(path)
    values = read_env_file(path)
    if env_key not in values:
        return None
    values.pop(env_key)
    written_path = write_env_file(path, values, owners=owners)
    return LocalEnvUpdate(path=written_path, env_key=env_key, value="")


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
