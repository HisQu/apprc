"""Resolve active storage selectors from CLI and environment values.

Runtime commands require an explicit active storage selector. The selector may
be a registered storage name or a path-like value from ``<APP>_STORAGE``. The
same rules are shared by bootstrap and diagnostics so ``config doctor`` reports
the state that runtime will actually use.
"""

from __future__ import annotations

# == Standard Library ========================
import re
from dataclasses import dataclass
from pathlib import Path

# == Internal ================================
from apprc.config.paths import normalize_storage_root_path
from apprc.config.storage_registry import StorageRegistry

_WINDOWS_DRIVE_SELECTOR_PATTERN = re.compile(r"^[A-Za-z]:")


class StorageSelectorError(ValueError):
    """Readable storage-selector failure with optional CLI parameter context.

    :param message: Human-facing error text.
    :param param_hint: Optional Typer parameter hint for CLI callers.
    """

    def __init__(self, message: str, *, param_hint: str | None = None) -> None:
        """Store the message and CLI parameter hint."""
        super().__init__(message)
        self.param_hint = param_hint


@dataclass(frozen=True, slots=True)
class StorageSelection:
    """Resolved active storage selector.

    :param source: User-visible selector source, such as ``--storage`` or the
        app-specific storage env key.
    :param raw_value: Original selector value before resolution.
    :param storage_name: Registered storage name when the selector used one.
    :param root: Resolved storage root used for runtime dotenv loading.
    """

    source: str
    raw_value: str
    storage_name: str | None
    root: Path


def resolve_registered_storage_name(
    *,
    registry: StorageRegistry,
    name: str,
    source: str = "--storage",
) -> StorageSelection:
    """Resolve one registered storage selector.

    :param registry: Parsed AppRC TOML storage registry.
    :param name: Storage name selected by a CLI option.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved storage selection.
    :raises StorageSelectorError: If ``name`` is not registered.
    """
    try:
        record = registry.selected(name)
    except ValueError as exc:
        raise StorageSelectorError(str(exc), param_hint=source) from exc
    return StorageSelection(
        source=source,
        raw_value=name,
        storage_name=record.name,
        root=record.root,
    )


def resolve_storage_selector_value(
    *,
    registry: StorageRegistry,
    raw_value: str,
    storage_env_key: str,
    source: str | None = None,
) -> StorageSelection:
    """Resolve one storage env value to a registered name or path.

    :param registry: Parsed AppRC TOML storage registry.
    :param raw_value: Value from ``<APP>_STORAGE`` or an explicit env file.
    :param storage_env_key: Env key used in human-facing errors.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved storage selection.
    :raises StorageSelectorError: If a bare selector is not registered.
    """
    selector = raw_value.strip()
    selection_source = source or storage_env_key
    if selector in registry.storages:
        record = registry.selected(selector)
        return StorageSelection(
            source=selection_source,
            raw_value=selector,
            storage_name=record.name,
            root=record.root,
        )
    if _is_storage_path_like(selector):
        return StorageSelection(
            source=selection_source,
            raw_value=selector,
            storage_name=None,
            root=normalize_storage_root_path(selector).resolve(),
        )
    known = ", ".join(sorted(registry.storages)) or "<none>"
    raise StorageSelectorError(
        f"{storage_env_key} value {selector!r} is not a registered storage "
        f"name in {registry.path}. Known storages: {known}. Use "
        f"{'./' + selector!r} if you meant a relative storage path.",
        param_hint=storage_env_key,
    )


def missing_storage_selector_error(
    storage_env_key: str,
) -> StorageSelectorError:
    """Return the runtime error for a missing active storage selector.

    :param storage_env_key: Env key that should hold the active storage selector.
    :return: Error carrying CLI parameter context.
    """
    return StorageSelectorError(
        f"{storage_env_key} is required and must be either a registered "
        "storage name or an explicit storage path. Pass --storage NAME or "
        f'export {storage_env_key}="/path/to/storage".',
        param_hint=storage_env_key,
    )


def _is_storage_path_like(value: str) -> bool:
    """Return whether selector text should be interpreted as a path."""
    path = Path(value).expanduser()
    return (
        value in {".", "..", "~"}
        or "/" in value
        or "\\" in value
        or path.is_absolute()
        or value.startswith("~/")
        or _WINDOWS_DRIVE_SELECTOR_PATTERN.match(value) is not None
    )
