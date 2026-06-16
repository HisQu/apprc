"""Command handlers for generated AppRC ``config`` commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

# == 3rd Party ===============================
import typer
from rich import print as rich_print

# == Internal ================================
from apprc.cli.config.output import print_storage_list, storage_list_payload
from apprc.cli.config.prompts import guard_storage_root_init
from apprc.cli.config.state import (
    ConfigCliState,
    active_storage_root_from_env,
    active_storage_root_from_state,
    initial_storage_from_state,
)
from apprc.cli.doctor import print_config_doctor
from apprc.cli.setup import run_config_setup
from apprc.cli.typer_utils import dump_json, exit_missing_action, state_from
from apprc.config.diagnostics import build_config_doctor_payload
from apprc.config.kit import AppConfigKit
from apprc.config.local_env import set_local_env_value
from apprc.config.paths import StorageRootPathError
from apprc.config.registry_env import RegistryEnvError
import apprc.config.setup.flow as setup_flow
from apprc.config.storage.registry import StorageRegistry, register_storage
from apprc.config.storage.selector import StorageSelectorError

if TYPE_CHECKING:
    from apprc.config.tui import ConfigEditorApp


class ConfigCommandHandlers:
    """Command implementations for the generated ``config`` Typer group.

    The Typer factory owns option declarations and command registration. This
    class owns the behavior those command callbacks execute, which keeps CLI
    parsing separate from AppRC state mutations.
    """

    def __init__(
        self,
        kit: AppConfigKit,
        *,
        state_type: type[Any],
        runtime_payload: Callable[[Any], Mapping[str, Any]] | None,
        active_storage_root: Callable[[Any], Path | None] | None,
        initial_storage: Callable[[Any], str | None] | None,
        editor_app_cls: type[ConfigEditorApp] | None,
        missing_setup: str,
        runtime_error_param_hint: str,
    ) -> None:
        """Store config command dependencies and extension hooks.

        :param kit: Application config facade.
        :param state_type: Application root CLI state type stored on
            ``ctx.obj``.
        :param runtime_payload: Optional serializer for ``config show``.
        :param active_storage_root: Optional active storage resolver.
        :param initial_storage: Optional editor initial-selection resolver.
        :param editor_app_cls: Optional Textual subclass.
        :param missing_setup: Message shown when runtime storage is absent.
        :param runtime_error_param_hint: Parameter hint for runtime payload
            validation errors.
        """
        self.kit = kit
        self.state_type = state_type
        self.runtime_payload = runtime_payload
        self.active_storage_root_hook = active_storage_root
        self.initial_storage_hook = initial_storage
        self.editor_app_cls = editor_app_cls
        self.missing_setup = missing_setup
        self.runtime_error_param_hint = runtime_error_param_hint

    def callback(self, ctx: typer.Context) -> None:
        """Show config help when no subcommand was selected."""
        if ctx.invoked_subcommand is not None:
            return
        exit_missing_action(ctx)

    def list(self, *, json_output: bool) -> None:
        """List registered storage roots from the user registry."""
        registry = self.required_registry()
        payload = storage_list_payload(
            registry,
            local_env_filename=self.kit.spec.local_env_filename,
            active_storage_root=self.optional_active_storage_root_from_env(
                registry
            ),
        )
        if json_output:
            dump_json(payload)
            return
        print_storage_list(payload)

    def show(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show the resolved runtime config available to this invocation."""
        current_state = self.state(ctx)
        if self.active_storage_root(current_state) is None:
            typer.echo(self.missing_setup, err=True)
            raise typer.Exit(code=1)
        try:
            payload = (
                self.runtime_payload(current_state)
                if self.runtime_payload is not None
                else self.default_runtime_payload(current_state)
            )
        except ValueError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.runtime_error_param_hint,
            ) from exc
        if json_output:
            dump_json(payload)
            return
        rich_print(payload)

    def doctor(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Check local storage setup and print suggested fixes."""
        storage = self.root_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.kit,
            storage=storage_selector,
        )
        if json_output:
            dump_json(payload)
        else:
            print_config_doctor(self.kit, payload)
        if not payload["runnable"]:
            raise typer.Exit(code=1)

    def init(
        self,
        *,
        storage_root: Path,
        name: str,
        assume_yes: bool,
    ) -> None:
        """Register one storage root and create its local env file."""
        try:
            registry_path = self.kit.spec.required_apprc_toml_path()
        except RegistryEnvError as exc:
            raise self._registry_bad_parameter(exc) from exc
        normalized_root = guard_storage_root_init(
            self.kit,
            storage_root,
            storage_name=name,
            assume_yes=assume_yes,
        )
        try:
            registry = register_storage(
                name=name,
                root=normalized_root,
                path=registry_path,
                local_env_filename=self.kit.spec.local_env_filename,
            )
        except StorageRootPathError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="STORAGE_ROOT",
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--name") from exc

        record = registry.selected(name)
        typer.echo(f"registered_storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(
            f"local_env: {record.root / self.kit.spec.local_env_filename}"
        )
        typer.echo(f"registry_path: {registry.path}")

    def setup(
        self,
        *,
        assume_yes: bool,
        apprc_dir: Path | None,
        storage_root: Path | None,
        storage_name: str | None,
        multi_storage: bool,
        existing_action: setup_flow.ExistingSetupAction | None,
    ) -> None:
        """Configure the active storage root and optional registry."""
        run_config_setup(
            self.kit,
            assume_yes=assume_yes,
            apprc_dir=apprc_dir,
            storage_root=storage_root,
            storage_name=storage_name,
            multi_storage=multi_storage,
            existing_action=existing_action,
        )

    def set(self, ctx: typer.Context, *, key: str, value: str) -> None:
        """Write one active storage-local config override."""
        root = self.validate_storage_root_for_write(
            self.required_storage_root(self.state(ctx))
        )
        try:
            update = set_local_env_value(
                storage_root=root,
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                local_env_filename=self.kit.spec.local_env_filename,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"local_env: {update.path}")

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for registered storage-local env files."""
        optional_registry = self.optional_registry()
        current_state = (
            ctx.obj if isinstance(ctx.obj, self.state_type) else None
        )
        selected_storage = (
            self.initial_storage(current_state, registry=optional_registry)
            if current_state is not None
            else None
        )
        active_storage_root = self.optional_active_storage_root_from_env(
            optional_registry
        )
        if self.editor_app_cls is not None:
            editor_app = self.editor_app_cls(
                kit=self.kit,
                registry=optional_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
            )
        else:
            from apprc.config.tui import ConfigEditorApp

            editor_app = ConfigEditorApp(
                kit=self.kit,
                registry=optional_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
            )
        editor_app.run()

    def state(self, ctx: typer.Context) -> Any:
        """Return the application root state stored by the parent CLI."""
        return state_from(ctx, self.state_type)

    def active_storage_root(self, state: Any) -> Path | None:
        """Return the selected storage root using app overrides first."""
        try:
            if self.active_storage_root_hook is not None:
                return self.active_storage_root_hook(state)
            return active_storage_root_from_state(
                self.kit,
                cast(ConfigCliState, state),
            )
        except RegistryEnvError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=self.kit.spec.apprc_toml_env_key,
            ) from exc
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def initial_storage(
        self,
        state: Any,
        registry: StorageRegistry | None = None,
    ) -> str | None:
        """Return the storage name the editor should select on startup."""
        if self.initial_storage_hook is not None:
            return self.initial_storage_hook(state)
        return initial_storage_from_state(
            self.kit,
            cast(ConfigCliState, state),
            registry=registry,
        )

    def required_registry(self) -> StorageRegistry:
        """Return the registry required by registry-only CLI commands."""
        try:
            return self.kit.load_required_registry()
        except (RegistryEnvError, ValueError) as exc:
            raise self._registry_bad_parameter(exc) from exc

    def optional_registry(self) -> StorageRegistry | None:
        """Return the registry only when multi-storage is enabled."""
        try:
            return self.kit.load_optional_registry()
        except (RegistryEnvError, ValueError) as exc:
            raise self._registry_bad_parameter(exc) from exc

    def _registry_bad_parameter(
        self,
        exc: RegistryEnvError | ValueError,
    ) -> typer.BadParameter:
        """Return Typer's error type for registry loading failures."""
        param_hint = (
            self.kit.spec.apprc_toml_env_key
            if isinstance(exc, RegistryEnvError)
            else self.kit.spec.apprc_toml_filename
        )
        return typer.BadParameter(str(exc), param_hint=param_hint)

    def optional_active_storage_root_from_env(
        self,
        registry: StorageRegistry | None,
    ) -> Path | None:
        """Return the env-selected storage root when it is displayable."""
        try:
            return active_storage_root_from_env(
                self.kit,
                registry=registry,
            )
        except StorageSelectorError:
            return None

    def required_storage_root(self, state: Any) -> Path:
        """Return an active storage root or raise Typer's CLI error type."""
        storage_root = self.active_storage_root(state)
        if storage_root is not None:
            return storage_root
        raise typer.BadParameter(
            f"No active {self.kit.spec.display_name} storage root. Run "
            f"`{self.kit.spec.config_command_name()} config setup --yes "
            "--storage-root /absolute/path/to/storage` or pass --storage.",
            param_hint="--storage",
        )

    def validate_storage_root_for_write(self, storage_root: Path) -> Path:
        """Reject writes when the active storage root no longer exists."""
        root = Path(storage_root).expanduser()
        if not root.is_dir():
            raise typer.BadParameter(
                f"Active storage root does not exist: {root}",
                param_hint="--storage",
            )
        return root

    def root_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        if ctx.parent is None:
            return None
        return ctx.parent.params.get(name)

    def default_runtime_payload(self, state: Any) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        storage_root = self.active_storage_root(state)
        registry_path = self.kit.spec.optional_apprc_toml_path()
        return {
            "app_name": self.kit.spec.app_name,
            "display_name": self.kit.spec.display_name,
            "registry_path": (
                str(registry_path) if registry_path is not None else None
            ),
            "storage_root": str(storage_root) if storage_root else None,
        }
