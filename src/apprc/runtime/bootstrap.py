"""Load dotenv layers into one CLI process at application startup.

AppRC imports are side-effect free: importing a config dataclass does not read
``.env`` files or modify the process environment. Application entrypoints call
``bootstrap_env`` once, before runtime config objects are created, to merge
packaged defaults, per-user dotenv values, optional storage
dotenv values, explicit ``--env-file`` values, and the values already present
in ``os.environ``.

The helper mutates only the current Python process because runtime config
binding and some application dependencies intentionally read from
``os.environ``. It resolves AppRC-managed paths but never creates files,
storage roots, or parent shell changes. AppRC TOML path lookup is
delegated to
:mod:`apprc.definition.app_config.spec`, active storage selection is delegated
to :mod:`apprc.user_files.storage_roots.selector`, and storage dotenv editing is
delegated to :mod:`apprc.user_files.env_files.files`.
"""

from __future__ import annotations

# == Standard Library ========================
import logging
import os
from collections.abc import Sequence
from pathlib import Path

# == Internal ================================
from apprc.runtime._dotenv_layers import (
    merged_env_values,
    read_dotenv_file,
    read_explicit_env_files,
    read_defaults_dotenv_values,
)
from apprc.runtime._process_env import (
    user_dotenv_keys,
    merged_env_value_origins,
    original_env_value_origins,
    selection_env,
    write_bootstrap_environment,
)
from apprc.runtime.result import (
    BootstrapLogger,
    EnvBootstrapResult,
)
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.runtime.provenance import EnvValueOrigin
from apprc.runtime.provenance import register_env_value_origins
from apprc.user_files.storage_roots._loading import (
    load_optional_runtime_storage_registry,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelectorError,
    missing_storage_selector_error,
    resolve_active_storage_selection,
)

LOG = logging.getLogger(__name__)


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
    layers are packaged ``apprc.defaults.env``, per-user
    ``apprc.user.env``, optional active-storage ``apprc.storage.env``, and
    explicit ``env_files``. Later
    explicit files override earlier explicit files. The merged explicit values
    always override defaults, app, and storage dotenv layers. When
    dotenv layers are skipped, explicit files are still parsed so they can
    guide storage-root selection for storage apps, but their values
    are not merged into ``os.environ``.

    :param spec: Application-specific bootstrap contract.
    :param env_files: Optional invocation-local dotenv files that outrank
        packaged ``apprc.defaults.env``, user ``apprc.user.env``, and active
        storage ``apprc.storage.env``.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process. The parent shell
        is never mutated.
    :param load_dotenv_layers: Whether packaged ``apprc.defaults.env``, app
        ``apprc.user.env``, storage ``apprc.storage.env``, and explicit dotenv
        values should be merged into this process. Storage selection still
        runs for storage apps when this is ``False``.
    :param storage: Optional registered storage name from ``--storage``.
    :param logger: Optional application logger for bootstrap status messages.
    :return: Bootstrap summary for diagnostics and tests.
    """
    emit = logger or LOG
    if storage is not None and not spec.uses_storage():
        raise StorageSelectorError(
            f"{spec.display_name} does not declare storage support.",
            param_hint="--storage",
        )
    original_env = dict(os.environ)
    loaded_env_files, explicit_layers, explicit_values = (
        read_explicit_env_files(env_files)
    )
    selector_env = selection_env(
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
    )
    paths = spec.paths(proc_env=selector_env)
    defaults_dotenv_path, defaults_values = read_defaults_dotenv_values(spec)
    user_dotenv_path = paths.user_dotenv
    user_dotenv_values: dict[str, str] = {}
    try:
        if user_dotenv_path is not None and user_dotenv_path.is_file():
            user_dotenv_values = read_dotenv_file(user_dotenv_path)
    except OSError as exc:
        raise AppRCDirectoryError(
            f"AppRC-managed file could not be read: {user_dotenv_path}: {exc}"
        ) from exc
    owned_env_keys = user_dotenv_keys(spec)
    emit.info(
        "AppRC bootstrap starting for %s: explicit_env_files=%s "
        "load_dotenv_layers=%s env_file_overrides_os_environ=%s",
        spec.app_id,
        len(loaded_env_files),
        load_dotenv_layers,
        env_file_overrides_os_environ,
    )
    registry = None
    selection = None
    active_storage_root: Path | None = None
    active_storage_dotenv: Path | None = None
    storage_selector_env_key = spec.storage_selector_env_key
    if spec.uses_storage():
        storage_selector_env_key = spec.require_storage_selector_env_key()
        registry = load_optional_runtime_storage_registry(
            spec,
            proc_env=selector_env,
        )
        if registry is None:
            raise missing_storage_selector_error(storage_selector_env_key)
        selection = resolve_active_storage_selection(
            registry=registry,
            storage=storage,
            storage_selector_env_key=storage_selector_env_key,
            original_env=original_env,
            explicit_values=explicit_values,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        if selection is None:
            raise missing_storage_selector_error(storage_selector_env_key)
        emit.info(
            "AppRC bootstrap selected storage selector: source=%s value=%s",
            selection.source,
            selection.raw_value,
        )
        active_storage_root = selection.root
        _validate_runtime_storage_root(
            spec=spec,
            storage_root=active_storage_root,
            param_hint=selection.source,
        )
        active_storage_dotenv = spec.storage_dotenv_path(active_storage_root)
        emit.info(
            "AppRC bootstrap resolved storage: name=%s root=%s "
            "registry_path=%s registry_storage_count=%s",
            selection.storage_name,
            active_storage_root,
            registry.path,
            len(registry.storages),
        )
    else:
        emit.info("AppRC bootstrap using user dotenv: %s", user_dotenv_path)

    env_origins = original_env_value_origins(
        user_dotenv_keys=owned_env_keys,
        original_env=original_env,
    )
    loaded_storage_dotenv: Path | None = None
    loaded_user_dotenv: Path | None = None
    if load_dotenv_layers:
        loaded_storage_dotenv = active_storage_dotenv
        loaded_user_dotenv = user_dotenv_path
        if defaults_dotenv_path is None:
            raise FileNotFoundError(
                "Did not find packaged defaults file "
                f"{spec.defaults_dotenv_filename} for {spec.config_package}."
            )
        try:
            storage_values = read_dotenv_file(active_storage_dotenv)
        except OSError as exc:
            raise StorageSelectorError(
                "Storage env file could not be read: "
                f"{active_storage_dotenv}: {exc}",
                param_hint="--storage",
            ) from exc
        merged = merged_env_values(
            defaults_values=defaults_values,
            user_dotenv_values=user_dotenv_values,
            storage_values=storage_values,
            explicit_values=explicit_values,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        env_origins = merged_env_value_origins(
            user_dotenv_keys=owned_env_keys,
            defaults_dotenv_path=defaults_dotenv_path,
            defaults_values=defaults_values,
            user_dotenv_path=user_dotenv_path,
            user_dotenv_values=user_dotenv_values,
            storage_dotenv_path=active_storage_dotenv,
            storage_values=storage_values,
            explicit_layers=explicit_layers,
            original_env=original_env,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
        )
        write_bootstrap_environment(
            merged,
            storage_selector_env_key=storage_selector_env_key,
            storage_root=active_storage_root,
        )
        emit.info(
            "AppRC bootstrap loaded dotenv layers: defaults_dotenv=%s "
            "user_dotenv=%s storage_dotenv=%s explicit_env_files=%s",
            defaults_dotenv_path,
            user_dotenv_path,
            active_storage_dotenv,
            loaded_env_files,
        )
        emit.info(
            "AppRC bootstrap wrote process env entries: total=%s "
            "app_owned=%s storage_selector_key=%s",
            len(merged),
            len(set(merged) & owned_env_keys),
            storage_selector_env_key,
        )
    else:
        write_bootstrap_environment(
            {},
            storage_selector_env_key=storage_selector_env_key,
            storage_root=active_storage_root,
        )
        emit.info(
            "AppRC bootstrap skipped dotenv layer merge and wrote only "
            "storage selector key: %s",
            storage_selector_env_key,
        )
    if storage_selector_env_key is not None and active_storage_root is not None:
        env_origins[storage_selector_env_key] = EnvValueOrigin(
            env_key=storage_selector_env_key,
            origin="shell_bootstrap_selector",
            value=str(active_storage_root),
        )
    register_env_value_origins(env_origins, clear_keys=owned_env_keys)

    return EnvBootstrapResult(
        defaults_dotenv=defaults_dotenv_path if load_dotenv_layers else None,
        storage_dotenv=loaded_storage_dotenv,
        env_files=loaded_env_files,
        apprc_toml=paths.apprc_toml,
        storage_selector_source=(
            selection.source if selection is not None else None
        ),
        storage_selector_value=(
            selection.raw_value if selection is not None else None
        ),
        storage_name=selection.storage_name if selection is not None else None,
        storage_root=active_storage_root,
        storage_count=len(registry.storages) if registry is not None else 0,
        apprc_dir=paths.root,
        user_dotenv=loaded_user_dotenv,
    )


def _validate_runtime_storage_root(
    *,
    spec: AppConfigSpec,
    storage_root: Path,
    param_hint: str,
) -> None:
    """Reject a selected root that AppRC setup has not prepared.

    Runtime bootstrap reads configuration but never creates directories. The
    generated setup command owns that write so applications get one consistent
    recovery path before they construct storage-backed runtime objects.

    :param spec: Application contract used to build recovery instructions.
    :param storage_root: Resolved path selected for this process.
    :param param_hint: Selector source shown by CLI error rendering.
    :return: None.
    :raises StorageSelectorError: If the path is missing or is not a directory.
    """
    setup_command = (
        f"{spec.config_command_name()} config setup --yes "
        "--storage-root STORAGE_ROOT"
    )
    if not storage_root.exists():
        raise StorageSelectorError(
            f"Selected {spec.display_name} storage root does not exist: "
            f"{storage_root}. Run `{setup_command}` before runtime use.",
            param_hint=param_hint,
        )
    if not storage_root.is_dir():
        raise StorageSelectorError(
            f"Selected {spec.display_name} storage root is not a directory: "
            f"{storage_root}. Repoint or move its registered storage, then run "
            f"`{setup_command}`.",
            param_hint=param_hint,
        )
