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
import logging
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

# == Internal ================================
from apprc.definition.app_config.capabilities import (
    CapabilityState,
    StorageLayerState,
)
from apprc.definition.app_config.spec import (
    DEFAULT_APP_ENV_FILENAME,
    DEFAULT_APPRC_TOML_FILENAME,
    DEFAULT_DEFAULTS_ENV_FILENAME,
    AppConfigSpec,
)
from apprc.definition.app_config.storage import Storage
from apprc.definition.env_config.env import EnvConfig
from apprc.runtime._bootstrap_state import BootstrapState
from apprc.runtime.bootstrap import (
    BootstrapLogger,
    EnvBootstrapResult,
    bootstrap_env,
)

StateT = TypeVar("StateT")
LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    import typer

    from apprc.interfaces.cli.config_command import ConfigSelectorContext
    from apprc.interfaces.tui import ConfigEditorApp


class AppConfigKit:
    """Convenience facade around one application's config contract.

    The kit is intentionally small: it stores the app spec and delegates each
    workflow to the lower-level modules. Applications can stay at this level
    for normal CLI setup while tests and advanced integrations can still import
    the individual storage, dotenv, schema, or TUI modules directly.
    """

    @overload
    def __init__(
        self,
        spec: AppConfigSpec,
        *,
        _bootstrap_state: BootstrapState | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        spec: None = None,
        *,
        app_name: str,
        display_name: str | None,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage: Storage | None = None,
        command_name: str | None = None,
        defaults_env_filename: str = DEFAULT_DEFAULTS_ENV_FILENAME,
        app_env_filename: str = DEFAULT_APP_ENV_FILENAME,
        apprc_toml_filename: str = DEFAULT_APPRC_TOML_FILENAME,
        storage_env_key: str | None = None,
        storage_layer: StorageLayerState | str | None = None,
        app_wide_layer: CapabilityState | str | None = None,
        named_storage_layer: CapabilityState | str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str | None = None,
        app_wide_env_filename: str | None = None,
        storage_env_filename: str | None = None,
        _legacy_constructor: str | None = None,
        _bootstrap_state: BootstrapState | None = None,
    ) -> None: ...

    def __init__(
        self,
        spec: AppConfigSpec | None = None,
        *,
        app_name: str | None = None,
        display_name: str | None = None,
        config_package: str | None = None,
        envs: tuple[type[EnvConfig], ...] = (),
        storage: Storage | None = None,
        command_name: str | None = None,
        defaults_env_filename: str = DEFAULT_DEFAULTS_ENV_FILENAME,
        app_env_filename: str = DEFAULT_APP_ENV_FILENAME,
        apprc_toml_filename: str = DEFAULT_APPRC_TOML_FILENAME,
        storage_env_key: str | None = None,
        storage_layer: StorageLayerState | str | None = None,
        app_wide_layer: CapabilityState | str | None = None,
        named_storage_layer: CapabilityState | str | None = None,
        index_filename: str | None = None,
        shared_env_filename: str | None = None,
        app_wide_env_filename: str | None = None,
        storage_env_filename: str | None = None,
        _legacy_constructor: str | None = None,
        _bootstrap_state: BootstrapState | None = None,
    ) -> None:
        """Store the application spec or build one from keyword arguments."""
        self._bootstrap_state = _bootstrap_state or BootstrapState()
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
            display_name=display_name or app_name,
            config_package=config_package,
            envs=envs,
            storage=storage,
            command_name=command_name,
            defaults_env_filename=defaults_env_filename,
            app_env_filename=app_env_filename,
            apprc_toml_filename=apprc_toml_filename,
            storage_env_key=storage_env_key,
            storage_layer=storage_layer,
            app_wide_layer=app_wide_layer,
            named_storage_layer=named_storage_layer,
            index_filename=index_filename,
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
            _legacy_constructor=_legacy_constructor,
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
        :param storage_env_filename: Storage dotenv override filename.
        :return: Kit with storage and named-storage disabled.
        """
        cls._warn_legacy_constructor("env_only")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_layer=StorageLayerState.DISABLED,
            app_wide_layer=CapabilityState.OPTIONAL,
            named_storage_layer=CapabilityState.DISABLED,
            command_name=command_name,
            index_filename=(
                AppConfigSpec.derive_legacy_apprc_toml_filename(app_name)
                if index_filename is None
                else index_filename
            ),
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
            _legacy_constructor="env_only",
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
        :param storage_env_filename: Storage dotenv override filename.
        :return: Kit with storage required and app-wide/index upgrades enabled.
        """
        cls._warn_legacy_constructor("storage_only")
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
            index_filename=(
                AppConfigSpec.derive_legacy_apprc_toml_filename(app_name)
                if index_filename is None
                else index_filename
            ),
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
            _legacy_constructor="storage_only",
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
        :param storage_env_filename: Storage dotenv override filename.
        :return: Kit with app-wide config enabled by default.
        """
        cls._warn_legacy_constructor("app_wide_config")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            envs=envs,
            storage_layer=StorageLayerState.DISABLED,
            app_wide_layer=CapabilityState.DEFAULT,
            named_storage_layer=CapabilityState.DISABLED,
            command_name=command_name,
            index_filename=(
                AppConfigSpec.derive_legacy_apprc_toml_filename(app_name)
                if index_filename is None
                else index_filename
            ),
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
            _legacy_constructor="app_wide_config",
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
        :param storage_env_filename: Storage dotenv override filename.
        :return: Kit with app-wide config and storage enabled.
        """
        cls._warn_legacy_constructor("app_wide_storage")
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
            index_filename=(
                AppConfigSpec.derive_legacy_apprc_toml_filename(app_name)
                if index_filename is None
                else index_filename
            ),
            shared_env_filename=shared_env_filename,
            app_wide_env_filename=app_wide_env_filename,
            storage_env_filename=storage_env_filename,
            _legacy_constructor="app_wide_storage",
        )

    @staticmethod
    def _warn_legacy_constructor(name: str) -> None:
        """Warn that a 0.19 capability constructor will be removed.

        :param name: Deprecated constructor name used by the caller.
        """
        warnings.warn(
            f"AppConfigKit.{name}(...) is deprecated in AppRC 0.20 and "
            "will be removed in 0.21. Instantiate AppConfigKit(...) directly "
            "and pass storage=Storage(...) when the app needs storage.",
            DeprecationWarning,
            stacklevel=2,
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

        :param env_files: Optional CLI-run-local dotenv files that outrank
            packaged ``apprc.defaults.env``, app ``apprc.app.env``, and
            active storage ``apprc.storage.env``.
        :param env_file_overrides_os_environ: Whether explicit dotenv values beat
            existing values in ``os.environ`` inside this process. The parent
            shell is never mutated.
        :param load_dotenv_layers: Whether packaged ``apprc.defaults.env``,
            app ``apprc.app.env``, active storage ``apprc.storage.env``,
            and explicit ``env_files`` values should be merged into this
            process. Storage selection still runs for storage apps
            when this is ``False``, and explicit values may still provide the
            selector used for selection.
        :param storage: Optional ``--storage`` selector for storage apps. With
            AppRC TOML it may be a registered storage name or path.
            Without registered storages it is interpreted as a path.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        with self._bootstrap_state.lock:
            if self._bootstrap_state.result is not None:
                LOG.warning(
                    "AppRC bootstrap is running again for %s. Existing "
                    "config objects keep their current values; config objects "
                    "constructed afterward read the new process environment.",
                    self.spec.app_name,
                )
            result = bootstrap_env(
                spec=self.spec,
                env_files=env_files,
                env_file_overrides_os_environ=env_file_overrides_os_environ,
                load_dotenv_layers=load_dotenv_layers,
                storage=storage,
                logger=logger,
            )
            self._bootstrap_state.result = result
            return result

    def _ensure_bootstrapped(self) -> EnvBootstrapResult:
        """Return existing bootstrap state or load the default layers.

        This private kit hook keeps the public convenience API on ``AppRC``
        while sharing state with CLI callbacks that bootstrap through the kit.

        :return: Latest successful bootstrap result.
        """
        with self._bootstrap_state.lock:
            if self._bootstrap_state.result is not None:
                return self._bootstrap_state.result
            return self.bootstrap(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=None,
            )

    def typer_app(
        self,
        *,
        state_type: type[StateT] | None = None,
        runtime_payload: Callable[[StateT], Mapping[str, Any]] | None = None,
        active_storage_root_with_context: (
            Callable[[StateT, ConfigSelectorContext], Path | None] | None
        ) = None,
        initial_storage_with_context: (
            Callable[[StateT, ConfigSelectorContext], str | None] | None
        ) = None,
        editor_app_cls: type[ConfigEditorApp] | None = None,
        help: str | None = None,
        setup_message: str | None = None,
        runtime_error_param_hint: str = "CONFIG",
        config_group_name: str = "config",
    ) -> typer.Typer:
        """Build the generic Typer ``config`` command group.

        :param state_type: Application host CLI state type stored on
            ``ctx.obj``. When omitted, AppRC uses its default config state.
        :param runtime_payload: Optional serializer for ``config show``.
        :param active_storage_root_with_context: Optional storage-root resolver
            that receives explicit env-file selector context.
        :param initial_storage_with_context: Optional editor initial-selection
            resolver that receives explicit env-file selector context.
        :param editor_app_cls: Optional Textual subclass.
        :param help: Optional Typer group help.
        :param setup_message: Optional setup text for missing storage.
        :param runtime_error_param_hint: Parameter hint for runtime-payload
            validation errors.
        :param config_group_name: Config command group name used in generated
            guidance.
        :return: Configured Typer app.
        """
        from apprc.interfaces.cli.config_command import (
            DefaultConfigCliState,
        )
        from apprc.interfaces.cli.config_command.app import (
            build_config_typer_app_from_options,
        )
        from apprc.interfaces.cli.config_command.group_options import (
            ConfigGroupOptions,
        )

        resolved_state_type = state_type or DefaultConfigCliState
        group_options = ConfigGroupOptions(
            state_type=resolved_state_type,
            runtime_payload=runtime_payload,
            active_storage_root_with_context=active_storage_root_with_context,
            initial_storage_with_context=initial_storage_with_context,
            editor_app_cls=editor_app_cls,
            help=help,
            setup_message=setup_message,
            runtime_error_param_hint=runtime_error_param_hint,
            config_group_name=config_group_name,
        )

        return build_config_typer_app_from_options(
            self,
            options=group_options,
        )
