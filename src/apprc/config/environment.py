"""Load dotenv layers into one CLI process at application startup.

AppRC imports are side-effect free: importing a config dataclass does not read
``.env`` files or modify the process environment. Application entrypoints call
``bootstrap_env`` once, before runtime config objects are created, to merge the
packaged shared defaults, the selected storage-local dotenv file, optional
explicit ``--env-file`` values, and the values already present in
``os.environ``.

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
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Mapping, Protocol

# == 3rd Party ===============================
from dotenv import dotenv_values

# == Internal ================================
from apprc.config.app_spec import AppConfigSpec
from apprc.config.provenance import (
    EnvValueOrigin,
    ShellProvenanceOrigin,
    register_env_value_origins,
)
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
    :param env_files: Explicit dotenv files passed through the CLI or Python API.
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
    env_files: tuple[Path, ...]
    apprc_toml_path: Path | None
    storage_selector_source: str | None
    storage_selector_value: str | None
    storage_name: str | None
    storage_root: Path | None
    storage_count: int


@dataclass(frozen=True, slots=True)
class _ExplicitEnvLayer:
    """Parsed explicit env file plus its path for provenance tracking.

    :param path: Resolved explicit env file path.
    :param values: Parsed dotenv values from ``path``.
    """

    path: Path
    values: dict[str, str]


def bootstrap_env(
    *,
    spec: AppConfigSpec,
    env_files: Sequence[Path] = (),
    env_file_overrides_os_environ: bool = False,
    load_dotenv_layers: bool = True,
    storage: str | None = None,
    logger: BootstrapLogger | None = None,
) -> EnvBootstrapResult:
    """Populate ``os.environ`` for one application CLI process.

    Imports stay side-effect free; entrypoints call this helper before building
    runtime config objects that read OS environment variables from the current
    Python process via ``os.environ``. The parent shell is not mutated. Dotenv
    layers are the packaged ``.env.shared``, the active storage-local
    ``.env.local``, and the optional explicit ``env_files``. Later explicit
    files override earlier explicit files. The merged explicit values always
    override the packaged and storage-local dotenv layers. When dotenv layers
    are skipped, explicit files are still parsed so they can guide storage-root
    selection, but their values are not merged into ``os.environ``.

    :param spec: Application-specific bootstrap contract.
    :param env_files: Optional invocation-local dotenv files that outrank the
        packaged ``.env.shared`` and active storage-local ``.env.local``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
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
    loaded_env_files, explicit_layers, explicit_values = (
        _read_explicit_env_files(env_files)
    )
    shared_env_path, shared_values = read_shared_env_values(spec)
    app_env_keys = _app_env_keys(spec)
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
    registry = load_optional_runtime_storage_registry(
        spec,
        proc_env=_selection_env(
            original_env=original_env,
            explicit_values=explicit_values,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        ),
    )
    selector_source, selector_value = storage_selector
    selection = resolve_storage_selector_value(
        registry=registry,
        raw_value=selector_value,
        storage_env_key=spec.storage_env_key,
        source=selector_source,
    )

    active_storage_root = selection.root
    active_local_env = active_storage_root / spec.local_env_filename

    env_origins = _original_env_value_origins(
        app_env_keys=app_env_keys,
        original_env=original_env,
    )
    loaded_local_env: Path | None = None
    if load_dotenv_layers:
        loaded_local_env = active_local_env
        if shared_env_path is None:
            raise FileNotFoundError(
                f"Did not find packaged .env.shared for {spec.config_package}."
            )
        local_values = _read_dotenv_file(active_local_env)
        merged = _merged_env_values(
            shared_values=shared_values,
            local_values=local_values,
            explicit_values=explicit_values,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        env_origins = _merged_env_value_origins(
            app_env_keys=app_env_keys,
            shared_env_path=shared_env_path,
            shared_values=shared_values,
            local_env_path=active_local_env,
            local_values=local_values,
            explicit_layers=explicit_layers,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        os.environ.update(merged)
    os.environ[spec.storage_env_key] = str(active_storage_root)
    env_origins[spec.storage_env_key] = EnvValueOrigin(
        env_key=spec.storage_env_key,
        origin="shell_bootstrap_selector",
        value=str(active_storage_root),
    )
    register_env_value_origins(env_origins, clear_keys=app_env_keys)

    return EnvBootstrapResult(
        shared_env=shared_env_path if load_dotenv_layers else None,
        local_env=loaded_local_env,
        env_files=loaded_env_files,
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


def _read_explicit_env_files(
    env_files: Sequence[Path],
) -> tuple[tuple[Path, ...], tuple[_ExplicitEnvLayer, ...], dict[str, str]]:
    """Read ordered explicit dotenv files.

    Explicit values may guide storage selection even when dotenv layers
    are not merged into ``os.environ``. Later files override earlier files.
    """
    loaded_paths: list[Path] = []
    layers: list[_ExplicitEnvLayer] = []
    merged_values: dict[str, str] = {}
    for env_file in env_files:
        resolved = Path(env_file).expanduser()
        if not resolved.is_file():
            raise FileNotFoundError(
                f"Explicit env file does not exist: {resolved}"
            )
        loaded_paths.append(resolved)
        values = _read_dotenv_file(resolved)
        layers.append(_ExplicitEnvLayer(path=resolved, values=values))
        merged_values.update(values)
    return tuple(loaded_paths), tuple(layers), merged_values


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


def _app_env_keys(spec: AppConfigSpec) -> set[str]:
    """Return env keys owned by one application contract.

    :param spec: Application-specific bootstrap contract.
    :return: Full env keys that AppRC should track for this app.
    """
    keys = {spec.apprc_toml_env_key, spec.storage_env_key}
    for owner in spec.owners:
        keys.update(
            owner.env_key(owner_field.name) for owner_field in owner.fields
        )
    return keys


def _original_env_value_origins(
    *,
    app_env_keys: set[str],
    original_env: Mapping[str, str],
) -> dict[str, EnvValueOrigin]:
    """Return shell-export origins from the pre-bootstrap process env.

    :param app_env_keys: App-owned env keys eligible for provenance tracking.
    :param original_env: Process environment captured before bootstrap writes.
    :return: Existing env values keyed by env key.
    """
    return {
        key: EnvValueOrigin(
            env_key=key,
            origin="shell_export_variable",
            value=original_env[key],
        )
        for key in app_env_keys
        if key in original_env
    }


def _merged_env_value_origins(
    *,
    app_env_keys: set[str],
    shared_env_path: Path,
    shared_values: Mapping[str, str],
    local_env_path: Path,
    local_values: Mapping[str, str],
    explicit_layers: tuple[_ExplicitEnvLayer, ...],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, EnvValueOrigin]:
    """Return winning env-value origins using runtime bootstrap precedence.

    :param app_env_keys: App-owned env keys eligible for provenance tracking.
    :param shared_env_path: Packaged shared dotenv path.
    :param shared_values: Parsed packaged shared dotenv values.
    :param local_env_path: Active storage-local dotenv path.
    :param local_values: Parsed storage-local dotenv values.
    :param explicit_layers: Parsed explicit env files in command/API order.
    :param original_env: Process environment captured before bootstrap writes.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process.
    :return: Winning env-value origins keyed by env key.
    """
    origins: dict[str, EnvValueOrigin] = {}

    def apply_values(
        values: Mapping[str, str],
        origin: ShellProvenanceOrigin,
        *,
        path: Path | None = None,
    ) -> None:
        for key, value in values.items():
            if key not in app_env_keys:
                continue
            origins[key] = EnvValueOrigin(
                env_key=key,
                origin=origin,
                value=value,
                path=path,
            )

    apply_values(shared_values, "shell_dotenv_shared", path=shared_env_path)
    apply_values(local_values, "shell_dotenv_local", path=local_env_path)
    if env_file_overrides_os_environ:
        apply_values(original_env, "shell_export_variable")
        for layer in explicit_layers:
            apply_values(
                layer.values,
                "shell_dotenv_explicit",
                path=layer.path,
            )
        return origins

    for layer in explicit_layers:
        apply_values(
            layer.values,
            "shell_dotenv_explicit",
            path=layer.path,
        )
    apply_values(original_env, "shell_export_variable")
    return origins


def _selection_env(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Return env values used before dotenv layers mutate ``os.environ``."""
    if env_file_overrides_os_environ:
        return {**original_env, **explicit_values}
    return {**explicit_values, **original_env}
