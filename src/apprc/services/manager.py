"""Application-bound operations shared by noninteractive and terminal callers."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.resolution import (
    BundleFieldSpec,
    ConfigSource,
    ResolveOptions,
)
from apprc.definition.provenance import ConfigOriginState
from apprc.definition.env_config.lookup import resolve_config_field_reference
from apprc.user_files.env_files.layers import read_explicit_env_files
from apprc.runtime._selection import selection_env
from apprc.runtime.resolution import (
    ResolvedConfig,
    merge_layers,
    resolve_config,
)
from apprc.services.inspection import ConfigInspection, inspect_resolved
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.locations import AppRCDirectoryPaths
from apprc.user_files.app_home.writes import managed_write_lock
from apprc.user_files.env_files.updates import (
    EnvFileEditPlan,
    EnvFileUpdate,
    apply_env_file_edit,
    plan_env_file_value_update,
    plan_env_file_value_removal,
)
from apprc.user_files.env_files._parsing import (
    parse_dotenv_file,
    parse_dotenv_text,
)
from apprc.user_files.env_files.secrets import (
    SecretFileStatus,
    ensure_secret_file,
    inspect_secret_file,
    repair_secret_file_permissions,
    secret_companion_path,
)
from apprc.user_files.env_files.secret_migration import (
    SecretMigrationPlan,
    apply_secret_migration as apply_secret_migration_plan,
    plan_secret_migration as build_secret_migration_plan,
)
from apprc.user_files.migration import (
    ConfigMigrationPlan,
    ConfigMigrationResult,
    StorageMigrationResolution,
    apply_config_migration,
    build_config_migration_plan,
)
from apprc.user_files.purge import (
    ConfigPurgePlan,
    ConfigPurgeResult,
    apply_config_purge,
    build_config_purge_plan,
)
from apprc.user_files.setup.flow import ConfigSetupFlow, ConfigSetupResult
from apprc.user_files.storage_roots import registry as storage_registry
from apprc.user_files.storage_roots.archive import (
    StorageArchiveProgress,
    archive_directory,
    extract_archive,
)
from apprc.user_files.storage_roots.model import StorageRegistry
from apprc.user_files.storage_roots._loading import (
    StorageRegistryInspection,
    inspect_storage_registry,
)
from apprc.user_files.storage_roots.move import StorageMoveResult, move_storage
from apprc.user_files.storage_roots.paths import resolve_storage_root_path

type WriteScope = Literal["user", "storage"]


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
        options: ResolveOptions | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        """Capture operation inputs without inspecting or creating files.

        :param schema: Application declaration snapshot.
        :param registered_types: Config sections known at manager creation.
        :param bundles: Registered bundle construction rules.
        :param options: Invocation choices, independent of persisted defaults.
        :param environment: Explicit environment, or a copy of the process.
        """
        self.schema = schema
        self.options = options or ResolveOptions()
        self.environment = MappingProxyType(
            dict(os.environ if environment is None else environment)
        )
        self._registered_types = registered_types
        self._bundles = MappingProxyType(dict(bundles))

    def _path_environment(
        self, *, allow_unready: bool = False
    ) -> dict[str, str]:
        """Apply structural directory precedence without mutating the process."""
        try:
            _, _, explicit = read_explicit_env_files(
                self.options.env_files, environment=self.environment
            )
        except (OSError, ValueError):
            if not allow_unready:
                raise
            explicit = {}
        environment = selection_env(
            original_env=self.environment,
            explicit_values=explicit,
            env_file_overrides_os_environ=self.options.env_file_overrides_os_environ,
        )
        if self.options.apprc_dir is not None:
            environment[self.schema.apprc_dir_env_key] = str(
                self.options.apprc_dir
            )
        return environment

    @property
    def paths(self) -> AppRCDirectoryPaths:
        """Resolve managed paths without reading registry or creating files."""
        if not self.schema.uses_managed_files():
            raise ValueError(
                "This application declares no managed-file capability."
            )
        return AppFiles(self.schema).paths(self._path_environment())

    def resolve(self) -> ResolvedConfig:
        """Read current files and validate the runtime storage requirement."""
        return resolve_config(
            self.schema,
            registered_types=self._registered_types,
            bundles=self._bundles,
            options=self.options,
            environment=self.environment,
        )

    def inspect(
        self, *, storage: str | None = None, include_storage: bool = True
    ) -> ConfigInspection:
        """Inspect values even when required fields or selected storage are missing.

        :param storage: Optional storage to browse for this inspection only.
        :param include_storage: Whether to include storage while browsing user overrides.
        :return: Per-field state and readiness findings; no persisted selection changes.
        """
        options = (
            replace(self.options, storage=storage)
            if storage is not None
            else self.options
        )
        resolved = resolve_config(
            self.schema,
            registered_types=self._registered_types,
            bundles=self._bundles,
            options=options,
            environment=self.environment,
            allow_unready=True,
            include_storage=include_storage,
        )
        return inspect_resolved(resolved)

    def setup(
        self,
        *,
        storage_root: Path | None = None,
        storage_name: str = "default",
    ) -> ConfigSetupResult:
        """Initialize the declared writable capabilities without prompts.

        :param storage_root: Initial storage directory, required for storage setup.
        :param storage_name: Registry name for the initial storage.
        :return: Paths initialized by the existing setup workflow.
        """
        flow = ConfigSetupFlow(
            self.schema, environment=self._path_environment()
        )
        if self.schema.uses_storage():
            if storage_root is None:
                raise ValueError("storage_root is required for storage setup.")
            root = resolve_storage_root_path(storage_root, base=self.paths.root)
            with managed_write_lock(self.paths.root, root):
                return flow.run_storage_setup(root, storage_name=storage_name)
        with managed_write_lock(self.paths.root):
            self.schema.require_user_dotenv()
            return flow.run_user_dotenv_setup()

    def setup_user_dotenv(self) -> ConfigSetupResult:
        """Initialize user overrides independently of storage readiness.

        :return: Created or existing user dotenv path and its managed directory.
        """
        self.schema.require_user_dotenv()
        with managed_write_lock(self.paths.root):
            return ConfigSetupFlow(
                self.schema, environment=self._path_environment()
            ).run_user_dotenv_setup()

    def writable_path(
        self,
        scope: WriteScope,
        *,
        storage: str | None = None,
        secret: bool = False,
    ) -> Path:
        """Resolve a declared edit target independently of required setting values.

        :param scope: User-wide or storage-local saved overrides.
        :param storage: Storage being edited; does not persist a new default.
        :return: Fixed managed dotenv path.
        """
        if scope == "user":
            self.schema.require_user_dotenv()
            path = self.paths.user_dotenv
            return secret_companion_path(path) if secret else path
        if scope != "storage":
            raise ValueError(f"Unknown write scope: {scope!r}.")
        self.schema.require_storage()
        inspected = self.inspect(storage=storage)
        selection = inspected.resolved.selection
        if selection is None:
            raise ValueError(
                "Select an initialized storage before editing its overrides."
            )
        if not selection.root.is_dir():
            raise ValueError("The inspected storage directory does not exist.")
        path = AppFiles(self.schema).storage_dotenv_path(selection.root)
        return secret_companion_path(path) if secret else path

    def secret_status(
        self, scope: WriteScope, *, storage: str | None = None
    ) -> SecretFileStatus:
        """Report whether a selected layer can save secret fields."""
        return inspect_secret_file(
            self.writable_path(scope, storage=storage, secret=True)
        )

    def repair_secret_permissions(
        self, scope: WriteScope, *, storage: str | None = None
    ) -> SecretFileStatus:
        """Apply an explicitly requested privacy repair to one layer."""
        path = self.writable_path(scope, storage=storage, secret=True)
        with managed_write_lock(path.parent):
            return repair_secret_file_permissions(path)

    def plan_secret_migration(
        self, scope: WriteScope, *, storage: str | None = None
    ) -> SecretMigrationPlan:
        """Inspect legacy secret assignments without changing files."""
        regular = self.writable_path(scope, storage=storage)
        secret_keys = {
            owner.env_key(spec.name)
            for owner in self.schema.owners
            for spec in owner.fields
            if spec.secret
        }
        return replace(
            build_secret_migration_plan(
                regular, secret_companion_path(regular), secret_keys
            ),
            lock_roots=(self.paths.root, regular.parent),
        )

    def apply_secret_migration(self, plan: SecretMigrationPlan) -> None:
        """Apply an explicitly reviewed move of legacy secret assignments."""
        apply_secret_migration_plan(plan)

    def writable_scopes(
        self, *, storage: str | None = None, include_storage: bool = True
    ) -> tuple[WriteScope, ...]:
        """Return initialized edit scopes without requiring valid setting values.

        :param storage: Optional inspected storage, without changing the saved default.
        :param include_storage: Whether this view includes a storage layer.
        :return: User scope when its file exists and storage scope when its root exists.
        """
        scopes: list[WriteScope] = []
        if self.schema.uses_user_dotenv() and self.paths.user_dotenv.is_file():
            scopes.append("user")
        if self.schema.uses_storage() and include_storage:
            selection = self.inspect(storage=storage).resolved.selection
            if selection is not None and selection.root.is_dir():
                scopes.append("storage")
        return tuple(scopes)

    def resolve_write_scope(self, requested: str | None = None) -> WriteScope:
        """Choose an initialized scope, rejecting ambiguous implicit writes.

        :param requested: Explicit user or storage scope, or automatic selection.
        :return: One writable scope.
        """
        scopes = self.writable_scopes()
        if requested is not None:
            if requested not in scopes:
                raise ValueError(
                    f"Scope {requested!r} is unavailable. Initialize user overrides or select an existing storage."
                )
            return "user" if requested == "user" else "storage"
        if len(scopes) == 1:
            return scopes[0]
        if not scopes:
            raise ValueError(
                "No writable AppRC layer is active. Run setup first."
            )
        raise ValueError(
            "Both user and storage dotenv files are writable. Pass --scope user or --scope storage."
        )

    def plan_update(
        self,
        reference: str,
        raw_value: str,
        *,
        scope: WriteScope,
        storage: str | None = None,
    ) -> EnvFileEditPlan:
        """Validate a value and retain the exact original revision before editing.

        :param reference: Field name, dotted path, or complete environment key.
        :param raw_value: Proposed dotenv value.
        :param scope: Declared writable layer.
        :param storage: Optional storage being edited.
        :return: Source-preserving plan; applying it is a separate operation.
        """
        owner, spec = resolve_config_field_reference(
            self.schema.owners, reference
        )
        path = self.writable_path(scope, storage=storage, secret=spec.secret)
        if spec.secret:
            self._require_private_secret_edit(
                scope, owner.env_key(spec.name), storage=storage
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
            lock_roots=(self.paths.root, path.parent),
        )

    def plan_removal(
        self,
        reference: str,
        *,
        scope: WriteScope,
        storage: str | None = None,
    ) -> EnvFileEditPlan | None:
        """Plan removal of every active assignment for a field.

        :param reference: Registered field reference.
        :param scope: Writable layer.
        :param storage: Optional inspected storage.
        :return: Revision-checked plan, or ``None`` when already absent.
        """
        owner, spec = resolve_config_field_reference(
            self.schema.owners, reference
        )
        path = self.writable_path(scope, storage=storage, secret=spec.secret)
        if spec.secret:
            self._require_private_secret_edit(
                scope, owner.env_key(spec.name), storage=storage
            )
        plan = plan_env_file_value_removal(
            path=path,
            reference=reference,
            owners=self.schema.owners,
            layer_name=path.name,
            private=spec.secret,
        )
        return (
            None
            if plan is None
            else replace(plan, lock_roots=(self.paths.root, path.parent))
        )

    def _require_private_secret_edit(
        self, scope: WriteScope, env_key: str, *, storage: str | None
    ) -> None:
        """Avoid unsafe writes or revealing a legacy ordinary-file value."""
        regular = self.writable_path(scope, storage=storage)
        if env_key in parse_dotenv_file(regular, environment=self.environment):
            raise ValueError(
                f"{env_key} is still in {regular.name}. Run `config secrets migrate` first."
            )
        status = self.secret_status(scope, storage=storage)
        if not status.available:
            raise ValueError(status.issue or "Secret file is unavailable.")

    def apply_edit(self, plan: EnvFileEditPlan) -> EnvFileUpdate:
        """Apply a planned edit, rejecting changes made since inspection.

        :param plan: Validated plan produced by a management operation.
        :return: Written field and any duplicate-assignment warnings.
        """
        return apply_env_file_edit(plan)

    def preview_edit(
        self,
        plan: EnvFileEditPlan,
        *,
        storage: str | None = None,
    ) -> ConfigInspection:
        """Inspect a proposed edit with runtime precedence and explicit files.

        :param plan: Pending managed dotenv edit.
        :param storage: Optional storage being browsed.
        :return: Candidate effective values without changing files or selection.
        """
        resolved = self.inspect(storage=storage).resolved
        values = parse_dotenv_text(plan.text, environment=self.environment)
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

    @property
    def registry_path(self) -> Path:
        """Return the declared registry path without requiring it to exist."""
        self.schema.require_storage()
        return self.paths.apprc_toml

    def registry(self) -> StorageRegistry:
        """Read current persisted selection, returning an empty missing registry."""
        return storage_registry.load_storage_registry_or_empty(
            self.registry_path
        )

    def inspect_registry(self) -> StorageRegistryInspection:
        """Report missing, invalid, or stale registry data without creating files.

        :return: Registry readiness using the invocation's directory inputs.
        """
        return inspect_storage_registry(
            self.schema, proc_env=self._path_environment(allow_unready=True)
        )

    def register_storage(self, name: str, root: Path) -> StorageRegistry:
        """Register a root and initialize its fixed storage dotenv.

        :param name: New registry name.
        :param root: Directory to create or register.
        :return: Updated registry.
        """
        root = resolve_storage_root_path(root, base=self.paths.root)
        with managed_write_lock(self.paths.root, root):
            root_existed = root.exists()
            result = storage_registry.register_storage(
                name=name, root=root, path=self.registry_path
            )
            secret_path = AppFiles(self.schema).storage_secret_dotenv_path(
                result.storages[name].root
            )
            if root_existed:
                ensure_secret_file(secret_path)
            else:
                repair_secret_file_permissions(secret_path)
            return result

    def select_storage(self, name: str) -> StorageRegistry:
        """Persist the fallback used when an invocation has no selector.

        :param name: Existing registry name.
        :return: Updated registry; already resolved runtime objects are unchanged.
        """
        with managed_write_lock(self.paths.root):
            return storage_registry.select_storage(
                name=name, path=self.registry_path
            )

    def rename_storage(self, current_name: str, name: str) -> StorageRegistry:
        """Rename a registry entry without moving its data.

        :param current_name: Existing name.
        :param name: Replacement name.
        :return: Updated registry.
        """
        with managed_write_lock(self.paths.root):
            return storage_registry.rename_storage(
                current_name=current_name, name=name, path=self.registry_path
            )

    def repoint_storage(self, name: str, root: Path) -> StorageRegistry:
        """Associate a registered name with an existing initialized root.

        :param name: Existing name.
        :param root: Replacement directory; no files are moved.
        :return: Updated registry.
        """
        with managed_write_lock(self.paths.root):
            return storage_registry.repoint_storage(
                name=name, root=root, path=self.registry_path
            )

    def remove_storage(
        self, name: str, *, delete_content: bool = False
    ) -> StorageRegistry:
        """Unregister storage, optionally removing its directory after the registry write.

        :param name: Existing registry name.
        :param delete_content: Explicit request to delete the directory too.
        :return: Updated registry. A deletion failure raises after unregistering.
        """
        with managed_write_lock(
            self.paths.root, self.registry().selected(name).root
        ):
            root = self.registry().selected(name).root
            result = storage_registry.unregister_storage(
                name=name, path=self.registry_path
            )
            if delete_content and root.exists():
                shutil.rmtree(root)
            return result

    def remove_archive_record(self, name: str) -> StorageRegistry:
        """Forget an archive record while retaining its archive file.

        :param name: Archived registry name.
        :return: Updated registry.
        """
        with managed_write_lock(self.paths.root):
            return storage_registry.remove_archived_storage(
                name=name, path=self.registry_path
            )

    def move_storage(self, name: str, destination: Path) -> StorageMoveResult:
        """Move a registered directory using the existing preflight and rollback.

        :param name: Storage to move.
        :param destination: New or empty directory.
        :return: Completed filesystem and registry changes.
        """
        with managed_write_lock(
            self.paths.root, self.registry().selected(name).root, destination
        ):
            return move_storage(
                name=name, destination=destination, path=self.registry_path
            )

    def archive_storage(
        self,
        name: str,
        archive_path: Path,
        *,
        progress: Callable[[StorageArchiveProgress], None] | None = None,
    ) -> Path:
        """Create and record an archive, retaining the live directory.

        :param name: Registered storage to archive.
        :param archive_path: Archive destination.
        :param progress: Optional noninteractive progress callback.
        :return: Written archive path.
        """
        with managed_write_lock(
            self.paths.root, self.registry().selected(name).root
        ):
            root = self.registry().selected(name).root
            legacy = self.plan_secret_migration("storage", storage=name)
            if legacy.keys:
                raise ValueError(
                    "Move legacy storage secrets with `config secrets migrate --scope storage` before archiving."
                )
            result = archive_directory(
                source_root=root,
                archive_path=archive_path,
                progress=progress,
                excluded_names=(
                    AppFiles(self.schema).storage_secret_dotenv_path(root).name,
                ),
            )
            storage_registry.record_archived_storage(
                name=name,
                archive=result,
                source_root=root,
                path=self.registry_path,
            )
            return result

    def restore_storage(
        self,
        name: str,
        archive_path: Path,
        destination: Path,
        *,
        archived_name: str | None = None,
        replace_existing: bool = False,
        progress: Callable[[StorageArchiveProgress], None] | None = None,
    ) -> Path:
        """Extract storage and commit its registry entry with extraction rollback.

        :param name: Name for the restored storage.
        :param archive_path: Existing archive.
        :param destination: Directory receiving the contents.
        :param archived_name: Archive record to consume, if any.
        :param replace_existing: Whether explicitly approved replacement is allowed.
        :param progress: Optional progress callback.
        :return: Installed root.
        """

        def register(root: Path) -> None:
            """Commit before the extraction implementation discards its backup."""
            storage_registry.register_restored_storage(
                name=name,
                root=root,
                path=self.registry_path,
                archived_name=archived_name,
            )

        with managed_write_lock(self.paths.root, destination):
            result = extract_archive(
                archive_path=archive_path,
                destination_root=destination,
                replace_existing=replace_existing,
                progress=progress,
                after_install=register,
            )
            ensure_secret_file(
                AppFiles(self.schema).storage_secret_dotenv_path(result)
            )
            return result

    def plan_migration(
        self,
        *,
        storage_roots: tuple[Path, ...] = (),
        storage_resolution: StorageMigrationResolution | None = None,
    ) -> ConfigMigrationPlan:
        """Inspect released legacy locations without writing files.

        :param storage_roots: Additional storage roots to inspect.
        :param storage_resolution: Explicit mapping for ambiguous legacy selection.
        :return: Existing migration preflight result.
        """
        return build_config_migration_plan(
            self.schema,
            storage_roots=storage_roots,
            proc_env=self._path_environment(),
            storage_resolution=storage_resolution,
        )

    def apply_migration(
        self, plan: ConfigMigrationPlan
    ) -> ConfigMigrationResult:
        """Apply a reviewed legacy migration plan.

        :param plan: Successful migration preflight.
        :return: Migration changes.
        """
        with managed_write_lock(self.paths.root):
            return apply_config_migration(plan)

    def plan_purge(self) -> ConfigPurgePlan:
        """Inspect existing cleanup targets without deleting anything."""
        return build_config_purge_plan(
            self.schema,
            apprc_dir=AppFiles(self.schema)
            .paths(self._path_environment())
            .root,
        )

    def apply_purge(self, plan: ConfigPurgePlan) -> ConfigPurgeResult:
        """Delete only the managed targets enumerated by a reviewed purge plan.

        :param plan: Existing purge preflight result.
        :return: Removed and retained paths.
        """
        with managed_write_lock(
            plan.apprc_dir,
            *plan.external_storage_roots,
        ):
            return apply_config_purge(plan)
