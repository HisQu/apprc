"""High-level facade for one application's AppRC integration.

``AppConfigKit`` is the convenient entrypoint for applications. It stores one
``AppConfigSpec`` and delegates to the focused lower-level modules for storage
registries, dotenv bootstrapping, local value editing, diagnostics, Textual
editing, and Typer command generation.

Use this module when wiring a host application. Use the sibling modules
directly when testing one layer in isolation or when building a custom workflow
that should not pull in CLI/TUI dependencies.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

# == Internal ================================
from apprc.config.app_spec import AppConfigSpec
from apprc.config.environment import (
    BootstrapLogger,
    EnvBootstrapResult,
    bootstrap_env,
)
from apprc.config.install_state import ConfigInstallState
from apprc.config.local_env import (
    LocalEnvUpdate,
    clear_local_env_value,
    local_env_path,
    set_local_env_value,
)
from apprc.config.schema import ConfigOwner
from apprc.config.apprc_toml import (
    ApprcTomlEnvError,
    default_apprc_toml_filename,
)
from apprc.config.storage.registry import (
    StorageRegistry,
    load_storage_registry,
    prune_missing_archived_storages,
    record_archived_storage,
    register_storage,
    remove_archived_storage,
    suggested_storage_name,
    suggested_storage_root,
    unregister_storage,
)

StateT = TypeVar("StateT")

if TYPE_CHECKING:
    import typer

    from apprc.config.diagnostics import ConfigDoctorPayload
    from apprc.config.tui import ConfigEditorApp
    from apprc.config.tui.setup import ConfigSetupApp


class AppConfigKit:
    """Convenience facade around one application's config contract.

    The kit is intentionally small: it stores the app spec and delegates each
    workflow to the lower-level modules. Applications can stay at this level
    for normal CLI setup while tests and advanced integrations can still import
    the individual storage, dotenv, schema, or TUI modules directly.
    """

    @overload
    def __init__(self, spec: AppConfigSpec) -> None: ...

    @overload
    def __init__(
        self,
        spec: None = None,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        owners: tuple[ConfigOwner, ...],
        storage_env_key: str,
        command_name: str | None = None,
        apprc_toml_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        local_env_filename: str = ".env.local",
    ) -> None: ...

    def __init__(
        self,
        spec: AppConfigSpec | None = None,
        *,
        app_name: str | None = None,
        display_name: str | None = None,
        config_package: str | None = None,
        owners: tuple[ConfigOwner, ...] | None = None,
        storage_env_key: str | None = None,
        command_name: str | None = None,
        apprc_toml_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        local_env_filename: str = ".env.local",
    ) -> None:
        """Store the application spec or build one from keyword arguments."""
        if spec is not None:
            self.spec = spec
            return
        if (
            app_name is None
            or display_name is None
            or config_package is None
            or owners is None
            or storage_env_key is None
        ):
            raise TypeError(
                "AppConfigKit requires either an AppConfigSpec or all "
                "application spec keyword arguments."
            )
        self.spec = AppConfigSpec(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            owners=owners,
            storage_env_key=storage_env_key,
            command_name=command_name,
            apprc_toml_filename=(
                apprc_toml_filename
                if apprc_toml_filename is not None
                else default_apprc_toml_filename(app_name)
            ),
            shared_env_filename=shared_env_filename,
            local_env_filename=local_env_filename,
        )

    def apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the active AppRC TOML path.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path for this application.
        :raises ApprcTomlEnvError: If the AppRC TOML env var is missing.
        """
        return self.spec.apprc_toml_path(proc_env)

    def optional_apprc_toml_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path | None:
        """Return the active AppRC TOML path when the env var is set.

        :param proc_env: Optional environment mapping for tests.
        :return: Env-selected AppRC TOML path, or ``None``.
        """
        return self.spec.optional_apprc_toml_path(proc_env)

    def apprc_toml_env_key(self) -> str:
        """Return the env var that selects the AppRC TOML path."""
        return self.spec.apprc_toml_env_key()

    def bootstrap(
        self,
        *,
        env_file: Path | None,
        env_file_overrides_os_environ: bool,
        load_dotenv_layers: bool,
        storage: str | None,
        logger: BootstrapLogger | None = None,
    ) -> EnvBootstrapResult:
        """Populate ``os.environ`` for this application.

        :param env_file: Optional invocation-local dotenv file that outranks
            the packaged ``.env.shared`` and active storage-local
            ``.env.local``.
        :param env_file_overrides_os_environ: Whether explicit dotenv values beat
            existing values in ``os.environ`` inside this process. The parent
            shell is never mutated.
        :param load_dotenv_layers: Whether packaged ``.env.shared``, active
            storage-local ``.env.local``, and explicit ``env_file`` values
            should be merged into this process. Storage selection still runs
            when this is ``False``, and explicit ``env_file`` values may still
            provide the selector used for selection.
        :param storage: Optional ``--storage`` selector. With an AppRC TOML it
            may be a registered storage name or path. Without an AppRC TOML it
            is always interpreted as a path.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        return bootstrap_env(
            spec=self.spec.env_bootstrap_spec(),
            env_file=env_file,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )

    def load_registry(self, path: Path | None = None) -> StorageRegistry:
        """Read this application's storage registry.

        :param path: Optional explicit AppRC TOML path for tests.
        :return: Parsed storage registry, or an empty registry.
        """
        return load_storage_registry(
            self.apprc_toml_path() if path is None else path
        )

    def load_existing_registry(
        self,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Read an already-installed multi-storage registry.

        Creation flows use :meth:`load_registry` because a missing TOML can be
        created there. Runtime registry features use this stricter helper so a
        configured but missing ``<APP>_APPRC_TOML`` is reported as an unhealthy
        multi-storage setup.

        :param path: Optional explicit AppRC TOML path for tests.
        :return: Parsed storage registry.
        :raises ApprcTomlEnvError: If the TOML env var is missing or points at
            a missing file.
        :raises ValueError: If the registry cannot be parsed.
        """
        registry_path = self.apprc_toml_path() if path is None else path
        resolved_path = Path(registry_path).expanduser().resolve()
        if not resolved_path.is_file():
            env_key = self.apprc_toml_env_key()
            path_context = (
                f"{env_key} points to a missing AppRC TOML"
                if path is None
                else "AppRC TOML does not exist"
            )
            raise ApprcTomlEnvError(
                f"{path_context}: {resolved_path}. Remove {env_key} for "
                "single-storage mode, or create the registry with "
                f"{self.spec.config_command_name()} config setup --yes "
                "--multi-storage."
            )
        return load_storage_registry(resolved_path)

    def register_storage(
        self,
        *,
        name: str,
        root: Path,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Add or update one storage entry for this application."""
        return register_storage(
            name=name,
            root=root,
            path=self.apprc_toml_path() if path is None else path,
            local_env_filename=self.spec.local_env_filename,
        )

    def unregister_storage(
        self,
        *,
        name: str,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Remove one live storage from this application's registry."""
        return unregister_storage(
            name=name,
            path=self.apprc_toml_path() if path is None else path,
        )

    def record_archived_storage(
        self,
        *,
        name: str,
        archive: Path,
        source_root: Path,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Remember the last archive path for one storage selector."""
        return record_archived_storage(
            name=name,
            archive=archive,
            source_root=source_root,
            path=self.apprc_toml_path() if path is None else path,
        )

    def remove_archived_storage(
        self,
        *,
        name: str,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Remove one archived-storage convenience record."""
        return remove_archived_storage(
            name=name,
            path=self.apprc_toml_path() if path is None else path,
        )

    def prune_missing_archived_storages(
        self,
        *,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Drop archive records whose last known files are gone."""
        return prune_missing_archived_storages(
            path=self.apprc_toml_path() if path is None else path
        )

    def suggested_storage_root(self) -> Path:
        """Return this app's conventional active storage directory."""
        return suggested_storage_root(self.spec.app_name)

    def suggested_storage_name(self) -> str:
        """Return this app's conventional first storage selector."""
        return suggested_storage_name(self.spec.app_name)

    def local_env_path(self, storage_root: Path) -> Path:
        """Return this application's storage-local dotenv path."""
        return local_env_path(
            storage_root,
            filename=self.spec.local_env_filename,
        )

    def set_local_value(
        self,
        *,
        storage_root: Path,
        reference: str,
        raw_value: str,
    ) -> LocalEnvUpdate:
        """Set one storage-local override value.

        :param storage_root: Active storage root from the registry.
        :param reference: Env key, dotted config path, or unique field name.
        :param raw_value: User-provided value before type validation.
        :return: Written dotenv path, env key, and normalized value.
        """
        return set_local_env_value(
            storage_root=storage_root,
            reference=reference,
            raw_value=raw_value,
            owners=self.spec.owners,
            local_env_filename=self.spec.local_env_filename,
        )

    def clear_local_value(
        self,
        *,
        storage_root: Path,
        reference: str,
    ) -> LocalEnvUpdate | None:
        """Remove one storage-local override value.

        :param storage_root: Active storage root from the registry.
        :param reference: Env key, dotted config path, or unique field name.
        :return: Written dotenv path and env key, or ``None`` when absent.
        """
        return clear_local_env_value(
            storage_root=storage_root,
            reference=reference,
            owners=self.spec.owners,
            local_env_filename=self.spec.local_env_filename,
        )

    def install_state(
        self,
        storage: str | None = None,
        apprc_toml_path: Path | None = None,
    ) -> ConfigInstallState:
        """Return this application's explicit local installation state.

        :param storage: Optional selector passed by ``--storage``.
        :param apprc_toml_path: Optional explicit AppRC TOML path used by setup.
        :return: Coarse installation and health state.
        """
        return ConfigInstallState(
            self.doctor_payload(
                storage=storage,
                apprc_toml_path=apprc_toml_path,
            )["install_state"]
        )

    def doctor_payload(
        self,
        storage: str | None = None,
        apprc_toml_path: Path | None = None,
    ) -> ConfigDoctorPayload:
        """Return JSON-friendly local setup diagnostics."""
        from apprc.config.diagnostics import build_config_doctor_payload

        return build_config_doctor_payload(
            self,
            storage=storage,
            apprc_toml_path=apprc_toml_path,
        )

    def editor_app(
        self,
        *,
        registry: StorageRegistry,
        initial_storage: str | None = None,
        active_storage_root: Path | None = None,
    ) -> ConfigEditorApp:
        """Build the generic Textual config editor for this application."""
        from apprc.config.tui import ConfigEditorApp

        return ConfigEditorApp(
            kit=self,
            registry=registry,
            initial_storage=initial_storage,
            active_storage_root=active_storage_root,
        )

    def setup_app(self) -> ConfigSetupApp:
        """Build the generic Textual setup wizard for this application."""
        from apprc.config.tui.setup import ConfigSetupApp

        return ConfigSetupApp(kit=self)

    def typer_app(
        self,
        *,
        state_type: type[StateT],
        runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
        active_storage_root: Callable[[StateT], Path | None] | None = None,
        initial_storage: Callable[[StateT], str | None] | None = None,
        editor_app_cls: type[ConfigEditorApp] | None = None,
        help: str | None = None,
        setup_message: str | None = None,
        legacy_json_migration_message: str | None = None,
        runtime_error_param_hint: str = "CONFIG",
    ) -> typer.Typer:
        """Build the generic Typer ``config`` command group.

        :param state_type: Application root CLI state type stored on
            ``ctx.obj``.
        :param runtime_payload: Optional serializer for ``config show``.
        :param active_storage_root: Optional storage-root resolver for custom
            CLI state objects.
        :param initial_storage: Optional editor initial-selection resolver.
        :param editor_app_cls: Optional Textual subclass.
        :param help: Optional Typer group help.
        :param setup_message: Optional setup text for missing storage.
        :param legacy_json_migration_message: Optional deprecated callback
            ``--json`` hint.
        :param runtime_error_param_hint: Parameter hint for runtime-payload
            validation errors.
        :return: Configured Typer app.
        """
        from apprc.cli.config import build_config_typer_app

        return build_config_typer_app(
            self,
            state_type=state_type,
            runtime_payload=runtime_payload,
            active_storage_root=active_storage_root,
            initial_storage=initial_storage,
            editor_app_cls=editor_app_cls,
            help=help,
            setup_message=setup_message,
            legacy_json_migration_message=legacy_json_migration_message,
            runtime_error_param_hint=runtime_error_param_hint,
        )
