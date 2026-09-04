"""Resolve active storage names and filesystem paths."""

from __future__ import annotations

# == Standard Library ===========================================
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == Internal ===================================================
from apprc.user_files.storage_roots.model import StorageRegistry
from apprc.user_files.storage_roots.paths import resolve_storage_root_path

_WINDOWS_DRIVE_SELECTOR_PATTERN = re.compile(r"^[A-Za-z]:")


class StorageSelectorError(ValueError):
    """Readable storage-selector failure with optional CLI context.

    :param message: Human-facing error text.
    :param param_hint: Optional Typer parameter hint for CLI callers.
    """

    def __init__(self, message: str, *, param_hint: str | None = None) -> None:
        """Store the message and CLI parameter hint."""
        super().__init__(message)
        self.param_hint = param_hint


class MissingStorageSelectorError(StorageSelectorError):
    """No CLI, process, explicit-dotenv, or registry selector was found."""


class StorageNotInitializedError(StorageSelectorError):
    """A selected filesystem root lacks a readable AppRC marker.

    :param message: Human-facing failure text.
    :param storage_root: Root that setup may initialize.
    :param storage_name: Associated registry name, when known.
    :param param_hint: CLI selector source.
    """

    def __init__(
        self,
        message: str,
        *,
        storage_root: Path,
        storage_name: str | None,
        param_hint: str | None = None,
    ) -> None:
        """Store recovery context with the selector error."""
        super().__init__(message, param_hint=param_hint)
        self.storage_root = storage_root
        self.storage_name = storage_name


@dataclass(frozen=True, slots=True)
class StorageSelection:
    """Resolved active storage selector.

    :param source: User-visible selector source.
    :param raw_value: Original selector value.
    :param storage_name: Associated registered name, if exactly one exists.
    :param root: Resolved storage root.
    :param selector_kind: Whether the selector was a name or path.
    :param matching_storage_names: Registered aliases for a selected path.
    """

    source: str
    raw_value: str
    storage_name: str | None
    root: Path
    selector_kind: Literal["name", "path"] = "name"
    matching_storage_names: tuple[str, ...] = ()


def resolve_registered_storage_name(
    *,
    registry: StorageRegistry,
    name: str,
    source: str = "--storage",
) -> StorageSelection:
    """Resolve one registered storage selector.

    :param registry: Parsed storage registry.
    :param name: Storage name selected by a CLI option or environment value.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved storage selection.
    :raises StorageSelectorError: If ``name`` is a path or is not registered.
    """
    selector = name.strip()
    if not selector:
        raise missing_storage_selector_error("storage selector")
    if storage_selector_is_path_like(selector):
        raise StorageSelectorError(
            f"{source} must contain a registered storage name, not a path: "
            f"{selector!r}.",
            param_hint=source,
        )
    try:
        record = registry.selected(selector)
    except ValueError as exc:
        raise StorageSelectorError(str(exc), param_hint=source) from exc
    return StorageSelection(
        source=source,
        raw_value=selector,
        storage_name=record.name,
        root=record.root,
        selector_kind="name",
        matching_storage_names=(record.name,),
    )


def resolve_active_storage_selection(
    *,
    registry: StorageRegistry | None,
    apprc_toml_path: Path | None = None,
    storage: str | None,
    storage_selector_env_key: str,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> StorageSelection | None:
    """Return the active storage selected by CLI, env, or registry.

    ``--storage`` always wins. The existing explicit-dotenv precedence option
    decides whether a selector from an explicit dotenv beats the process
    environment. ``selected_storage`` is the final fallback.

    :param registry: Parsed storage registry, when one exists.
    :param apprc_toml_path: Fixed registry path used to resolve relative paths.
    :param storage: Optional ``--storage`` name or path.
    :param storage_selector_env_key: Environment selector key.
    :param original_env: Process environment before dotenv loading.
    :param explicit_values: Values read from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        already exported process values.
    :return: Resolved selection, or ``None`` when the registry has no default.
    """
    selected = select_storage_selector(
        storage=storage,
        original_env=original_env,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        storage_selector_env_key=storage_selector_env_key,
        selected_storage=(
            registry.selected_storage if registry is not None else None
        ),
    )
    if selected is None:
        return None
    source, raw_value = selected
    return resolve_storage_selector_value(
        registry=registry,
        apprc_toml_path=apprc_toml_path,
        raw_value=raw_value,
        storage_selector_env_key=storage_selector_env_key,
        source=source,
    )


def resolve_storage_selector_value(
    *,
    registry: StorageRegistry | None,
    apprc_toml_path: Path | None = None,
    raw_value: str,
    storage_selector_env_key: str,
    source: str | None = None,
) -> StorageSelection:
    """Resolve one environment selector as a registered name or path.

    Exact registered names win over path classification. A path associated
    with exactly one registry entry reports that name. Duplicate aliases stay
    readable but make the direct path unassociated so callers cannot claim an
    arbitrary name.

    :param registry: Parsed storage registry, when one exists.
    :param apprc_toml_path: Fixed registry path used to resolve relative paths.
    :param raw_value: Selector from process or explicit dotenv state.
    :param storage_selector_env_key: Environment key used in errors.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved named or path-backed storage.
    """
    selector = raw_value.strip()
    selected_source = source or storage_selector_env_key
    if not selector:
        raise missing_storage_selector_error(storage_selector_env_key)
    if registry is not None and selector in registry.storages:
        return resolve_registered_storage_name(
            registry=registry,
            name=selector,
            source=selected_source,
        )
    if not storage_selector_is_path_like(selector):
        if registry is None:
            raise StorageSelectorError(
                f"{selected_source} contains storage name {selector!r}, but "
                "the AppRC storage registry does not exist. Run config "
                "setup or pass a filesystem path.",
                param_hint=selected_source,
            )
        return resolve_registered_storage_name(
            registry=registry,
            name=selector,
            source=selected_source,
        )

    registry_path = registry.path if registry is not None else apprc_toml_path
    if registry_path is None:
        raise StorageSelectorError(
            f"Cannot resolve relative storage path {selector!r} without the "
            "apprc.toml location.",
            param_hint=selected_source,
        )
    root = resolve_storage_root_path(selector, base=registry_path.parent)
    matching_names = _matching_storage_names(registry, root=root)
    return StorageSelection(
        source=selected_source,
        raw_value=selector,
        storage_name=(matching_names[0] if len(matching_names) == 1 else None),
        root=root,
        selector_kind="path",
        matching_storage_names=matching_names,
    )


def missing_storage_selector_error(
    storage_selector_env_key: str,
) -> MissingStorageSelectorError:
    """Return the runtime error for a missing active storage selector.

    :param storage_selector_env_key: Environment selector key.
    :return: Error carrying CLI parameter context.
    """
    return MissingStorageSelectorError(
        "No storage is selected. Pass --storage NAME_OR_PATH, export "
        f"{storage_selector_env_key}=NAME_OR_PATH, or run config storage "
        "select NAME.",
        param_hint=storage_selector_env_key,
    )


def select_storage_selector(
    *,
    storage: str | None,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    storage_selector_env_key: str,
    selected_storage: str | None,
) -> tuple[str, str] | None:
    """Return the raw selector selected by the documented precedence.

    :param storage: Optional host-level ``--storage`` value.
    :param original_env: Process environment captured before dotenv loading.
    :param explicit_values: Values read from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        already exported process values.
    :param storage_selector_env_key: Environment selector key.
    :param selected_storage: Default name from ``apprc.toml``.
    :return: Source and selector value, or ``None`` when unset.
    """
    if storage is not None:
        return "--storage", storage
    if env_file_overrides_os_environ:
        raw_value = explicit_values.get(
            storage_selector_env_key
        ) or original_env.get(storage_selector_env_key)
    else:
        raw_value = original_env.get(
            storage_selector_env_key
        ) or explicit_values.get(storage_selector_env_key)
    if raw_value:
        return storage_selector_env_key, raw_value
    if selected_storage is not None:
        return "apprc.toml selected_storage", selected_storage
    return None


def storage_selector_is_path_like(value: str) -> bool:
    """Return whether selector text looks like a filesystem path.

    Names remain the default for bare words. Relative filesystem selectors
    therefore use explicit syntax such as ``./data`` or ``data/storage``.

    :param value: Selector text.
    :return: Whether the value has path syntax.
    """
    path = Path(value).expanduser()
    return (
        value in {".", "..", "~"}
        or "/" in value
        or "\\" in value
        or path.is_absolute()
        or value.startswith("~/")
        or _WINDOWS_DRIVE_SELECTOR_PATTERN.match(value) is not None
    )


def _matching_storage_names(
    registry: StorageRegistry | None,
    *,
    root: Path,
) -> tuple[str, ...]:
    """Return registered names whose resolved root equals ``root``.

    :param registry: Parsed registry, when one exists.
    :param root: Resolved direct-path selector.
    :return: Sorted matching storage names.
    """
    if registry is None:
        return ()
    return tuple(
        sorted(
            name
            for name, record in registry.storages.items()
            if resolve_storage_root_path(
                record.root,
                base=registry.path.parent,
            )
            == root
        )
    )
