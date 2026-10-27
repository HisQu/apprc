"""Application-bound operations shared by noninteractive and terminal callers."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config.lookup import resolve_config_field_reference
from apprc.definition.paths import AppPaths
from apprc.definition.provenance import ConfigOriginState
from apprc.definition.resolution import (
    BundleFieldSpec,
    ConfigSource,
    ImportedConfig,
    ResolveOptions,
    dependency_environment_exclusions,
    filter_dependency_environment,
)
from apprc.runtime.resolution import (
    ResolvedConfig,
    merge_layers,
    resolve_config,
)
from apprc.services.inspection import ConfigInspection, inspect_resolved
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.layouts import resolve_app_paths
from apprc.user_files.app_home.ownership import ensure_owned_path
from apprc.user_files.app_home.writes import managed_write_lock
from apprc.user_files.env_files._parsing import (
    parse_dotenv_file,
    parse_dotenv_text,
)
from apprc.user_files.env_files.secret_migration import (
    SecretMigrationPlan,
    apply_secret_migration,
    plan_secret_migration,
)
from apprc.user_files.env_files.secrets import (
    SecretFileStatus,
    ensure_secret_file,
    inspect_secret_file,
    repair_secret_file_permissions,
    secret_companion_path,
)
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
    EnvFileUpdate,
    apply_env_file_edit,
    plan_env_file_value_removal,
    plan_env_file_value_update,
)
from apprc.user_files.setup.flow import ConfigSetupResult

type WriteScope = Literal["user", "workspace"]


class ConfigManager:
    """Coordinate fixed-layout operations using a captured declaration and inputs.

    Creating a manager only captures inputs. Reading paths or planning an edit
    creates no directories. Each operation reads current files; runtime objects
    built earlier keep their own source snapshots.
    """

    def __init__(
        self,
        schema: AppConfigSpec,
        *,
        registered_types: tuple[type[object], ...],
        bundles: Mapping[type[object], tuple[BundleFieldSpec, ...]],
        imported_configs: tuple[ImportedConfig[object], ...] = (),
        options: ResolveOptions | None = None,
        environment: Mapping[str, str] | None = None,
        app_paths: AppPaths | None = None,
    ) -> None:
        """Capture operation inputs without inspecting or creating files.

        :param schema: Application declaration snapshot.
        :param registered_types: Config sections known at manager creation.
        :param bundles: Registered bundle construction rules.
        :param imported_configs: Parent-owned dependency bindings.
        :param options: Invocation choices, independent of persisted defaults.
        :param environment: Explicit environment, or a copy of the process.
        :param app_paths: Captured path snapshot supplied by an adapter.
        """
        self.schema = schema
        self.options = options or ResolveOptions()
        self.environment = MappingProxyType(
            dict(os.environ if environment is None else environment)
        )
        self._registered_types = registered_types
        self._bundles = MappingProxyType(dict(bundles))
        self._imported_configs = tuple(imported_configs)
        excluded_env_keys, excluded_env_prefixes = (
            dependency_environment_exclusions(self._imported_configs)
        )
        self.app_paths = app_paths or resolve_app_paths(
            schema,
            self.options,
            self.environment,
            excluded_env_keys=excluded_env_keys,
            excluded_env_prefixes=excluded_env_prefixes,
            allow_unready=True,
        )

    @property
    def paths(self) -> AppPaths:
        """Return this manager's captured path snapshot."""
        return self.app_paths

    def resolve(self) -> ResolvedConfig:
        """Read current files using the manager's captured paths."""
        return resolve_config(
            self.schema,
            registered_types=self._registered_types,
            bundles=self._bundles,
            imported_configs=self._imported_configs,
            options=self.options,
            environment=self.environment,
            app_paths=self.app_paths,
        )

    def inspect(
        self, *, workspace: str | None = None, include_workspace: bool = True
    ) -> ConfigInspection:
        """Inspect configuration and optionally browse a workspace overlay."""
        options = (
            replace(self.options, workspace=workspace)
            if workspace is not None
            else self.options
        )
        resolved = resolve_config(
            self.schema,
            registered_types=self._registered_types,
            bundles=self._bundles,
            imported_configs=self._imported_configs,
            options=options,
            environment=self.environment,
            allow_unready=True,
            include_workspace=include_workspace,
            app_paths=self.app_paths,
        )
        return inspect_resolved(resolved)

    def setup(self, *, adopt: bool = False) -> ConfigSetupResult:
        """Initialize only the declared configuration component.

        :param adopt: Explicitly allow adopting a nonempty unowned config root.
        :return: The initialized config directory and optional user dotenv.
        """
        config_dir = self.paths.require("config")
        with managed_write_lock(config_dir, private_directories=(config_dir,)):
            ensure_owned_path(self.schema, self.paths, "config", adopt=adopt)
            user_dotenv = (
                AppFiles(self.schema, self.paths).ensure_user_dotenv()
                if self.schema.uses_user_dotenv()
                else None
            )
            if user_dotenv is not None:
                ensure_secret_file(secret_companion_path(user_dotenv))
        return ConfigSetupResult(config_dir=config_dir, user_dotenv=user_dotenv)

    def writable_path(
        self,
        scope: WriteScope,
        *,
        workspace: str | None = None,
        secret: bool = False,
    ) -> Path:
        """Resolve an enabled saved-configuration layer.

        :param scope: User-wide or workspace-local overrides.
        :param workspace: Workspace to inspect without changing the default.
        :param secret: Whether to return the private companion file.
        :return: Fixed managed dotenv path.
        """
        files = AppFiles(self.schema, self.paths)
        if scope == "user":
            self.schema.require_user_dotenv()
            path = files.user_dotenv_path()
        elif scope == "workspace":
            self.schema.require_workspaces()
            selection = self.inspect(workspace=workspace).resolved.workspace
            if selection is None or not selection.root.is_dir():
                raise ValueError(
                    "Select an initialized workspace before editing its overrides."
                )
            path = files.workspace_dotenv_path(selection.root)
        else:
            raise ValueError(f"Unknown write scope: {scope!r}.")
        return secret_companion_path(path) if secret else path

    def secret_status(
        self, scope: WriteScope, *, workspace: str | None = None
    ) -> SecretFileStatus:
        """Report whether a selected layer can save secret fields."""
        return inspect_secret_file(
            self.writable_path(scope, workspace=workspace, secret=True)
        )

    def repair_secret_permissions(
        self, scope: WriteScope, *, workspace: str | None = None
    ) -> SecretFileStatus:
        """Apply an explicitly requested privacy repair to one layer."""
        path = self.writable_path(scope, workspace=workspace, secret=True)
        with managed_write_lock(path.parent):
            return repair_secret_file_permissions(path)

    def plan_secret_migration(
        self, scope: WriteScope, *, workspace: str | None = None
    ) -> SecretMigrationPlan:
        """Inspect legacy secret assignments without changing files."""
        regular = self.writable_path(scope, workspace=workspace)
        secret_keys = {
            owner.env_key(spec.name)
            for owner in self.schema.owners
            for spec in owner.fields
            if spec.secret
        }
        roots = tuple(
            dict.fromkeys(
                root
                for root in (self.paths.config_dir, regular.parent)
                if root is not None
            )
        )
        return replace(
            plan_secret_migration(
                regular, secret_companion_path(regular), secret_keys
            ),
            lock_roots=roots,
        )

    def apply_secret_migration(self, plan: SecretMigrationPlan) -> None:
        """Apply an explicitly reviewed move of legacy secret assignments."""
        apply_secret_migration(plan)

    def writable_scopes(
        self, *, workspace: str | None = None, include_workspace: bool = True
    ) -> tuple[WriteScope, ...]:
        """Return initialized configuration layers without requiring valid values."""
        scopes: list[WriteScope] = []
        files = AppFiles(self.schema, self.paths)
        if (
            self.schema.uses_user_dotenv()
            and files.user_dotenv_path().is_file()
        ):
            scopes.append("user")
        if self.schema.uses_workspaces() and include_workspace:
            selection = self.inspect(workspace=workspace).resolved.workspace
            if selection is not None and selection.root.is_dir():
                scopes.append("workspace")
        return tuple(scopes)

    def resolve_write_scope(self, requested: str | None = None) -> WriteScope:
        """Choose an initialized user or workspace layer."""
        scopes = self.writable_scopes()
        if requested is not None:
            if requested not in scopes:
                raise ValueError(
                    f"Scope {requested!r} is unavailable. Initialize user overrides or select a workspace."
                )
            return requested
        if len(scopes) == 1:
            return scopes[0]
        if not scopes:
            raise ValueError(
                "No writable AppRC layer is active. Run setup first."
            )
        raise ValueError(
            "Both user and workspace dotenv files are writable. Pass --scope user or --scope workspace."
        )

    def plan_update(
        self,
        reference: str,
        raw_value: str,
        *,
        scope: WriteScope,
        workspace: str | None = None,
    ) -> EnvFileEditPlan:
        """Validate a value and retain its original revision before editing."""
        owner, spec = resolve_config_field_reference(
            self.schema.owners, reference
        )
        path = self.writable_path(
            scope, workspace=workspace, secret=spec.secret
        )
        if spec.secret:
            self._require_private_secret_edit(
                scope, owner.env_key(spec.name), workspace=workspace
            )
        config_root = self.paths.config_dir
        lock_roots = tuple(
            dict.fromkeys(
                root for root in (config_root, path.parent) if root is not None
            )
        )
        return replace(
            plan_env_file_value_update(
                path=path,
                reference=reference,
                raw_value=raw_value,
                owners=self.schema.owners,
                layer_name=path.name,
                private=spec.secret,
            ),
            lock_roots=lock_roots,
            private_directories=(
                (config_root,)
                if scope == "user" and config_root is not None
                else ()
            ),
        )

    def plan_removal(
        self,
        reference: str,
        *,
        scope: WriteScope,
        workspace: str | None = None,
    ) -> EnvFileEditPlan | None:
        """Plan removal of every active assignment for a field."""
        owner, spec = resolve_config_field_reference(
            self.schema.owners, reference
        )
        path = self.writable_path(
            scope, workspace=workspace, secret=spec.secret
        )
        if spec.secret:
            self._require_private_secret_edit(
                scope, owner.env_key(spec.name), workspace=workspace
            )
        plan = plan_env_file_value_removal(
            path=path,
            reference=reference,
            owners=self.schema.owners,
            layer_name=path.name,
            private=spec.secret,
        )
        config_root = self.paths.config_dir
        lock_roots = tuple(
            dict.fromkeys(
                root for root in (config_root, path.parent) if root is not None
            )
        )
        return (
            None
            if plan is None
            else replace(
                plan,
                lock_roots=lock_roots,
                private_directories=(
                    (config_root,)
                    if scope == "user" and config_root is not None
                    else ()
                ),
            )
        )

    def _require_private_secret_edit(
        self, scope: WriteScope, env_key: str, *, workspace: str | None
    ) -> None:
        """Avoid unsafe writes or revealing a legacy ordinary-file value."""
        regular = self.writable_path(scope, workspace=workspace)
        environment = filter_dependency_environment(
            self.environment, self._imported_configs
        )
        excluded_env_keys, excluded_env_prefixes = (
            dependency_environment_exclusions(self._imported_configs)
        )
        if env_key in parse_dotenv_file(
            regular,
            environment=environment,
            excluded_env_keys=excluded_env_keys,
            excluded_env_prefixes=excluded_env_prefixes,
        ):
            raise ValueError(
                f"{env_key} is still in {regular.name}. Run `config secrets migrate` first."
            )
        status = self.secret_status(scope, workspace=workspace)
        if not status.available:
            raise ValueError(status.issue or "Secret file is unavailable.")

    def apply_edit(self, plan: EnvFileEditPlan) -> EnvFileUpdate:
        """Initialize config ownership, then apply a revision-checked edit."""
        config_root = self.paths.config_dir
        if config_root is not None and plan.path.is_relative_to(config_root):
            ensure_owned_path(self.schema, self.paths, "config")
        return apply_env_file_edit(plan)

    def preview_edit(
        self,
        plan: EnvFileEditPlan,
        *,
        workspace: str | None = None,
    ) -> ConfigInspection:
        """Inspect a proposed edit without changing files or selection."""
        resolved = self.inspect(workspace=workspace).resolved
        environment = filter_dependency_environment(
            self.environment, self._imported_configs
        )
        excluded_env_keys, excluded_env_prefixes = (
            dependency_environment_exclusions(self._imported_configs)
        )
        values = filter_dependency_environment(
            parse_dotenv_text(
                plan.text,
                environment=environment,
                excluded_env_keys=excluded_env_keys,
                excluded_env_prefixes=excluded_env_prefixes,
            ),
            self._imported_configs,
        )
        layers = tuple(
            replace(
                layer,
                source=ConfigSource(
                    values,
                    {
                        key: ConfigOriginState(
                            layer.origin, env_key=key, path=layer.path
                        )
                        for key in values
                    },
                ),
            )
            if layer.path is not None
            and layer.path.resolve() == plan.path.resolve()
            else layer
            for layer in resolved.layers
        )
        return inspect_resolved(
            replace(resolved, layers=layers, source=merge_layers(layers))
        )
