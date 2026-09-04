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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

# == Internal ================================
from apprc.definition.app_config.spec import AppConfigSpec
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
        app_id: str,
        display_name: str | None,
        config_package: str,
        envs: tuple[type[EnvConfig], ...] = (),
        storage: Storage | None = None,
        command_name: str | None = None,
        apprc_dir: Path | None = None,
        apprc_dir_env_key: str | None = None,
        legacy_app_ids: tuple[str, ...] = (),
        _bootstrap_state: BootstrapState | None = None,
    ) -> None: ...

    def __init__(
        self,
        spec: AppConfigSpec | None = None,
        *,
        app_id: str | None = None,
        display_name: str | None = None,
        config_package: str | None = None,
        envs: tuple[type[EnvConfig], ...] = (),
        storage: Storage | None = None,
        command_name: str | None = None,
        apprc_dir: Path | None = None,
        apprc_dir_env_key: str | None = None,
        legacy_app_ids: tuple[str, ...] = (),
        _bootstrap_state: BootstrapState | None = None,
    ) -> None:
        """Store the application spec or build one from keyword arguments."""
        self._bootstrap_state = _bootstrap_state or BootstrapState()
        if spec is not None:
            self.spec = spec
            return
        if app_id is None or display_name is None or config_package is None:
            raise TypeError(
                "AppConfigKit requires either an AppConfigSpec or all "
                "required application spec keyword arguments."
            )
        self.spec = AppConfigSpec(
            app_id=app_id,
            display_name=display_name or app_id,
            config_package=config_package,
            envs=envs,
            storage=storage,
            command_name=command_name,
            apprc_dir=apprc_dir,
            apprc_dir_env_key=apprc_dir_env_key,
            legacy_app_ids=legacy_app_ids,
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
            packaged ``apprc.defaults.env``, user ``apprc.user.env``, and
            active storage ``apprc.storage.env``.
        :param env_file_overrides_os_environ: Whether explicit dotenv values beat
            existing values in ``os.environ`` inside this process. The parent
            shell is never mutated.
        :param load_dotenv_layers: Whether packaged ``apprc.defaults.env``,
            user ``apprc.user.env``, active storage ``apprc.storage.env``,
            and explicit ``env_files`` values should be merged into this
            process. Storage selection still runs for storage apps
            when this is ``False``, and explicit values may still provide the
            selector used for selection.
        :param storage: Optional registered name supplied by ``--storage``.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        with self._bootstrap_state.lock:
            if self._bootstrap_state.result is not None:
                LOG.warning(
                    "AppRC bootstrap is running again for %s. Existing "
                    "config objects keep their current values; config objects "
                    "constructed afterward read the new process environment.",
                    self.spec.app_id,
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
