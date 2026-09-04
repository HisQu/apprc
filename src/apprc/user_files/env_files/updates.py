"""Validated set and clear operations for AppRC dotenv files."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# == Internal ================================
from apprc.definition.env_config.lookup import resolve_config_field_reference
from apprc.definition.env_config.schema import ConfigOwner
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    write_text_atomic,
)
from apprc.user_files.env_files.files import (
    require_existing_storage_root,
    storage_dotenv_path,
)
from apprc.user_files.env_files._document import (
    clear_dotenv_document_value,
    set_dotenv_document_value,
)
from apprc.user_files.env_files.values import normalize_env_value
from apprc.user_files.storage_roots.paths import StorageRootPathError


@dataclass(frozen=True, slots=True)
class EnvFileUpdate:
    """Result of one dotenv edit.

    :param path: Dotenv file that was written.
    :param env_key: Concrete env key written to the file.
    :param value: Normalized string value stored in the file.
    :param warnings: User-facing warnings discovered while editing.
    """

    path: Path
    env_key: str
    value: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvFileEditPlan:
    """Describe one validated dotenv write before it changes the file.

    Interactive interfaces inspect this object before applying a write. This
    lets them warn about duplicate assignments while cancellation is still a
    zero-write operation.

    :param path: Dotenv path that will be written.
    :param env_key: Concrete environment key being changed.
    :param value: Normalized value stored by a set operation.
    :param text: Complete file text after the edit.
    :param warnings: User-facing warnings about the planned edit.
    :param duplicate_lines: Later active assignments that will be disabled.
    """

    path: Path
    env_key: str
    value: str
    text: str
    warnings: tuple[str, ...] = ()
    duplicate_lines: tuple[int, ...] = ()


def set_storage_dotenv_value(
    *,
    storage_root: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    storage_dotenv_filename: str = "apprc.storage.env",
) -> EnvFileUpdate:
    """Set one value in a storage dotenv file.

    :param storage_root: Active storage root from the application selector.
    :param reference: Full env key, dotted config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param storage_dotenv_filename: Storage dotenv filename.
    :return: Written file, key, and normalized value.
    :raises ValueError: If the key is unknown, read-only, or invalid.
    :raises StorageRootPathError: If the storage root cannot be used.
    """
    try:
        plan = plan_storage_dotenv_value_update(
            storage_root=storage_root,
            reference=reference,
            raw_value=raw_value,
            owners=owners,
            storage_dotenv_filename=storage_dotenv_filename,
        )
        return apply_env_file_edit(plan)
    except (AppRCDirectoryError, OSError) as exc:
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
    plan = plan_env_file_value_update(
        path=path,
        reference=reference,
        raw_value=raw_value,
        owners=owners,
        layer_name=layer_name,
    )
    return apply_env_file_edit(plan)


def plan_storage_dotenv_value_update(
    *,
    storage_root: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    storage_dotenv_filename: str = "apprc.storage.env",
) -> EnvFileEditPlan:
    """Prepare a storage dotenv edit without writing it.

    :param storage_root: Active storage root from the application selector.
    :param reference: Full env key, config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param storage_dotenv_filename: Storage dotenv filename.
    :return: Validated edit ready to apply.
    :raises StorageRootPathError: If the storage root cannot be used.
    """
    root = require_existing_storage_root(storage_root)
    path = storage_dotenv_path(root, filename=storage_dotenv_filename)
    return plan_env_file_value_update(
        path=path,
        reference=reference,
        raw_value=raw_value,
        owners=owners,
        layer_name=storage_dotenv_filename,
    )


def plan_env_file_value_update(
    *,
    path: Path,
    reference: str,
    raw_value: str,
    owners: Iterable[ConfigOwner],
    layer_name: str,
) -> EnvFileEditPlan:
    """Prepare one source-preserving dotenv edit without writing it.

    :param path: Dotenv file that will receive the value.
    :param reference: Full env key, config path, or unique field name.
    :param raw_value: User-provided value before type validation.
    :param owners: Config owners to search.
    :param layer_name: Human-readable layer name for read-only errors.
    :return: Validated edit ready for confirmation or immediate application.
    """
    owner, spec = resolve_config_field_reference(owners, reference)
    if not spec.editable:
        raise ValueError(
            f"{owner.env_key(spec.name)} is managed outside {layer_name}."
        )
    value = normalize_env_value(spec, raw_value)
    env_key = owner.env_key(spec.name)
    env_path = Path(path).expanduser()
    text = (
        _read_text_preserving_newlines(env_path) if env_path.is_file() else ""
    )
    edit = set_dotenv_document_value(text, env_key=env_key, value=value)
    warnings = _duplicate_warnings(
        path=env_path,
        env_key=env_key,
        first_line=edit.matched_lines[0] if edit.matched_lines else None,
        duplicate_lines=edit.disabled_duplicate_lines,
    )
    return EnvFileEditPlan(
        path=env_path,
        env_key=env_key,
        value=value,
        text=edit.text,
        warnings=warnings,
        duplicate_lines=edit.disabled_duplicate_lines,
    )


def apply_env_file_edit(plan: EnvFileEditPlan) -> EnvFileUpdate:
    """Write a previously validated dotenv edit.

    :param plan: Complete edit created by an AppRC planning helper.
    :return: Written file, key, value, and warnings.
    """
    written_path = write_text_atomic(plan.path, plan.text)
    return EnvFileUpdate(
        path=written_path,
        env_key=plan.env_key,
        value=plan.value,
        warnings=plan.warnings,
    )


def clear_storage_dotenv_value(
    *,
    storage_root: Path,
    reference: str,
    owners: Iterable[ConfigOwner],
    storage_dotenv_filename: str = "apprc.storage.env",
) -> EnvFileUpdate | None:
    """Remove one override value from a storage dotenv file.

    :param storage_root: Active storage root from the application selector.
    :param reference: Full env key, dotted config path, or unique field name.
    :param owners: Config owners to search.
    :param storage_dotenv_filename: Storage dotenv filename.
    :return: Written file and removed key, or ``None`` when the key was absent.
    :raises ValueError: If the key is unknown or read-only.
    :raises StorageRootPathError: If the storage root cannot be used.
    """
    root = require_existing_storage_root(storage_root)
    path = storage_dotenv_path(root, filename=storage_dotenv_filename)
    try:
        return clear_env_file_value(
            path=path,
            reference=reference,
            owners=owners,
            layer_name=storage_dotenv_filename,
        )
    except (AppRCDirectoryError, OSError) as exc:
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
    text = _read_text_preserving_newlines(path)
    edit = clear_dotenv_document_value(text, env_key=env_key)
    if not edit.matched_lines:
        return None
    written_path = write_text_atomic(path, edit.text)
    return EnvFileUpdate(path=written_path, env_key=env_key, value="")


def _duplicate_warnings(
    *,
    path: Path,
    env_key: str,
    first_line: int | None,
    duplicate_lines: tuple[int, ...],
) -> tuple[str, ...]:
    """Return a concise warning for active duplicate assignments.

    :param path: Dotenv file being edited.
    :param env_key: Environment key with multiple assignments.
    :param first_line: First assignment line that remains active.
    :param duplicate_lines: Later assignments that will be commented out.
    :return: Empty tuple or one warning.
    """
    if not duplicate_lines:
        return ()
    duplicate_text = ", ".join(str(line) for line in duplicate_lines)
    duplicate_location = (
        f"line {duplicate_text}"
        if len(duplicate_lines) == 1
        else f"lines {duplicate_text}"
    )
    return (
        f"{path}: {env_key} is assigned more than once. AppRC will update "
        f"line {first_line} and comment out duplicate {duplicate_location}.",
    )


def _read_text_preserving_newlines(path: Path) -> str:
    """Read UTF-8 text without universal-newline conversion.

    :param path: Existing dotenv file.
    :return: Exact decoded text, including original line endings.
    """
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()
