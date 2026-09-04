"""Resolve active named storage selectors.

Runtime storage selectors are names from ``apprc.toml``. Paths are registry
attributes and never double as selectors.
"""

from __future__ import annotations

# == Standard Library ===========================================
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.user_files.storage_roots.model import StorageRegistry

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


@dataclass(frozen=True, slots=True)
class StorageSelection:
    """Resolved active storage selector.

    :param source: User-visible selector source.
    :param raw_value: Original selector value.
    :param storage_name: Registered storage name.
    :param root: Resolved registered root.
    """

    source: str
    raw_value: str
    storage_name: str
    root: Path


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
    )


def resolve_active_storage_selection(
    *,
    registry: StorageRegistry,
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

    :param registry: Parsed storage registry.
    :param storage: Optional ``--storage`` name.
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
        selected_storage=registry.selected_storage,
    )
    if selected is None:
        return None
    source, name = selected
    return resolve_registered_storage_name(
        registry=registry,
        name=name,
        source=source,
    )


def resolve_storage_selector_value(
    *,
    registry: StorageRegistry,
    raw_value: str,
    storage_selector_env_key: str,
    source: str | None = None,
) -> StorageSelection:
    """Resolve one environment selector as a registered name.

    :param registry: Parsed storage registry.
    :param raw_value: Selector from process or explicit dotenv state.
    :param storage_selector_env_key: Environment key used in errors.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved named storage.
    """
    return resolve_registered_storage_name(
        registry=registry,
        name=raw_value,
        source=source or storage_selector_env_key,
    )


def missing_storage_selector_error(
    storage_selector_env_key: str,
) -> MissingStorageSelectorError:
    """Return the runtime error for a missing active storage selector.

    :param storage_selector_env_key: Environment selector key.
    :return: Error carrying CLI parameter context.
    """
    return MissingStorageSelectorError(
        "No storage is selected. Pass --storage NAME, export "
        f"{storage_selector_env_key}=NAME, or run config storage select NAME.",
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

    Migration uses this check to distinguish released 0.19 path selectors
    from named selectors. Runtime resolution rejects either form as a path.

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
