"""Command handlers for generated AppRC ``config`` commands."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

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
from apprc.cli.doctor import print_config_doctor, print_config_paths
from apprc.cli.errors import config_home_bad_parameter
from apprc.cli.setup import run_config_setup
from apprc.cli.typer_utils import dump_json, exit_missing_action, state_from
from apprc.runtime_config.config_home import ConfigHomeError
from apprc.runtime_config.doctor.payload import build_config_doctor_payload
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.env_file import (
    set_env_file_value,
    set_storage_env_value,
)
from apprc.runtime_config.storage.loading import (
    index_path_for_create,
    load_create_or_empty_storage_registry,
    load_optional_runtime_storage_registry,
)
from apprc.runtime_config.storage.paths import StorageRootPathError
from apprc.runtime_config.storage.registry import (
    StorageRegistry,
    register_storage,
    unregister_storage,
)
from apprc.runtime_config.storage.selector import StorageSelectorError

if TYPE_CHECKING:
    from apprc.runtime_config.tui import ConfigEditorApp

type ConfigSetScope = Literal["app", "storage"]


class ConfigCommandBase:
    """Shared dependencies and adapters for generated config commands."""

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
        :param runtime_error_param_hint: Parameter hint for runtime-payload
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

    def state(self, ctx: typer.Context) -> Any:
        """Return the application root state stored by the parent CLI."""
        return state_from(ctx, self.state_type)

    def root_context_param(
        self,
        ctx: typer.Context,
        name: str,
    ) -> object | None:
        """Read one option value from the parent command context."""
        if ctx.parent is None:
            return None
        return ctx.parent.params.get(name)

    def config_home_bad_parameter(
        self,
        exc: ConfigHomeError | OSError,
    ) -> typer.BadParameter:
        """Return Typer's error type for AppRC config-home failures.

        :param exc: Path preparation failure from AppRC-managed files.
        :return: Typer parameter error with the shared config-home hint.
        """
        return config_home_bad_parameter(exc)

    def index_bad_parameter(
        self,
        exc: ValueError,
    ) -> typer.BadParameter:
        """Return Typer's error type for named-storage index failures."""
        return typer.BadParameter(
            str(exc), param_hint=self.kit.spec.index_env_key
        )

    def require_storage_capability(self) -> None:
        """Raise a CLI error when a storage command is unavailable."""
        if not self.kit.spec.storage_required():
            raise typer.BadParameter(
                f"{self.kit.spec.display_name} does not use AppRC storage.",
                param_hint="storage",
            )

    def require_named_storage_capability(self) -> None:
        """Raise a CLI error when named storage is unavailable."""
        self.require_storage_capability()
        if not self.kit.spec.named_storage_allowed():
            raise typer.BadParameter(
                f"{self.kit.spec.display_name} does not enable named storage.",
                param_hint="storage",
            )

    def load_optional_storage_registry(self) -> StorageRegistry | None:
        """Return the named-storage index only when it exists."""
        try:
            return load_optional_runtime_storage_registry(self.kit.spec)
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise self.index_bad_parameter(exc) from exc

    def load_list_storage_registry(self) -> StorageRegistry:
        """Return a parsed or empty named-storage registry without writing."""
        self.require_named_storage_capability()
        try:
            return load_create_or_empty_storage_registry(
                index_path_for_create(self.kit.spec)
            )
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise self.index_bad_parameter(exc) from exc

    def active_storage_root_for_cli(self, state: Any) -> Path | None:
        """Return the selected storage root using app overrides first."""
        try:
            if self.active_storage_root_hook is not None:
                return self.active_storage_root_hook(state)
            return active_storage_root_from_state(
                self.kit,
                cast(ConfigCliState, state),
            )
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def required_storage_root_for_write(self, state: Any) -> Path:
        """Return a writable active storage root or raise a CLI error."""
        storage_root = self.active_storage_root_for_cli(state)
        if storage_root is None:
            raise typer.BadParameter(
                f"No active {self.kit.spec.display_name} storage root. Run "
                f"`{self.kit.spec.config_command_name()} config setup --yes "
                "--storage-root /absolute/path/to/storage` or pass --storage.",
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
    ) -> Path | None:
        """Return the env-selected storage root, suppressing selector errors."""
        try:
            storage_root = active_storage_root_from_env(
                self.kit,
                registry=storage_registry,
            )
            if storage_root is None or not storage_root.is_dir():
                return None
            return storage_root
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except StorageSelectorError:
            return None
        except ValueError:
            return None

    def active_storage_root_for_editor(
        self,
        current_state: Any | None,
    ) -> Path | None:
        """Return the storage root selected for zero-write editor reads."""
        if not self.kit.spec.storage_required():
            return None
        try:
            if current_state is not None:
                return self.active_storage_root_for_cli(current_state)
            return active_storage_root_from_env(self.kit)
        except StorageSelectorError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint=exc.param_hint,
            ) from exc
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--storage") from exc

    def default_runtime_payload(
        self,
        *,
        storage_root: Path | None,
    ) -> dict[str, Any]:
        """Return generic ``config show`` data when the app provides none."""
        storage_env = (
            str(self.kit.spec.storage_env_path(storage_root))
            if storage_root is not None
            else None
        )
        return {
            "app_name": self.kit.spec.app_name,
            "display_name": self.kit.spec.display_name,
            "capabilities": {
                "storage": self.kit.spec.storage_layer.value,
                "app_wide": self.kit.spec.app_wide_layer.value,
                "named_storage": self.kit.spec.named_storage_layer.value,
            },
            "config_home": str(self.kit.spec.config_home()),
            "app_wide_env": str(self.kit.spec.app_wide_env_path()),
            "index_path": str(self.kit.spec.index_path()),
            "storage_root": str(storage_root) if storage_root else None,
            "storage_env": storage_env,
        }

    def launch_config_editor(
        self,
        *,
        current_state: Any | None,
        storage_registry: StorageRegistry | None,
        active_storage_root: Path | None,
    ) -> None:
        """Create and run the Textual config editor."""
        selected_storage = (
            self.initial_storage_for_editor(
                current_state,
                storage_registry=storage_registry,
            )
            if current_state is not None
            else None
        )
        if self.editor_app_cls is not None:
            editor_app = self.editor_app_cls(
                kit=self.kit,
                storage_registry=storage_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
            )
        else:
            from apprc.runtime_config.tui import ConfigEditorApp

            editor_app = ConfigEditorApp(
                kit=self.kit,
                storage_registry=storage_registry,
                initial_storage=selected_storage,
                active_storage_root=active_storage_root,
            )
        editor_app.run()

    def initial_storage_for_editor(
        self,
        state: Any,
        *,
        storage_registry: StorageRegistry | None,
    ) -> str | None:
        """Return the storage name the editor should select on startup."""
        if self.initial_storage_hook is not None:
            return self.initial_storage_hook(state)
        return initial_storage_from_state(
            self.kit,
            cast(ConfigCliState, state),
            registry=storage_registry,
        )


class StorageConfigCommands(ConfigCommandBase):
    """Named-storage config command implementations."""

    def storage_list(self, *, json_output: bool) -> None:
        """List named storage roots from the optional index."""
        registry = self.load_list_storage_registry()
        payload = storage_list_payload(
            registry,
            storage_env_filename=self.kit.spec.storage_env_filename,
            active_storage_root=self.best_effort_active_storage_root_from_env(
                storage_registry=registry,
            ),
        )
        if json_output:
            dump_json(payload)
            return
        print_storage_list(payload)

    def storage_add(
        self,
        *,
        name: str,
        path: Path,
        assume_yes: bool,
    ) -> None:
        """Create or update one named storage entry."""
        self.require_named_storage_capability()
        normalized_root = guard_storage_root_init(
            self.kit,
            path,
            storage_name=name,
            assume_yes=assume_yes,
        )
        try:
            registry = register_storage(
                name=name,
                root=normalized_root,
                path=index_path_for_create(self.kit.spec),
                storage_env_filename=self.kit.spec.storage_env_filename,
            )
        except StorageRootPathError as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="PATH",
            ) from exc
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc

        record = registry.selected(name)
        typer.echo(f"storage: {record.name}")
        typer.echo(f"storage_root: {record.root}")
        typer.echo(
            f"storage_env: {self.kit.spec.storage_env_path(record.root)}"
        )
        typer.echo(f"index_path: {registry.path}")

    def storage_remove(self, *, name: str) -> None:
        """Remove one named storage entry from the index."""
        self.require_named_storage_capability()
        try:
            registry = unregister_storage(
                name=name,
                path=index_path_for_create(self.kit.spec),
            )
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="NAME") from exc
        typer.echo(f"removed_storage: {name}")
        typer.echo(f"index_path: {registry.path}")


class RuntimeConfigCommands(ConfigCommandBase):
    """Runtime config command implementations."""

    def paths(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show declared and active config paths without writing files."""
        storage = self.root_context_param(ctx, "storage")
        storage_selector = storage if isinstance(storage, str) else None
        payload = build_config_doctor_payload(
            self.kit,
            storage=storage_selector,
        )
        if json_output:
            dump_json(payload)
            return
        print_config_paths(self.kit, payload)

    def show(self, ctx: typer.Context, *, json_output: bool) -> None:
        """Show the resolved runtime config available to this invocation."""
        current_state = (
            self.state(ctx)
            if self.kit.spec.storage_required()
            or isinstance(ctx.obj, self.state_type)
            else None
        )
        storage_root = (
            self.active_storage_root_for_cli(current_state)
            if current_state is not None
            else None
        )
        if self.kit.spec.storage_required() and storage_root is None:
            typer.echo(self.missing_setup, err=True)
            raise typer.Exit(code=1)
        try:
            payload = (
                self.runtime_payload(current_state)
                if self.runtime_payload is not None
                and current_state is not None
                else self.default_runtime_payload(storage_root=storage_root)
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
        """Check AppRC config readiness and print suggested fixes."""
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
        if payload["status"] != ConfigDoctorStatus.RUNNABLE.value:
            raise typer.Exit(code=1)

    def set(
        self,
        ctx: typer.Context,
        *,
        key: str,
        value: str,
        scope: str | None,
    ) -> None:
        """Write one config override to the selected writable layer."""
        current_state = (
            ctx.obj if isinstance(ctx.obj, self.state_type) else None
        )
        resolved_scope = self._resolve_write_scope(
            current_state,
            requested_scope=scope,
        )
        if resolved_scope == "app":
            update = self._set_app_value(key=key, value=value)
            typer.echo(f"updated: {update.env_key}")
            typer.echo(f"app_wide_env: {update.path}")
            return
        if current_state is None:
            raise typer.BadParameter(
                "Storage scope requires runtime CLI state.",
                param_hint="--scope",
            )
        root = self.required_storage_root_for_write(current_state)
        update = self._set_storage_value(root=root, key=key, value=value)
        typer.echo(f"updated: {update.env_key}")
        typer.echo(f"storage_env: {update.path}")

    def _resolve_write_scope(
        self,
        state: Any | None,
        *,
        requested_scope: str | None,
    ) -> ConfigSetScope:
        """Return the target write scope or raise for ambiguous writes.

        :param state: Optional application root CLI state.
        :param requested_scope: User-provided scope.
        :return: Concrete write scope.
        :raises typer.BadParameter: If no layer or multiple layers qualify.
        """
        if requested_scope is not None:
            if requested_scope not in {"app", "storage"}:
                raise typer.BadParameter(
                    "--scope must be 'app' or 'storage'.",
                    param_hint="--scope",
                )
            resolved_requested_scope = cast(ConfigSetScope, requested_scope)
            if not self._write_scope_is_active(
                state,
                resolved_requested_scope,
            ):
                raise typer.BadParameter(
                    _inactive_scope_message(self.kit, resolved_requested_scope),
                    param_hint="--scope",
                )
            return resolved_requested_scope
        active_scopes = self._active_write_scopes(state)
        if len(active_scopes) == 1:
            return active_scopes[0]
        if not active_scopes:
            raise typer.BadParameter(
                "No writable AppRC layer is active. Run `config app init`, "
                "select a storage root, or set environment variables directly.",
                param_hint="--scope",
            )
        raise typer.BadParameter(
            "Both app-wide and storage layers are writable. Pass "
            "--scope app or --scope storage.",
            param_hint="--scope",
        )

    def _active_write_scopes(
        self,
        state: Any | None,
    ) -> list[ConfigSetScope]:
        """Return write scopes currently active for ``config set``."""
        return [
            scope
            for scope in ("app", "storage")
            if self._write_scope_is_active(state, scope)
        ]

    def _write_scope_is_active(
        self,
        state: Any | None,
        scope: ConfigSetScope,
    ) -> bool:
        """Return whether one write scope can be updated now."""
        if scope == "app":
            app_path = self.kit.spec.app_wide_env_path()
            return self.kit.spec.app_wide_allowed() and (
                self.kit.spec.app_wide_default() or app_path.is_file()
            )
        if not self.kit.spec.storage_required() or state is None:
            return False
        storage_root = self.active_storage_root_for_cli(state)
        return storage_root is not None and storage_root.is_dir()

    def _set_app_value(self, *, key: str, value: str):
        """Write one value to the app-wide dotenv file."""
        try:
            return set_env_file_value(
                path=self.kit.spec.app_wide_env_path(),
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                layer_name=self.kit.spec.app_wide_env_filename,
            )
        except (ConfigHomeError, OSError) as exc:
            raise self.config_home_bad_parameter(exc) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc

    def _set_storage_value(self, *, root: Path, key: str, value: str):
        """Write one value to the selected storage dotenv file."""
        try:
            return set_storage_env_value(
                storage_root=root,
                reference=key,
                raw_value=value,
                owners=self.kit.spec.owners,
                storage_env_filename=self.kit.spec.storage_env_filename,
            )
        except (ConfigHomeError, OSError, StorageRootPathError) as exc:
            raise typer.BadParameter(
                str(exc),
                param_hint="--storage",
            ) from exc
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="KEY") from exc


class AppWideConfigCommands(ConfigCommandBase):
    """App-wide config command implementations."""

    def app_init(self) -> None:
        """Create the app-wide dotenv file explicitly."""
        if not self.kit.spec.app_wide_allowed():
            raise typer.BadParameter(
                f"{self.kit.spec.display_name} does not enable app-wide config.",
                param_hint="app",
            )
        try:
            path = self.kit.spec.ensure_app_wide_env()
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc
        typer.echo(f"app_wide_env: {path}")


class EditorConfigCommands(ConfigCommandBase):
    """Textual editor command implementation."""

    def edit(self, ctx: typer.Context) -> None:
        """Open the Textual editor for AppRC dotenv override files."""
        current_state = (
            ctx.obj if isinstance(ctx.obj, self.state_type) else None
        )
        try:
            active_storage_root = self.active_storage_root_for_editor(
                current_state
            )
            try:
                optional_registry = self.load_optional_storage_registry()
            except typer.BadParameter:
                if (
                    active_storage_root is None
                    and self.kit.spec.named_storage_default()
                ):
                    raise
                optional_registry = None
            self.launch_config_editor(
                current_state=current_state,
                storage_registry=optional_registry,
                active_storage_root=active_storage_root,
            )
        except ConfigHomeError as exc:
            raise self.config_home_bad_parameter(exc) from exc


class ConfigCommandHandlers(
    RuntimeConfigCommands,
    StorageConfigCommands,
    AppWideConfigCommands,
    EditorConfigCommands,
):
    """Command implementations for the generated ``config`` Typer group."""

    def callback(self, ctx: typer.Context) -> None:
        """Show config help when no subcommand was selected."""
        if ctx.invoked_subcommand is not None:
            return
        exit_missing_action(ctx)

    def setup(
        self,
        *,
        assume_yes: bool,
        storage_root: Path | None,
    ) -> None:
        """Configure files for the declared AppRC capability layers."""
        run_config_setup(
            self.kit,
            assume_yes=assume_yes,
            storage_root=storage_root,
        )


def _inactive_scope_message(
    kit: AppConfigKit,
    scope: ConfigSetScope,
) -> str:
    """Return a readable error for an unavailable write scope.

    :param kit: Application config facade.
    :param scope: Requested write scope.
    :return: Human-facing CLI error.
    """
    if scope == "app":
        return (
            "The app-wide layer is not active. Run "
            f"`{kit.spec.config_command_name()} config app init` first."
        )
    return (
        "The storage layer is not active. Select a storage root with --storage "
        f"or export {kit.spec.storage_env_key}."
    )
