"""Shared base class for generated config command handlers."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Any, cast

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces.cli.config_command.group_options import ConfigGroupOptions
from apprc.interfaces.cli.config_command._selector_context import (
    ConfigSelectorContext,
    ConfigStateResolver,
    ResolvedConfigState,
    SelectorContextReader,
    _empty_selector_context,
)
from apprc.interfaces.cli.config_command._editor_launcher import (
    ConfigEditorLauncher,
)
from apprc.interfaces.cli.config_command._runtime_payload import (
    default_runtime_payload,
)
from apprc.interfaces.cli.config_command.state import (
    ConfigCliState,
    DefaultConfigCliState,
    active_storage_root_from_env,
    active_storage_root_from_state,
)
from apprc.interfaces.cli._errors import apprc_dir_bad_parameter
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.storage_roots._loading import (
    load_create_or_empty_storage_registry,
    load_optional_runtime_storage_registry,
)
from apprc.user_files.storage_roots.registry import StorageRegistry
from apprc.user_files.storage_roots.selector import StorageSelectorError


class ConfigCommandBase:
    """Shared dependencies and adapters for generated config commands."""

    def __init__(
        self,
        kit: AppConfigKit,
        *,
        options: ConfigGroupOptions,
        missing_setup: str,
    ) -> None:
        """Store config command dependencies and extension hooks.

        :param kit: Application config facade.
        :param options: Generated config command hook bundle.
        :param missing_setup: Message shown when runtime storage is absent.
        """
        self.kit = kit
        self.state_type = options.state_type
        self.runtime_payload = options.runtime_payload
        self.active_storage_root_with_context_hook = (
            options.active_storage_root_with_context
        )
        self.missing_setup = missing_setup
        self.runtime_error_param_hint = options.runtime_error_param_hint
        self.config_group_name = options.config_group_name
        self.state_resolver = ConfigStateResolver(options.state_type)
        self.selector_context_reader = SelectorContextReader()
        self.editor_launcher = ConfigEditorLauncher(
            kit=kit,
            editor_app_cls=options.editor_app_cls,
            config_group_name=options.config_group_name,
            initial_storage_with_context_hook=(
                options.initial_storage_with_context
            ),
        )

    def state(self, ctx: typer.Context) -> Any:
        """Return the application CLI state stored by the parent CLI."""
        return self.state_resolver.state(ctx)

    def context_state(self, ctx: typer.Context) -> DefaultConfigCliState | None:
        """Return AppRC context as generic config state when available."""
        return self.state_resolver.context_state(ctx)

    def resolved_config_state(
        self,
        ctx: typer.Context,
    ) -> ResolvedConfigState | None:
        """Return state plus whether app-owned hooks may inspect it."""
        return self.state_resolver.resolved_config_state(ctx)

    def runtime_payload_state(
        self,
        resolved_state: ResolvedConfigState | None,
    ) -> Any | None:
        """Return state that is valid for app-owned runtime payload hooks."""
        return self.state_resolver.runtime_payload_state(resolved_state)

    def config_command_text(self, action: str) -> str:
        """Return one CLI command line for generated CLI guidance."""
        return (
            f"{self.kit.spec.config_command_name()} "
            f"{self.config_group_name} {action}"
        )

    def cli_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        return self.selector_context_reader.cli_context_param(ctx, name)

    def cli_selector_context(self, ctx: typer.Context) -> ConfigSelectorContext:
        """Return CLI explicit env-file values for selector-only reads."""
        return self.selector_context_reader.cli_selector_context(ctx)

    def apprc_dir_bad_parameter(
        self,
        exc: AppRCDirectoryError | OSError,
    ) -> typer.BadParameter:
        """Return Typer's error type for AppRC directory failures.

        :param exc: Path preparation failure from AppRC-managed files.
        :return: Typer parameter error with the shared directory hint.
        """
        return apprc_dir_bad_parameter(exc)

    def apprc_toml_bad_parameter(
        self,
        exc: ValueError,
    ) -> typer.BadParameter:
        """Return Typer's error type for AppRC TOML failures."""
        return typer.BadParameter(
            str(exc), param_hint=self.kit.spec.apprc_dir_env_key
        )

    def require_storage_support(self) -> None:
        """Raise a CLI error when a storage command is unavailable."""
        if not self.kit.spec.uses_storage():
            raise typer.BadParameter(
                f"{self.kit.spec.display_name} does not use AppRC storage.",
                param_hint="storage",
            )

    def require_storage_registry_support(self) -> None:
        """Raise a CLI error when storage is unavailable."""
        self.require_storage_support()

    def load_optional_storage_registry(
        self,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> StorageRegistry | None:
        """Return the AppRC TOML storage registry when it exists."""
        context = selector_context or _empty_selector_context()
        try:
            return load_optional_runtime_storage_registry(
                self.kit.spec,
                proc_env=context.proc_env,
            )
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise self.apprc_toml_bad_parameter(exc) from exc

    def load_storage_registry_or_empty(
        self,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> StorageRegistry:
        """Return a parsed or empty storage registry without writing."""
        self.require_storage_registry_support()
        context = selector_context or _empty_selector_context()
        try:
            return load_create_or_empty_storage_registry(
                self.kit.spec.preferred_apprc_toml_path(context.proc_env)
            )
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise self.apprc_toml_bad_parameter(exc) from exc

    def active_storage_root_for_cli(
        self,
        resolved_state: ResolvedConfigState,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path | None:
        """Return the selected storage root using app overrides first."""
        context = selector_context or _empty_selector_context()
        state = resolved_state.state
        try:
            if (
                resolved_state.app_owned
                and self.active_storage_root_with_context_hook is not None
            ):
                return self.active_storage_root_with_context_hook(
                    state,
                    context,
                )
            return active_storage_root_from_state(
                self.kit,
                cast(ConfigCliState, state),
                explicit_values=context.explicit_values,
                env_file_overrides_os_environ=(
                    context.env_file_overrides_os_environ
                ),
            )
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def required_storage_root_for_write(
        self,
        resolved_state: ResolvedConfigState,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path:
        """Return a writable active storage root or raise a CLI error."""
        storage_root = self.active_storage_root_for_cli(
            resolved_state,
            selector_context=selector_context,
        )
        if storage_root is None:
            raise typer.BadParameter(
                f"No active {self.kit.spec.display_name} storage root. Run "
                f"`{self.config_command_text('setup --yes --storage-root /absolute/path/to/storage')}` "
                "or pass --storage NAME.",
                param_hint="--storage",
            )
        return self.validate_storage_root_for_write(storage_root)

    def validate_storage_root_for_write(self, storage_root: Path) -> Path:
        """Reject writes when the active storage root no longer exists."""
        root = Path(storage_root).expanduser()
        if not root.is_dir():
            raise typer.BadParameter(
                f"Active storage root does not exist: {root}",
                param_hint="--storage",
            )
        return root

    def best_effort_active_storage_root_from_env(
        self,
        *,
        storage_registry: StorageRegistry | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path | None:
        """Return the env-selected storage root, suppressing selector errors."""
        context = selector_context or _empty_selector_context()
        try:
            storage_root = active_storage_root_from_env(
                self.kit,
                registry=storage_registry,
                explicit_values=context.explicit_values,
                env_file_overrides_os_environ=(
                    context.env_file_overrides_os_environ
                ),
            )
            if storage_root is None or not storage_root.is_dir():
                return None
            return storage_root
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except StorageSelectorError:
            return None
        except ValueError:
            return None

    def active_storage_root_for_editor(
        self,
        current_state: ResolvedConfigState | None,
        *,
        selector_context: ConfigSelectorContext | None = None,
    ) -> Path | None:
        """Return the storage root selected for zero-write editor reads."""
        if not self.kit.spec.uses_storage():
            return None
        context = selector_context or _empty_selector_context()
        try:
            if current_state is not None:
                return self.active_storage_root_for_cli(
                    current_state,
                    selector_context=context,
                )
            return active_storage_root_from_env(
                self.kit,
                explicit_values=context.explicit_values,
                env_file_overrides_os_environ=(
                    context.env_file_overrides_os_environ
                ),
            )
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except AppRCDirectoryError as exc:
            raise self.apprc_dir_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def default_runtime_payload(
        self,
        *,
        storage_root: Path | None,
    ) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        return default_runtime_payload(self.kit, storage_root=storage_root)

    def launch_config_editor(
        self,
        *,
        current_state: ResolvedConfigState | None,
        storage_registry: StorageRegistry | None,
        storage_registry_error: str | None,
        active_storage_root: Path | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> None:
        """Create and run the Textual config editor."""
        self.editor_launcher.launch(
            current_state=current_state,
            storage_registry=storage_registry,
            storage_registry_error=storage_registry_error,
            active_storage_root=active_storage_root,
            selector_context=selector_context,
        )

    def initial_storage_for_editor(
        self,
        resolved_state: ResolvedConfigState,
        *,
        storage_registry: StorageRegistry | None,
        selector_context: ConfigSelectorContext | None = None,
    ) -> str | None:
        """Return the storage name the editor should select on startup."""
        return self.editor_launcher.initial_storage(
            resolved_state,
            storage_registry=storage_registry,
            selector_context=selector_context,
        )
