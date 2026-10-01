"""Resolve application inputs without writing files or process state."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, cast

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.provenance import ConfigOriginState, ShellProvenanceOrigin
from apprc.definition.resolution import (
    BundleFieldSpec,
    ConfigSource,
    ImportedConfig,
    ResolveOptions,
    filter_dependency_environment,
)
from apprc.user_files.env_files.layers import (
    defaults_dotenv_resource,
    read_explicit_env_files,
)
from apprc.runtime._selection import selection_env
from apprc.runtime.config.config import Config
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    AppRCDirectoryPaths,
)
from apprc.user_files.env_files._parsing import (
    parse_dotenv_file,
    parse_dotenv_text,
)
from apprc.user_files.storage_roots._loading import (
    load_optional_runtime_storage_registry,
)
from apprc.user_files.storage_roots.readiness import (
    validate_runtime_storage_root,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelection,
    StorageSelectorError,
    missing_storage_selector_error,
    resolve_active_storage_selection,
    select_storage_selector,
    storage_selector_is_path_like,
)

_EXPORT_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class ResolvedLayer:
    """One parsed layer retained for inspection and provenance.

    :param origin: Source category.
    :param source: Immutable assignments and their origin records.
    :param path: Durable filesystem path, if any.
    :param resource: Package resource identity without temporary extraction paths.
    """

    origin: ShellProvenanceOrigin
    source: ConfigSource = field(repr=False)
    path: Path | None = None
    resource: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedConfig:
    """An independent snapshot of inputs and declaration registrations.

    :param schema: Declaration at resolution time.
    :param options: Invocation choices.
    :param source: Effective values and provenance.
    :param layers: Sources in increasing precedence order.
    :param paths: Managed paths, when a capability needs them.
    :param selection: Validated active storage, when selected.
    :param storage_count: Number of registry entries.
    :param registered_types: Section classes known at resolution time.
    :param bundles: Registered bundle construction rules.
    :param issues: Source and storage findings retained only during inspection.
    :param storage_issues: Storage-specific findings for recovery interfaces.
    """

    schema: AppConfigSpec
    options: ResolveOptions
    source: ConfigSource = field(repr=False)
    layers: tuple[ResolvedLayer, ...]
    paths: AppRCDirectoryPaths | None
    selection: StorageSelection | None
    storage_count: int
    registered_types: tuple[type[object], ...] = field(repr=False)
    bundles: Mapping[type[object], tuple[BundleFieldSpec, ...]] = field(
        repr=False
    )
    issues: tuple[str, ...] = ()
    storage_issues: tuple[str, ...] = ()
    imported_configs: tuple[ImportedConfig[object], ...] = field(
        default=(), repr=False
    )

    def __post_init__(self) -> None:
        """Freeze bundle registrations independently of the application."""
        object.__setattr__(
            self, "bundles", MappingProxyType(dict(self.bundles))
        )
        object.__setattr__(
            self, "imported_configs", tuple(self.imported_configs)
        )

    @property
    def values(self) -> Mapping[str, str]:
        """Return effective raw values; callers must redact secrets for display."""
        return self.source.values

    @property
    def _has_valid_storage_selection(self) -> bool:
        """Whether runtime code can use the selected storage root.

        Inspection may retain an invalid candidate selection so repair tools
        can show its root and associated storage name. Such a candidate is not
        usable until storage validation completes without issues.

        :return: True when a selected storage root passed validation.
        """
        return self.selection is not None and not self.storage_issues

    def __repr__(self) -> str:
        """Describe the snapshot without printing configuration values."""
        return f"ResolvedConfig(app_id={self.schema.app_id!r}, layers={len(self.layers)})"

    def require_registered(self, config_type: type[object]) -> None:
        """Reject types absent from this declaration snapshot.

        :param config_type: Requested section or bundle.
        :return: None.
        """
        if (
            config_type not in self.registered_types
            and config_type not in self.bundles
            and not any(
                config_type in (item.config_type, item.runtime_config_type)
                for item in self.imported_configs
            )
        ):
            raise ValueError(
                f"{config_type.__name__} was not registered when this configuration "
                "was resolved. Register it with this AppRC and resolve again."
            )

    def build[T](
        self,
        config_type: type[T] | ImportedConfig[T],
        **overrides: Any,
    ) -> T:
        """Construct a registered section or bundle using this source snapshot.

        Ordinary constructors and post-init hooks run once. A custom factory
        for an environment-backed bundle child must be replaced by an explicitly
        injected child because its environment reads cannot be controlled here.

        :param config_type: Registered section or bundle class.
        :param overrides: Explicit constructor values or bundle children.
        :return: A newly constructed configuration object.
        """
        if isinstance(config_type, ImportedConfig):
            imported = self._require_imported_config(config_type)
            if (
                imported.parent_owner.requires_storage
                and not self._has_valid_storage_selection
            ):
                raise ValueError(
                    f"{imported.parent_owner.title} requires a valid storage "
                    "selection in the parent resolution."
                )
            if (
                "_apprc_source" in overrides
                or "_apprc_owner_override" in overrides
            ):
                raise TypeError("AppRC resolution state is reserved.")
            runtime_type = imported.runtime_config_type
            assert runtime_type is not None
            runtime_config_type = cast(Any, runtime_type)
            instance = runtime_config_type(
                _apprc_source=self.source,
                _apprc_owner_override=imported.runtime_owner,
                **overrides,
            )
            object.__setattr__(
                instance,
                "_apprc_imported_field_names",
                frozenset(imported.field_targets),
            )
            object.__setattr__(instance, "_apprc_imported_binding", imported)
            return cast(T, instance)
        self.require_registered(config_type)
        imported = self._imported_for_type(config_type)
        if imported is not None:
            return cast(T, self.build(imported, **overrides))
        if "_apprc_source" in overrides or "_apprc_owner_override" in overrides:
            raise TypeError("AppRC resolution state is reserved.")
        if issubclass(config_type, Config):
            runtime_config_type = cast(Any, config_type)
            return cast(
                T,
                runtime_config_type(_apprc_source=self.source, **overrides),
            )
        if config_type in self.bundles:
            for child in self.bundles[config_type]:
                if not child.init or child.name in overrides:
                    continue
                if child.imported_config is not None:
                    if child.default_factory is not child.config_type:
                        raise TypeError(
                            f"Inject {child.name!r} explicitly: its custom "
                            "factory cannot receive the resolved configuration "
                            "source."
                        )
                    overrides[child.name] = self.build(child.imported_config)
                    continue
                if issubclass(child.config_type, Config):
                    if child.default_factory is not child.config_type:
                        raise TypeError(
                            f"Inject {child.name!r} explicitly: its custom factory "
                            "cannot receive the resolved configuration source."
                        )
                    overrides[child.name] = self.build(child.config_type)
        return config_type(**overrides)

    def _require_imported_config[T](
        self,
        imported_config: ImportedConfig[T],
    ) -> ImportedConfig[T]:
        """Require a binding captured by this exact resolution."""
        if not any(item is imported_config for item in self.imported_configs):
            raise ValueError(
                "Imported config binding was not registered when this "
                "configuration was resolved. Resolve the parent AppRC again."
            )
        return imported_config

    def _imported_for_type[T](
        self,
        config_type: type[T],
    ) -> ImportedConfig[T] | None:
        """Find a unique imported binding for its dependency config class."""
        candidates = [
            item
            for item in self.imported_configs
            if config_type in (item.config_type, item.runtime_config_type)
        ]
        if len(candidates) > 1:
            raise ValueError(
                f"{config_type.__name__} has multiple imported bindings. "
                "Build it with the desired ImportedConfig handle."
            )
        return cast(
            ImportedConfig[T] | None,
            candidates[0] if candidates else None,
        )

    def export_environment(self) -> None:
        """Export effective file assignments and the selected storage path.

        This explicitly changes the current process for dependencies that read
        environment variables. It neither removes unrelated keys nor changes
        provenance on already constructed objects.

        :return: None.
        """
        keys = {
            key
            for layer in self.layers
            if layer.origin != "shell_export_variable"
            for key in layer.source.values
        }
        assignments = {key: self.source.values[key] for key in keys}
        for key, value in assignments.items():
            if not key or "=" in key or "\0" in key or "\0" in value:
                raise ValueError(f"Invalid environment assignment for {key!r}.")
        with _EXPORT_LOCK:
            os.environ.update(assignments)


def resolve_config(
    schema: AppConfigSpec,
    *,
    registered_types: tuple[type[object], ...],
    bundles: Mapping[type[object], tuple[BundleFieldSpec, ...]],
    imported_configs: tuple[ImportedConfig[object], ...] = (),
    options: ResolveOptions | None = None,
    environment: Mapping[str, str] | None = None,
    allow_unready: bool = False,
    include_storage: bool = True,
) -> ResolvedConfig:
    """Capture inputs once and resolve every layer without external writes.

    :param schema: Registered declaration metadata.
    :param registered_types: Section registration snapshot.
    :param bundles: Bundle registration snapshot.
    :param imported_configs: Parent-owned dependency bindings captured by the
        declaration.
    :param options: Invocation policy, or defaults.
    :param environment: Explicit environment snapshot; ``None`` captures the process.
    :param allow_unready: Retain storage readiness failures for management inspection.
    :param include_storage: Whether an inspection includes a storage layer.
    :return: Immutable resolved inputs ready to build runtime objects.
    """
    options = options or ResolveOptions()
    original = filter_dependency_environment(
        dict(os.environ if environment is None else environment),
        imported_configs,
    )
    if (
        options.storage is not None or options.storage_required
    ) and not schema.uses_storage():
        raise StorageSelectorError(
            "Storage options require storage=rc.Storage()."
        )
    if options.apprc_dir is not None and not schema.uses_managed_files():
        raise ValueError("apprc_dir requires a managed-file capability.")
    issues: list[str] = []
    try:
        _, explicit_layers, explicit_values = read_explicit_env_files(
            options.env_files, environment=original
        )
    except (OSError, ValueError) as exc:
        if not allow_unready:
            raise
        issues.append(str(exc))
        explicit_layers, explicit_values = (), {}
    explicit_values = filter_dependency_environment(
        explicit_values, imported_configs
    )
    selector_env = selection_env(
        original_env=original,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=options.env_file_overrides_os_environ,
    )
    if options.apprc_dir is not None:
        selector_env[schema.apprc_dir_env_key] = str(options.apprc_dir)
    paths = (
        AppFiles(schema).paths(selector_env)
        if schema.uses_managed_files()
        else None
    )
    registry = None
    selection = None
    storage_issues: list[str] = []
    try:
        if schema.uses_storage() and include_storage:
            assert paths is not None
            key = schema.require_storage_selector_env_key()
            try:
                registry = load_optional_runtime_storage_registry(
                    schema, proc_env=selector_env
                )
            except (AppRCDirectoryError, ValueError):
                selector = select_storage_selector(
                    storage=options.storage,
                    original_env=original,
                    explicit_values=explicit_values,
                    env_file_overrides_os_environ=options.env_file_overrides_os_environ,
                    storage_selector_env_key=key,
                    selected_storage=None,
                )
                if selector is None or not storage_selector_is_path_like(
                    selector[1]
                ):
                    raise
            selection = resolve_active_storage_selection(
                registry=registry,
                apprc_toml_path=paths.apprc_toml,
                storage=options.storage,
                storage_selector_env_key=key,
                original_env=original,
                explicit_values=explicit_values,
                env_file_overrides_os_environ=options.env_file_overrides_os_environ,
            )
            if selection is None and options.storage_required:
                raise missing_storage_selector_error(key)
            if selection is not None:
                validate_runtime_storage_root(
                    spec=schema,
                    storage_root=selection.root,
                    storage_name=selection.storage_name,
                    param_hint=selection.source,
                )
    except (OSError, ValueError) as exc:
        if not allow_unready:
            raise
        issues.append(str(exc))
        storage_issues.append(str(exc))
    layers: list[ResolvedLayer] = []

    def add_layer(
        values: Mapping[str, str],
        origin: ShellProvenanceOrigin,
        *,
        path: Path | None = None,
        resource: tuple[str, str] | None = None,
    ) -> None:
        """Record each input layer once for both inspection and binding."""
        parent_values = filter_dependency_environment(values, imported_configs)
        layers.append(
            ResolvedLayer(
                origin,
                ConfigSource(
                    parent_values,
                    {
                        key: ConfigOriginState(
                            origin, env_key=key, path=path, resource=resource
                        )
                        for key in parent_values
                    },
                ),
                path,
                resource,
            )
        )

    def read_layer(path: Path, origin: ShellProvenanceOrigin) -> None:
        """Keep an unreadable managed layer visible during repair inspection."""
        try:
            values = parse_dotenv_file(path, environment=original)
        except (OSError, ValueError) as exc:
            if not allow_unready:
                raise
            issues.append(f"Could not read {path}: {exc}")
            values = {}
        add_layer(values, origin, path=path)

    def read_secret_layer(path: Path, origin: ShellProvenanceOrigin) -> None:
        """Read only declared secret fields from a companion file."""
        try:
            parsed = parse_dotenv_file(path, environment=original)
        except (OSError, ValueError) as exc:
            if not allow_unready:
                raise
            issues.append(f"Could not read {path}: {exc}")
            parsed = {}
        secret_keys = {
            owner.env_key(spec.name)
            for owner in schema.owners
            for spec in owner.fields
            if spec.secret
        }
        add_layer(
            {key: value for key, value in parsed.items() if key in secret_keys},
            origin,
            path=path,
        )

    if options.load_dotenv_layers:
        for imported in imported_configs:
            if not imported.include_packaged_defaults:
                continue
            assert imported.config_package is not None
            try:
                dependency_defaults = files(imported.config_package).joinpath(
                    schema.defaults_dotenv_filename
                )
                if not dependency_defaults.is_file():
                    continue
                dependency_values = parse_dotenv_text(
                    dependency_defaults.read_text(encoding="utf-8"),
                    environment=original,
                )
                parent_values: dict[str, str] = {}
                for (
                    dependency_field,
                    parent_field,
                ) in imported.field_targets.items():
                    dependency_key = imported.dependency_owner.env_key(
                        dependency_field
                    )
                    if dependency_key not in dependency_values:
                        continue
                    parent_key = imported.parent_owner.env_key(parent_field)
                    value = dependency_values[dependency_key]
                    previous = parent_values.get(parent_key)
                    if previous is not None and previous != value:
                        raise ValueError(
                            "Conflicting dependency packaged defaults map to "
                            f"parent field {parent_field!r}."
                        )
                    parent_values[parent_key] = value
                add_layer(
                    parent_values,
                    "shell_dotenv_defaults",
                    path=(
                        dependency_defaults
                        if isinstance(dependency_defaults, Path)
                        else None
                    ),
                    resource=(
                        imported.config_package,
                        schema.defaults_dotenv_filename,
                    ),
                )
            except (ImportError, OSError, ValueError, TypeError) as exc:
                if not allow_unready:
                    raise
                issues.append(
                    "Could not read dependency packaged defaults from "
                    f"{imported.config_package!r}: {exc}"
                )
        try:
            defaults = defaults_dotenv_resource(schema)
            if defaults is not None and defaults.is_file():
                assert schema.config_package is not None
                add_layer(
                    parse_dotenv_text(
                        defaults.read_text(encoding="utf-8"),
                        environment=original,
                    ),
                    "shell_dotenv_defaults",
                    path=defaults if isinstance(defaults, Path) else None,
                    resource=(
                        schema.config_package,
                        schema.defaults_dotenv_filename,
                    ),
                )
        except (ImportError, OSError, ValueError, TypeError) as exc:
            if not allow_unready:
                raise
            issues.append(
                f"Could not read packaged defaults from {schema.config_package!r}: {exc}"
            )
        if paths is not None and schema.uses_user_dotenv():
            read_layer(paths.user_dotenv, "shell_dotenv_user")
            read_secret_layer(
                AppFiles(schema).user_secret_dotenv_path(selector_env),
                "shell_dotenv_user",
            )
        if selection is not None:
            read_layer(
                AppFiles(schema).storage_dotenv_path(selection.root),
                "shell_dotenv_storage",
            )
            read_secret_layer(
                AppFiles(schema).storage_secret_dotenv_path(selection.root),
                "shell_dotenv_storage",
            )
    if options.env_file_overrides_os_environ:
        add_layer(original, "shell_export_variable")
    if options.load_dotenv_layers:
        for layer in explicit_layers:
            add_layer(layer.values, "shell_dotenv_explicit", path=layer.path)
    if not options.env_file_overrides_os_environ:
        add_layer(original, "shell_export_variable")
    if selection is not None:
        add_layer(
            {schema.require_storage_selector_env_key(): str(selection.root)},
            "shell_storage_selector",
        )
    return ResolvedConfig(
        schema,
        options,
        merge_layers(tuple(layers)),
        tuple(layers),
        paths,
        selection,
        len(registry.storages) if registry is not None else 0,
        registered_types,
        bundles,
        tuple(issues),
        tuple(storage_issues),
        imported_configs,
    )


def merge_layers(layers: tuple[ResolvedLayer, ...]) -> ConfigSource:
    """Merge ordered inputs for both runtime loading and edit previews.

    :param layers: Sources in increasing precedence order.
    :return: Immutable effective assignments and their winning origins.
    """
    values: dict[str, str] = {}
    origins: dict[str, ConfigOriginState] = {}
    for layer in layers:
        values.update(layer.source.values)
        origins.update(layer.source.origins)
    return ConfigSource(values, origins)
