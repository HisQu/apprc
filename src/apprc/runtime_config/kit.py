"""High-level facade for one application's AppRC integration.

``AppConfigKit`` is the convenient entrypoint for applications. It stores one
``AppConfigSpec`` and delegates to the focused lower-level modules for AppRC
TOML loading, dotenv bootstrapping, diagnostics, and Typer command generation.

Use this module when wiring a host application. Use the sibling modules
directly when testing one layer in isolation or when building a custom workflow
that should not pull in CLI/TUI dependencies.
"""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

# == Internal ================================
from apprc.runtime_config.app_spec import (
    AppConfigSpec,
    CapabilityState,
    StorageLayerState,
)
from apprc.runtime_config.bootstrap.orchestrator import (
    BootstrapLogger,
    EnvBootstrapResult,
    bootstrap_env,
)
from apprc.runtime_config.config_objects.env_config import EnvConfig

StateT = TypeVar("StateT")

if TYPE_CHECKING:
    import typer

    from apprc.runtime_config.tui import ConfigEditorApp


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
        envs: tuple[type[EnvConfig], ...] = (),
        storage_env_key: str | None = None,
        storage_layer: StorageLayerState | str = StorageLayerState.DISABLED,
        app_wide_layer: CapabilityState | str = CapabilityState.OPTIONAL,
        named_storage_layer: CapabilityState | str = CapabilityState.DISABLED,
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> None: ...

    def __init__(
        self,
        spec: AppConfigSpec | None = None,
        *,
        app_name: str | None = None,
        display_name: str | None = None,
        config_package: str | None = None,
        envs: tuple[type[EnvConfig], ...] = (),
        storage_env_key: str | None = None,
        storage_layer: StorageLayerState | str = StorageLayerState.DISABLED,
        app_wide_layer: CapabilityState | str = CapabilityState.OPTIONAL,
        named_storage_layer: CapabilityState | str = CapabilityState.DISABLED,
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> None:
        """Store the application spec or build one from keyword arguments."""
        if spec is not None:
            self.spec = spec
            return
        if app_name is None or display_name is None or config_package is None:
            raise TypeError(
                "AppConfigKit requires either an AppConfigSpec or all "
                "required application spec keyword arguments."
            )
        self.spec = AppConfigSpec(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_env_key=storage_env_key,
            storage_layer=storage_layer,
            app_wide_layer=app_wide_layer,
            named_storage_layer=named_storage_layer,
            command_name=command_name,
            index_filename=(
                index_filename
                if index_filename is not None
                else AppConfigSpec.derive_index_filename(app_name)
            ),
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
        )

    @classmethod
    def env_only(
        cls,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> AppConfigKit:
        """Create a setup-free integration with env/package/shell layers.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param command_name: Optional executable name shown in CLI copy.
        :param index_filename: Optional named-storage index filename override.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param app_wide_env_filename: App-wide dotenv override filename.
        :param storage_env_filename: Storage-local dotenv override filename.
        :return: Kit with storage and named-storage disabled.
        """
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_layer=StorageLayerState.DISABLED,
            app_wide_layer=CapabilityState.OPTIONAL,
            named_storage_layer=CapabilityState.DISABLED,
            command_name=command_name,
            index_filename=index_filename,
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
        )

    @classmethod
    def storage_only(
        cls,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage_env_key: str | None = None,
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> AppConfigKit:
        """Create an integration that requires one active storage selector.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param storage_env_key: Optional explicit storage selector env key.
        :param command_name: Optional executable name shown in CLI copy.
        :param index_filename: Optional named-storage index filename override.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param app_wide_env_filename: App-wide dotenv override filename.
        :param storage_env_filename: Storage-local dotenv override filename.
        :return: Kit with storage required and app-wide/index upgrades enabled.
        """
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_env_key=storage_env_key,
            storage_layer=StorageLayerState.REQUIRED,
            app_wide_layer=CapabilityState.OPTIONAL,
            named_storage_layer=CapabilityState.OPTIONAL,
            command_name=command_name,
            index_filename=index_filename,
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
        )

    @classmethod
    def app_wide_config(
        cls,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> AppConfigKit:
        """Create an integration centered on the app-wide dotenv layer.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param command_name: Optional executable name shown in CLI copy.
        :param index_filename: Optional named-storage index filename override.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param app_wide_env_filename: App-wide dotenv override filename.
        :param storage_env_filename: Storage-local dotenv override filename.
        :return: Kit with app-wide config enabled by default.
        """
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_layer=StorageLayerState.DISABLED,
            app_wide_layer=CapabilityState.DEFAULT,
            named_storage_layer=CapabilityState.DISABLED,
            command_name=command_name,
            index_filename=index_filename,
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
        )

    @classmethod
    def app_wide_storage(
        cls,
        *,
        app_name: str,
        display_name: str,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage_env_key: str | None = None,
        command_name: str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str = ".env.shared",
        app_wide_env_filename: str = ".env.apprc-app",
        storage_env_filename: str = ".env.apprc-storage",
    ) -> AppConfigKit:
        """Create an integration with app-wide config and storage roots.

        :param app_name: Lowercase application name used in env var derivation.
        :param display_name: Human-readable application name.
        :param config_package: Package containing the packaged shared dotenv.
        :param envs: ``EnvConfig`` classes decorated with ``@env_owner``.
        :param storage_env_key: Optional explicit storage selector env key.
        :param command_name: Optional executable name shown in CLI copy.
        :param index_filename: Optional named-storage index filename override.
        :param shared_env_filename: Packaged shared dotenv filename.
        :param app_wide_env_filename: App-wide dotenv override filename.
        :param storage_env_filename: Storage-local dotenv override filename.
        :return: Kit with app-wide config and storage enabled.
        """
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_env_key=storage_env_key,
            storage_layer=StorageLayerState.REQUIRED,
            app_wide_layer=CapabilityState.DEFAULT,
            named_storage_layer=CapabilityState.OPTIONAL,
            command_name=command_name,
            index_filename=index_filename,
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
        )

    def bootstrap(
        self,
        *,
        env_files: Sequence[Path],
        env_file_overrides_os_environ: bool,
        load_dotenv_layers: bool,
        storage: str | None,
        logger: BootstrapLogger | None = None,
    ) -> EnvBootstrapResult:
        """Populate ``os.environ`` for this application.

        :param env_files: Optional invocation-local dotenv files that outrank
            packaged ``.env.shared``, app-wide ``.env.apprc-app``, and active
            storage-local ``.env.apprc-storage``.
        :param env_file_overrides_os_environ: Whether explicit dotenv values beat
            existing values in ``os.environ`` inside this process. The parent
            shell is never mutated.
        :param load_dotenv_layers: Whether packaged ``.env.shared``,
            app-wide ``.env.apprc-app``, active storage-local
            ``.env.apprc-storage``,
            and explicit ``env_files`` values should be merged into this
            process. Storage selection still runs for storage-required apps
            when this is ``False``, and explicit values may still provide the
            selector used for selection.
        :param storage: Optional ``--storage`` selector for storage-required
            apps. With AppRC TOML it may be a registered storage name or path.
            Without registered storages it is interpreted as a path.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        return bootstrap_env(
            spec=self.spec,
            env_files=env_files,
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )

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
