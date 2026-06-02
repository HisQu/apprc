"""Entrypoint-only environment bootstrap for application commands."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Mapping, Protocol

# == 3rd Party ===============================
from dotenv import dotenv_values

# == Internal ================================
from apprc.logging import get_logger
from apprc.config.storage_registry import (
    StorageRecord,
    StorageRegistry,
    default_storage_registry_path,
    load_storage_registry,
)

LOG = get_logger(__name__)


class BootstrapLogger(Protocol):
    """Logger interface needed for bootstrap status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""


@dataclass(frozen=True, slots=True)
class EnvBootstrapSpec:
    """Application-specific bootstrap contract.

    :param app_name: Lowercase application name used below ``~/.config``.
    :param display_name: Human-readable application name in log messages.
    :param config_package: Package containing the shared dotenv resource.
    :param storage_root_env_key: Env key that stores the active storage root.
    :param registry_filename: Per-user TOML registry filename.
    :param shared_env_filename: Packaged shared dotenv filename.
    :param local_env_filename: Storage-local dotenv override filename.
    """

    app_name: str
    display_name: str
    config_package: str
    storage_root_env_key: str
    registry_filename: str
    shared_env_filename: str = ".env.shared"
    local_env_filename: str = ".env.local"

    def registry_path(self) -> Path:
        """Return the default user registry path for this application."""
        return default_storage_registry_path(
            app_name=self.app_name,
            registry_filename=self.registry_filename,
        )


@dataclass(frozen=True, slots=True)
class EnvBootstrapResult:
    """Files and storage selected during CLI env bootstrap.

    :param shared_env: Packaged shared dotenv path.
    :param local_env: Active storage-local dotenv path, when known.
    :param env_file: Explicit dotenv file passed through the CLI.
    :param registry_path: Per-user storage registry path.
    :param storage_name: Active registry storage name, when selected.
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
    env_file: Path | None,
    env_file_overrides_shell: bool,
    no_dotenv: bool,
    storage_name: str | None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Populate ``os.environ`` for one application CLI process.

    Imports stay side-effect free; entrypoints call this helper before building
    runtime config objects. The parent shell is not mutated.

    :param spec: Application-specific bootstrap contract.
    :param env_file: Optional explicit dotenv file.
    :param env_file_overrides_shell: Whether ``env_file`` beats already
        exported variables inside this process.
    :param no_dotenv: Disable dotenv layer loading.
    :param storage_name: Optional named storage selector from the user registry.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    """
    original_env = dict(os.environ)
    log = logger or LOG
    registry = load_storage_registry(spec.registry_path())
    explicit_values = _read_explicit_env_file(env_file)
    selected_storage, used_default_storage = _select_storage(
        spec=spec,
        registry=registry,
        storage_name=storage_name,
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_shell=env_file_overrides_shell,
    )
    if (
        selected_storage is not None
        and used_default_storage
        and len(registry.storages) > 1
    ):
        log.info(
            f"Using default {spec.display_name} storage "
            f"{selected_storage.name!r} at {selected_storage.root} from "
            f"{registry.path}. Pass --storage to select another storage."
        )

    if no_dotenv:
        active_storage_root = (
            selected_storage.root
            if selected_storage is not None
            else _storage_root_from_values(
                original_env=original_env,
                explicit_values=explicit_values,
                env_file_overrides_shell=env_file_overrides_shell,
                storage_root_env_key=spec.storage_root_env_key,
            )
        )
        if selected_storage is not None:
            os.environ[spec.storage_root_env_key] = str(selected_storage.root)
        return EnvBootstrapResult(
            shared_env=None,
            local_env=None,
            env_file=env_file,
            registry_path=registry.path,
            storage_name=selected_storage.name if selected_storage else None,
            storage_root=active_storage_root,
            used_default_storage=used_default_storage,
            storage_count=len(registry.storages),
        )

    active_storage_root = (
        selected_storage.root
        if selected_storage is not None
        else _storage_root_from_values(
            original_env=original_env,
            explicit_values=explicit_values,
            env_file_overrides_shell=env_file_overrides_shell,
            storage_root_env_key=spec.storage_root_env_key,
        )
    )
    local_env = (
        None
        if active_storage_root is None
        else Path(active_storage_root) / spec.local_env_filename
    )

    with as_file(_shared_env_resource(spec)) as shared_env:
        if not shared_env.is_file():
            raise FileNotFoundError(
                f"Did not find packaged .env.shared at {shared_env}."
            )
        merged = _merged_env_values(
            shared_values=_read_dotenv_file(shared_env),
            local_values=_read_dotenv_file(local_env),
            explicit_values=explicit_values,
            original_env=original_env,
            env_file_overrides_shell=env_file_overrides_shell,
        )
        os.environ.update(merged)
        if selected_storage is not None:
            os.environ[spec.storage_root_env_key] = str(selected_storage.root)

        return EnvBootstrapResult(
            shared_env=shared_env,
            local_env=local_env,
            env_file=env_file,
            registry_path=registry.path,
            storage_name=(
                selected_storage.name if selected_storage is not None else None
            ),
            storage_root=(
                selected_storage.root
                if selected_storage is not None
                else active_storage_root
            ),
            used_default_storage=used_default_storage,
            storage_count=len(registry.storages),
        )


def _shared_env_resource(spec: EnvBootstrapSpec) -> Traversable:
    """Return the packaged shared dotenv resource."""
    return files(spec.config_package).joinpath(spec.shared_env_filename)


def _read_explicit_env_file(env_file: Path | None) -> dict[str, str]:
    """Read the optional explicit dotenv file."""
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
    env_file_overrides_shell: bool,
) -> dict[str, str]:
    """Merge env layers using the selected CLI precedence policy."""
    if env_file_overrides_shell:
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


def _select_storage(
    *,
    spec: EnvBootstrapSpec,
    registry: StorageRegistry,
    storage_name: str | None,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_shell: bool,
) -> tuple[StorageRecord | None, bool]:
    """Return the registry-selected storage, if registry selection applies."""
    if storage_name is not None:
        return registry.selected(storage_name), False
    if _storage_root_value(
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_shell=env_file_overrides_shell,
        storage_root_env_key=spec.storage_root_env_key,
    ):
        return None, False
    default_storage = registry.default()
    if default_storage is None:
        return None, False
    return default_storage, True


def _storage_root_from_values(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_shell: bool,
    storage_root_env_key: str,
) -> Path | None:
    """Return active storage root from higher-precedence env values."""
    root = _storage_root_value(
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_shell=env_file_overrides_shell,
        storage_root_env_key=storage_root_env_key,
    )
    if not root:
        return None
    return Path(root).expanduser()


def _storage_root_value(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_shell: bool,
    storage_root_env_key: str,
) -> str | None:
    """Return the storage-root value implied by shell/explicit env layers."""
    if env_file_overrides_shell:
        return explicit_values.get(storage_root_env_key) or original_env.get(
            storage_root_env_key
        )
    return original_env.get(storage_root_env_key) or explicit_values.get(
        storage_root_env_key
    )
