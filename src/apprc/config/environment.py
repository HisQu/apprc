"""Load dotenv layers into one CLI process at application startup.

AppRC imports are side-effect free: importing a config dataclass does not read
``.env`` files or modify the process environment. Application entrypoints call
``bootstrap_env`` once, before runtime config objects are created, to merge the
packaged shared defaults, the selected storage-local dotenv file, an optional
explicit ``--env-file``, and the values already present in ``os.environ``.

The helper mutates only the current Python process. It never writes dotenv
files and never changes the parent shell. Registry selection is delegated to
:mod:`apprc.config.storage_registry`; storage-local editing is delegated to
:mod:`apprc.config.local_env`.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import re
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Mapping, Protocol

# == 3rd Party ===============================
from dotenv import dotenv_values

# == Internal ================================
from apprc.logging import get_logger
from apprc.config.paths import normalize_storage_root_path
from apprc.config.storage_registry import (
    StorageRecord,
    StorageRegistry,
    apprc_toml_env_key,
    configured_apprc_toml_path,
    load_storage_registry,
)

LOG = get_logger(__name__)
_WINDOWS_DRIVE_SELECTOR_PATTERN = re.compile(r"^[A-Za-z]:")


class BootstrapLogger(Protocol):
    """Logger interface needed for bootstrap status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""


@dataclass(frozen=True, slots=True)
class EnvBootstrapSpec:
    """Application-specific bootstrap contract.

    :param app_name: Lowercase application name used in env var derivation.
    :param display_name: Human-readable application name in log messages.
    :param config_package: Package containing the shared dotenv resource.
    :param storage_env_key: Env key that stores the active storage selector.
    :param apprc_toml_filename: Per-user TOML registry filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    storage_env_key: str
    apprc_toml_filename: str
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def apprc_toml_env_key(self) -> str:
        """Return the env var that overrides the registry file path."""
        return apprc_toml_env_key(self.app_name)

    def registry_path(self) -> Path:
        """Return the env-selected user registry path for this application."""
        return configured_apprc_toml_path(
            app_name=self.app_name,
            apprc_toml_filename=self.apprc_toml_filename,
        )


@dataclass(frozen=True, slots=True)
class EnvBootstrapResult:
    """Files and storage selected during CLI env bootstrap.

    :param shared_env: Packaged shared dotenv path loaded into the process, or
        ``None`` when dotenv layers were skipped.
    :param local_env: Active storage-local dotenv candidate considered during
        loading, or ``None`` when dotenv layers were skipped or no storage root
        is known. The path may not exist because missing local files are
        optional.
    :param env_file: Explicit dotenv file passed through the CLI.
    :param registry_path: Per-user storage registry path.
    :param storage_name: Registry storage record selected for this bootstrap,
        usually by ``--storage`` or the registry default.
    :param storage_root: Active storage root, when known.
    :param used_default_storage: Whether the registry default was selected.
    :param storage_count: Number of configured registry storages.
    """

    shared_env: Path | None
    local_env: Path | None
    env_file: Path | None
    registry_path: Path
    storage_name: str | None
    storage_root: Path | None
    used_default_storage: bool
    storage_count: int


def bootstrap_env(
    *,
    spec: EnvBootstrapSpec,
    env_file: Path | None = None,
    env_file_overrides_os_environ: bool = False,
    load_dotenv_layers: bool = True,
    registry_storage_name: str | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Populate ``os.environ`` for one application CLI process.

    Imports stay side-effect free; entrypoints call this helper before building
    runtime config objects. The parent shell is not mutated. Dotenv layers are
    the packaged ``.env.shared``, the active storage-local ``.env.local``, and
    the optional explicit ``env_file``. The explicit file always overrides the
    packaged and storage-local dotenv layers. When dotenv layers are skipped,
    the explicit ``env_file`` is still parsed so it can guide storage-root
    selection, but its values are not merged into ``os.environ``.

    :param spec: Application-specific bootstrap contract.
    :param env_file: Optional invocation-local dotenv file that outranks the
        packaged ``.env.shared`` and active storage-local ``.env.local``.
    :param env_file_overrides_os_environ: Whether ``env_file`` beats already
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``.env.shared``,
        storage-local ``.env.local``, and explicit dotenv values should be
        merged into this process. Registry selection still runs when this is
        ``False``.
    :param registry_storage_name: Optional ``--storage`` selector from the user
        registry. When provided, that registry root becomes the active storage
        root and determines the storage-local dotenv candidate.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    """
    original_env = dict(os.environ)
    explicit_values = _read_explicit_env_file(env_file)
    registry = load_storage_registry(spec.registry_path())
    selected_storage, explicit_storage_root, used_default_storage = (
        _select_storage(
            spec=spec,
            registry=registry,
            registry_storage_name=registry_storage_name,
            original_env=original_env,
            explicit_values=explicit_values,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
    )
    active_storage_root = (
        selected_storage.root
        if selected_storage is not None
        else explicit_storage_root
    )
    if active_storage_root is None:
        raise ValueError(
            f"{spec.storage_env_key} is required and must be either a "
            "registered storage name or an explicit storage path. Pass "
            "--storage NAME or export "
            f'{spec.storage_env_key}="/path/to/storage".'
        )

    active_local_env = Path(active_storage_root) / spec.local_env_filename

    if (
        selected_storage is not None
        and used_default_storage
        and len(registry.storages) > 1
    ):
        log = logger or LOG
        log.info(
            f"Using default {spec.display_name} storage "
            f"{selected_storage.name!r} at {selected_storage.root} from "
            f"{registry.path}. Pass --storage to select another storage."
        )

    shared_env_path: Path | None = None
    loaded_local_env: Path | None = None
    if load_dotenv_layers:
        loaded_local_env = active_local_env
        with as_file(_shared_env_resource(spec)) as shared_env:
            if not shared_env.is_file():
                raise FileNotFoundError(
                    f"Did not find packaged .env.shared at {shared_env}."
                )
            shared_env_path = shared_env
            merged = _merged_env_values(
                shared_values=_read_dotenv_file(shared_env),
                local_values=_read_dotenv_file(active_local_env),
                explicit_values=explicit_values,
                original_env=original_env,
                env_file_overrides_os_environ=env_file_overrides_os_environ,
            )
            os.environ.update(merged)
    os.environ[spec.storage_env_key] = str(active_storage_root)

    return EnvBootstrapResult(
        shared_env=shared_env_path,
        local_env=loaded_local_env,
        env_file=env_file,
        registry_path=registry.path,
        storage_name=(
            selected_storage.name if selected_storage is not None else None
        ),
        storage_root=active_storage_root,
        used_default_storage=used_default_storage,
        storage_count=len(registry.storages),
    )


def resolve_storage_selector_value(
    *,
    registry: StorageRegistry,
    raw_value: str,
    storage_env_key: str,
) -> tuple[StorageRecord | None, Path]:
    """Resolve one storage env value to a record name or path.

    :param registry: Parsed AppRC TOML storage registry.
    :param raw_value: Value from ``<APP>_STORAGE`` or an explicit env file.
    :param storage_env_key: Env key used in human-facing errors.
    :return: Selected registry record, if any, and resolved storage root.
    :raises ValueError: If a bare selector is not registered.
    """
    selector = raw_value.strip()
    if selector in registry.storages:
        record = registry.selected(selector)
        return record, record.root
    if _is_storage_path_like(selector):
        return None, normalize_storage_root_path(selector).resolve()
    known = ", ".join(sorted(registry.storages)) or "<none>"
    raise ValueError(
        f"{storage_env_key} value {selector!r} is not a registered storage "
        f"name in {registry.path}. Known storages: {known}. Use "
        f"{'./' + selector!r} if you meant a relative storage path."
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


def _select_storage(
    *,
    spec: EnvBootstrapSpec,
    registry: StorageRegistry,
    registry_storage_name: str | None,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> tuple[StorageRecord | None, Path | None, bool]:
    """Return storage selected by CLI or env selector."""
    if registry_storage_name is not None:
        record = registry.selected(registry_storage_name)
        return record, record.root, False
    storage_selector = _storage_selector_value(
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        storage_env_key=spec.storage_env_key,
    )
    if storage_selector:
        record, root = resolve_storage_selector_value(
            registry=registry,
            raw_value=storage_selector,
            storage_env_key=spec.storage_env_key,
        )
        return record, root, False
    return None, None, False


def _shared_env_resource(spec: EnvBootstrapSpec) -> Traversable:
    """Return the packaged shared dotenv resource."""
    return files(spec.config_package).joinpath(spec.shared_env_filename)


def _read_explicit_env_file(env_file: Path | None) -> dict[str, str]:
    """Read the optional explicit dotenv file.

    Explicit values may guide storage selection even when dotenv layers
    are not merged into ``os.environ``.
    """
    if env_file is None:
        return {}
    resolved = Path(env_file).expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(f"Explicit env file does not exist: {resolved}")
    return _read_dotenv_file(resolved)


def _read_dotenv_file(path: Path | None) -> dict[str, str]:
    """Read one dotenv file, ignoring missing optional files."""
    if path is None or not path.is_file():
        return {}
    raw_values = dotenv_values(path)
    return {
        key: value
        for key, value in raw_values.items()
        if isinstance(value, str)
    }


def _merged_env_values(
    *,
    shared_values: Mapping[str, str],
    local_values: Mapping[str, str],
    explicit_values: Mapping[str, str],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_os_environ:
        return {
            **shared_values,
            **local_values,
            **original_env,
            **explicit_values,
        }
    return {
        **shared_values,
        **local_values,
        **explicit_values,
        **original_env,
    }


def _storage_selector_value(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    storage_env_key: str,
) -> str | None:
    """Return the storage selector implied by ``os.environ`` and ``env_file``."""
    if env_file_overrides_os_environ:
        return explicit_values.get(storage_env_key) or original_env.get(
            storage_env_key
        )
    return original_env.get(storage_env_key) or explicit_values.get(
        storage_env_key
    )
