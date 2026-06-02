"""High-level facade for one application's AppRC integration.

``AppConfigKit`` is the convenient entrypoint for applications. It stores one
``AppConfigSpec`` and delegates to the focused lower-level modules for storage
registries, dotenv bootstrapping, local value editing, diagnostics, Textual
editing, and Typer command generation.

Use this module when wiring an application like Haiu. Use the sibling modules
directly when testing one layer in isolation or when building a custom workflow
that should not pull in CLI/TUI dependencies.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar, overload

# == Internal ================================
from apprc.config.app_spec import AppConfigSpec
from apprc.config.environment import (
    BootstrapLogger,
    EnvBootstrapResult,
    bootstrap_env,
)
from apprc.config.local_env import (
    LocalEnvUpdate,
    local_env_path,
    read_local_env,
    set_local_env_value,
    write_local_env,
)
from apprc.config.schema import ConfigOwner
from apprc.config.storage_registry import (
    StorageRegistry,
    load_storage_registry,
    register_storage,
    set_default_storage,
)

StateT = TypeVar("StateT")


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
        storage_root_env_key: str,
        registry_filename: str = "app.toml",
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
        storage_root_env_key: str | None = None,
        registry_filename: str = "app.toml",
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
            or storage_root_env_key is None
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
            storage_root_env_key=storage_root_env_key,
            registry_filename=registry_filename,
            shared_env_filename=shared_env_filename,
            local_env_filename=local_env_filename,
        )

    def registry_path(
        self,
        proc_env: Mapping[str, str] | None = None,
    ) -> Path:
        """Return the default user storage registry path.

        :param proc_env: Optional environment mapping for tests.
        :return: Default registry path for this application.
        """
        return self.spec.registry_path(proc_env)

    def bootstrap(
        self,
        *,
        env_file: Path | None,
        env_file_overrides_shell: bool,
        no_dotenv: bool,
        storage_name: str | None,
        logger: BootstrapLogger | None = None,
    ) -> EnvBootstrapResult:
        """Populate ``os.environ`` for this application.

        :param env_file: Optional explicit dotenv file.
        :param env_file_overrides_shell: Whether explicit dotenv values beat
            already exported variables inside this process.
        :param no_dotenv: Disable dotenv layer loading.
        :param storage_name: Optional named storage selector.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        return bootstrap_env(
            spec=self.spec.env_bootstrap_spec(),
            env_file=env_file,
            env_file_overrides_shell=env_file_overrides_shell,
            no_dotenv=no_dotenv,
            storage_name=storage_name,
            logger=logger,
        )

    def load_registry(self, path: Path | None = None) -> StorageRegistry:
        """Read this application's storage registry.

        :param path: Optional explicit registry path for tests.
        :return: Parsed storage registry, or an empty registry.
        """
        return load_storage_registry(
            self.registry_path() if path is None else path
        )

    def register_storage(
        self,
        *,
        name: str,
        root: Path,
        make_default: bool,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Add or update one storage entry for this application."""
        registry = register_storage(
            name=name,
            root=root,
            make_default=make_default,
            path=self.registry_path() if path is None else path,
            local_env_filename=self.spec.local_env_filename,
        )
        self._write_storage_root_local_value(registry.selected(name).root)
        return registry

    def set_default_storage(
        self,
        *,
        name: str,
        path: Path | None = None,
    ) -> StorageRegistry:
        """Set an existing storage as the default for this application."""
        registry = set_default_storage(
            name=name,
            path=self.registry_path() if path is None else path,
        )
        self._write_storage_root_local_value(registry.selected(name).root)
        return registry

    def _write_storage_root_local_value(self, storage_root: Path) -> Path:
        """Persist the registry-managed storage root in local dotenv form.

        :param storage_root: Resolved root of the registered storage.
        :return: Path to the storage-local dotenv file.
        """
        path = self.local_env_path(storage_root)
        values = read_local_env(path)
        values[self.spec.storage_root_env_key] = str(
            Path(storage_root).expanduser().resolve()
        )
        return write_local_env(path, values, owners=self.spec.owners)

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

    def doctor_payload(self, storage_name: str | None = None) -> dict[str, Any]:
        """Return JSON-friendly local setup diagnostics."""
        from apprc.cli.doctor import build_config_doctor_payload

        return build_config_doctor_payload(self, storage_name=storage_name)

    def editor_app(
        self,
        *,
        registry: StorageRegistry,
        initial_storage: str | None = None,
    ) -> Any:
        """Build the generic Textual config editor for this application."""
        from apprc.config.tui import ConfigEditorApp

        return ConfigEditorApp(
            kit=self,
            registry=registry,
            initial_storage=initial_storage,
        )

    def typer_app(
        self,
        *,
        state_type: type[StateT],
        runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
        active_storage_root: Callable[[StateT], Path | None] | None = None,
        initial_storage: Callable[[StateT], str | None] | None = None,
        editor_app_cls: type[Any] | None = None,
        help: str | None = None,
        setup_message: str | None = None,
        legacy_json_migration_message: str | None = None,
        runtime_error_param_hint: str = "CONFIG",
    ) -> Any:
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
        from apprc.cli.config_app import build_config_typer_app

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
