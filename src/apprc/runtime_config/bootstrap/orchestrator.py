"""Load dotenv layers into one CLI process at application startup.

AppRC imports are side-effect free: importing a config dataclass does not read
``.env`` files or modify the process environment. Application entrypoints call
``bootstrap_env`` once, before runtime config objects are created, to merge the
packaged shared defaults, app-global dotenv values, optional storage-local
dotenv values, explicit ``--env-file`` values, and the values already present
in ``os.environ``.

The helper mutates only the current Python process because runtime config
binding and some application dependencies intentionally read from
``os.environ``. It may create missing AppRC-managed config-home files, but it
does not prompt, write user values, create storage roots, or change the parent
shell. AppRC TOML path lookup is delegated to
:mod:`apprc.runtime_config.app_spec`, active storage selection is delegated
to :mod:`apprc.runtime_config.storage.selector`, and storage-local editing is
delegated to :mod:`apprc.runtime_config.storage.local_env`.
"""

from __future__ import annotations

# == Standard Library ========================
import os
from collections.abc import Sequence
from pathlib import Path

# == Internal ================================
from apprc.runtime_config.bootstrap.dotenv_layers import (
    merged_env_values,
    read_dotenv_file,
    read_explicit_env_files,
    read_shared_env_values,
)
from apprc.runtime_config.bootstrap.process_env import (
    app_env_keys,
    merged_env_value_origins,
    original_env_value_origins,
    selection_env,
    write_bootstrap_environment,
)
from apprc.runtime_config.bootstrap.result import (
    BootstrapLogger,
    EnvBootstrapResult,
)
from apprc.runtime_config.app_spec import AppConfigSpec, StorageMode
from apprc.runtime_config.provenance import EnvValueOrigin
from apprc.runtime_config.provenance import register_env_value_origins
from apprc.runtime_config.storage.loading import (
    load_optional_runtime_storage_registry,
)
from apprc.runtime_config.storage.selector import (
    missing_storage_selector_error,
    resolve_storage_selector_value,
    select_storage_selector,
)
from apprc.logging import get_logger

LOG = get_logger(__name__)


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
    layers are packaged ``.env.shared``, app-global ``.env.global``, optional
    active storage-local ``.env.local``, and explicit ``env_files``. Later
    explicit files override earlier explicit files. The merged explicit values
    always override packaged, global, and storage-local dotenv layers. When
    dotenv layers are skipped, explicit files are still parsed so they can
    guide storage-root selection for storage-required apps, but their values
    are not merged into ``os.environ``.

    :param spec: Application-specific bootstrap contract.
    :param env_files: Optional invocation-local dotenv files that outrank
        packaged ``.env.shared``, app-global ``.env.global``, and active
        storage-local ``.env.local``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``.env.shared``, app-global
        ``.env.global``, storage-local ``.env.local``, and explicit dotenv
        values should be merged into this process. Storage selection still runs
        for storage-required apps when this is ``False``.
    :param storage: Optional ``--storage`` selector for storage-required apps.
        When AppRC TOML has registered storages, exact registered names resolve
        through it. Otherwise every non-empty selector is interpreted as a path.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    """
    emit = logger or LOG
    original_env = dict(os.environ)
    loaded_env_files, explicit_layers, explicit_values = (
        read_explicit_env_files(env_files)
    )
    selector_env = selection_env(
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    config_home = spec.ensure_config_home(proc_env=selector_env)
    shared_env_path, shared_values = read_shared_env_values(spec)
    global_values = read_dotenv_file(config_home.global_env)
    owned_env_keys = app_env_keys(spec)
    emit.info(
        "AppRC bootstrap starting for %s: explicit_env_files=%s "
        "load_dotenv_layers=%s env_file_overrides_os_environ=%s",
        spec.app_name,
        len(loaded_env_files),
        load_dotenv_layers,
        env_file_overrides_os_environ,
    )
    registry = load_optional_runtime_storage_registry(
        spec, proc_env=selector_env
    )
    selection = None
    active_storage_root: Path | None = None
    active_local_env: Path | None = None
    storage_env_key = spec.storage_env_key
    if spec.storage_mode == StorageMode.REQUIRED:
        storage_env_key = spec.require_storage_env_key()
        storage_selector = select_storage_selector(
            storage=storage,
            storage_env_key=storage_env_key,
            original_env=original_env,
            explicit_values=explicit_values,
            global_values=global_values,
            shared_values=shared_values,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        if storage_selector is None:
            raise missing_storage_selector_error(storage_env_key)
        selector_source, selector_value = storage_selector
        emit.info(
            "AppRC bootstrap selected storage selector: source=%s value=%s",
            selector_source,
            selector_value,
        )
        selection = resolve_storage_selector_value(
            registry=registry,
            raw_value=selector_value,
            storage_env_key=storage_env_key,
            source=selector_source,
        )
        active_storage_root = selection.root
        active_local_env = active_storage_root / spec.local_env_filename
        emit.info(
            "AppRC bootstrap resolved storage: name=%s root=%s "
            "registry_path=%s registry_storage_count=%s",
            selection.storage_name,
            active_storage_root,
            registry.path if registry is not None else None,
            len(registry.storages) if registry is not None else 0,
        )
    else:
        emit.info(
            "AppRC bootstrap using storage-free config home: %s",
            config_home.root,
        )

    env_origins = original_env_value_origins(
        app_env_keys=owned_env_keys,
        original_env=original_env,
    )
    loaded_local_env: Path | None = None
    loaded_global_env: Path | None = None
    if load_dotenv_layers:
        loaded_local_env = active_local_env
        loaded_global_env = config_home.global_env
        if shared_env_path is None:
            raise FileNotFoundError(
                f"Did not find packaged .env.shared for {spec.config_package}."
            )
        local_values = read_dotenv_file(active_local_env)
        merged = merged_env_values(
            shared_values=shared_values,
            global_values=global_values,
            local_values=local_values,
            explicit_values=explicit_values,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        env_origins = merged_env_value_origins(
            app_env_keys=owned_env_keys,
            shared_env_path=shared_env_path,
            shared_values=shared_values,
            global_env_path=config_home.global_env,
            global_values=global_values,
            local_env_path=active_local_env,
            local_values=local_values,
            explicit_layers=explicit_layers,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        write_bootstrap_environment(
            merged,
            storage_env_key=storage_env_key,
            storage_root=active_storage_root,
        )
        emit.info(
            "AppRC bootstrap loaded dotenv layers: shared_env=%s "
            "global_env=%s local_env=%s explicit_env_files=%s",
            shared_env_path,
            config_home.global_env,
            active_local_env,
            loaded_env_files,
        )
        emit.info(
            "AppRC bootstrap wrote process env entries: total=%s "
            "app_owned=%s storage_selector_key=%s",
            len(merged),
            len(set(merged) & owned_env_keys),
            storage_env_key,
        )
    else:
        write_bootstrap_environment(
            {},
            storage_env_key=storage_env_key,
            storage_root=active_storage_root,
        )
        emit.info(
            "AppRC bootstrap skipped dotenv layer merge and wrote only "
            "storage selector key: %s",
            storage_env_key,
        )
    if storage_env_key is not None and active_storage_root is not None:
        env_origins[storage_env_key] = EnvValueOrigin(
            env_key=storage_env_key,
            origin="shell_bootstrap_selector",
            value=str(active_storage_root),
        )
    register_env_value_origins(env_origins, clear_keys=owned_env_keys)

    return EnvBootstrapResult(
        shared_env=shared_env_path if load_dotenv_layers else None,
        local_env=loaded_local_env,
        env_files=loaded_env_files,
        apprc_toml_path=config_home.apprc_toml,
        storage_selector_source=(
            selection.source if selection is not None else None
        ),
        storage_selector_value=(
            selection.raw_value if selection is not None else None
        ),
        storage_name=selection.storage_name if selection is not None else None,
        storage_root=active_storage_root,
        storage_count=len(registry.storages) if registry is not None else 0,
        config_home=config_home.root,
        global_env=loaded_global_env,
    )
