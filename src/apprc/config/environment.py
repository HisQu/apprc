"""Load dotenv layers into one CLI process at application startup.

AppRC imports are side-effect free: importing a config dataclass does not read
``.env`` files or modify the process environment. Application entrypoints call
``bootstrap_env`` once, before runtime config objects are created, to merge the
packaged shared defaults, the selected storage-local dotenv file, an optional
explicit ``--env-file``, and the values already present in ``os.environ``.

The helper mutates only the current Python process because runtime config
binding and some application dependencies intentionally read from
``os.environ``. It never writes dotenv files and never changes the parent
shell. AppRC TOML path lookup is delegated to
:mod:`apprc.config.app_spec`, active storage selection is delegated to
:mod:`apprc.config.storage.selector`, and storage-local editing is delegated to
:mod:`apprc.config.local_env`.
"""

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
from apprc.config.app_spec import AppConfigSpec
from apprc.config.storage_registry_loading import (
    load_optional_runtime_storage_registry,
)
from apprc.config.storage.selector import (
    missing_storage_selector_error,
    resolve_storage_selector_value,
    select_storage_selector,
)
from apprc.logging import get_logger

LOG = get_logger(__name__)


class BootstrapLogger(Protocol):
    """Logger interface needed for bootstrap status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""


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
    :param apprc_toml_path: Env-selected AppRC TOML path, or ``None`` when
        single-storage path mode is active.
    :param storage_selector_source: Source that selected the active storage,
        such as ``--storage`` or the app-specific storage env key.
    :param storage_selector_value: Selector value before it was resolved to a
        concrete storage root.
    :param storage_name: Named storage selected for this bootstrap when the
        selector matched an AppRC TOML entry.
    :param storage_root: Active storage root, when known.
    :param storage_count: Number of loaded named storages.
    """

    shared_env: Path | None
    local_env: Path | None
    env_file: Path | None
    apprc_toml_path: Path | None
    storage_selector_source: str | None
    storage_selector_value: str | None
    storage_name: str | None
    storage_root: Path | None
    storage_count: int


def bootstrap_env(
    *,
    spec: AppConfigSpec,
    env_file: Path | None = None,
    env_file_overrides_os_environ: bool = False,
    load_dotenv_layers: bool = True,
    storage: str | None = None,
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
        merged into this process. Multi-storage and storage selection still run
        when this is ``False``.
    :param storage: Optional ``--storage`` selector. When AppRC TOML is loaded,
        exact registered names resolve through it. Otherwise every non-empty
        selector is interpreted as a path.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    """
    original_env = dict(os.environ)
    explicit_values = _read_explicit_env_file(env_file)
    shared_env_path, shared_values = read_shared_env_values(spec)
    storage_selector = select_storage_selector(
        storage=storage,
        storage_env_key=spec.storage_env_key,
        original_env=original_env,
        explicit_values=explicit_values,
        shared_values=shared_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    if storage_selector is None:
        raise missing_storage_selector_error(spec.storage_env_key)
    registry = load_optional_runtime_storage_registry(spec)
    selector_source, selector_value = storage_selector
    selection = resolve_storage_selector_value(
        registry=registry,
        raw_value=selector_value,
        storage_env_key=spec.storage_env_key,
        source=selector_source,
    )

    active_storage_root = selection.root
    active_local_env = active_storage_root / spec.local_env_filename

    loaded_local_env: Path | None = None
    if load_dotenv_layers:
        loaded_local_env = active_local_env
        if shared_env_path is None:
            raise FileNotFoundError(
                f"Did not find packaged .env.shared for {spec.config_package}."
            )
        merged = _merged_env_values(
            shared_values=shared_values,
            local_values=_read_dotenv_file(active_local_env),
            explicit_values=explicit_values,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        os.environ.update(merged)
    os.environ[spec.storage_env_key] = str(active_storage_root)

    return EnvBootstrapResult(
        shared_env=shared_env_path if load_dotenv_layers else None,
        local_env=loaded_local_env,
        env_file=env_file,
        apprc_toml_path=registry.path if registry is not None else None,
        storage_selector_source=selection.source,
        storage_selector_value=selection.raw_value,
        storage_name=selection.storage_name,
        storage_root=active_storage_root,
        storage_count=len(registry.storages) if registry is not None else 0,
    )


def _shared_env_resource(spec: AppConfigSpec) -> Traversable:
    """Return the packaged shared dotenv resource."""
    return files(spec.config_package).joinpath(spec.shared_env_filename)


def read_shared_env_values(
    spec: AppConfigSpec,
) -> tuple[Path | None, dict[str, str]]:
    """Read packaged shared dotenv values when the resource exists.

    Missing shared resources are tolerated here so storage selection can use a
    packaged default when present without making shared defaults mandatory for
    every AppRC integration. ``bootstrap_env`` raises later when dotenv layers
    are enabled and the shared resource is absent.

    :param spec: Application-specific bootstrap contract.
    :return: Shared dotenv path and parsed values, or ``(None, {})``.
    """
    with as_file(_shared_env_resource(spec)) as shared_env:
        if not shared_env.is_file():
            return None, {}
        return shared_env, _read_dotenv_file(shared_env)


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
