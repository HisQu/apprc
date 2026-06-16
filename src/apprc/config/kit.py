"""High-level facade for one application's AppRC integration.

``AppConfigKit`` is the convenient entrypoint for applications. It stores one
``AppConfigSpec`` and delegates to the focused lower-level modules for storage
registries, dotenv bootstrapping, diagnostics, and Typer command generation.

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
from apprc.config.app_spec import AppConfigSpec, RegistryEnvError
from apprc.config.environment import (
    BootstrapLogger,
    EnvBootstrapResult,
    bootstrap_env,
)
from apprc.config.schema import ConfigOwner
from apprc.config.storage.registry import (
    StorageRegistry,
    load_storage_registry_or_empty,
)

StateT = TypeVar("StateT")

if TYPE_CHECKING:
    import typer

    from apprc.config.tui import ConfigEditorApp


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
                else AppConfigSpec.derive_apprc_toml_filename(app_name)
            ),
            shared_env_filename=shared_env_filename,
            local_env_filename=local_env_filename,
        )

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
        :param storage: Optional ``--storage`` selector. With a registry it may
            be a registered storage name or path. Without a registry it is
            always interpreted as a path.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        return bootstrap_env(
            spec=self.spec,
            env_file=env_file,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )

    def load_required_registry(self) -> StorageRegistry:
        """Read this application's required multi-storage registry.

        :return: Parsed storage registry.
        :raises RegistryEnvError: If the registry env var is missing or points at
            a missing file.
        :raises ValueError: If the registry cannot be parsed.
        """
        resolved_path = self.spec.required_apprc_toml_path()
        if not resolved_path.is_file():
            message = self.spec.missing_apprc_toml_file_message(resolved_path)
            raise RegistryEnvError(message)
        return load_storage_registry_or_empty(resolved_path)

    def load_optional_registry(self) -> StorageRegistry | None:
        """Read the registry only when ``<APP>_APPRC_TOML`` is set.

        :return: Parsed storage registry, or ``None`` in single-storage mode.
        :raises RegistryEnvError: If the registry env var points at a missing file.
        :raises ValueError: If the registry cannot be parsed.
        """
        if self.spec.optional_apprc_toml_path() is None:
            return None
        return self.load_required_registry()

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
            runtime_error_param_hint=runtime_error_param_hint,
        )
