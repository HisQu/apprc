"""Public AppRC application facade."""

from __future__ import annotations

# == Standard Library ========================
import dataclasses
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    TypeVar,
    cast,
    dataclass_transform,
)

# == 3rd Party ===============================
# == Internal ================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.env_config._validation import (
    validate_config_owner_inventory,
)
from apprc.definition.env_config.schema import ConfigOwner
from apprc.definition.maintenance import MaintenanceHandlers
from apprc.definition.installation import OperationContext
from apprc.definition.paths import AppPaths, Layout, PathKind, Paths
from apprc.definition.resolution import (
    BundleFieldSpec as _BundleFieldSpec,
)
from apprc.definition.resolution import (
    ImportedConfig,
    ResolveOptions,
    dependency_environment_exclusions,
)
from apprc.public._bundle_registration import (
    _build_bundle_init,
    _build_bundle_repr,
    _bundle_fields,
)
from apprc.public._config_registration import (
    _build_owner,
    _collect_field_declarations,
    _ensure_dataclass,
    _humanize_title,
    _is_env_config,
    _validate_config_class,
    _validate_python_only_registration,
)
from apprc.public._dependency_import import _prepare_dependency_config
from apprc.public.config import ConfigBase
from apprc.public.field import _FieldDeclaration
from apprc.runtime.resolution import ResolvedConfig, resolve_config
from apprc.services.installation import InstallationManager
from apprc.services.maintenance import MaintenanceManager
from apprc.services.manager import ConfigManager
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.app_home.layouts import resolve_app_paths
from apprc.user_files.app_home.ownership import ensure_owned_path

ConfigClassT = TypeVar("ConfigClassT", bound=type[ConfigBase])
ConfigInstanceT = TypeVar("ConfigInstanceT", bound=ConfigBase)
BundleClassT = TypeVar("BundleClassT", bound=type[object])


@dataclass(frozen=True, slots=True)
class RegisteredConfig:
    """Normalized public registration state for one config class.

    :param key: Stable config key used by the AppRC public API.
    :param config_type: Registered Python config class.
    :param title: Human-readable display title.
    :param rc_path: Runtime config path components.
    :param prefix: Required env prefix for env-backed config classes.
    :param declared_fields: Field declarations registered on this class.
    :param owner: Owner schema captured by this AppRC registration.
    """

    key: str
    config_type: type[ConfigBase]
    title: str
    rc_path: tuple[str, ...]
    prefix: str | None
    declared_fields: Mapping[str, _FieldDeclaration]
    owner: ConfigOwner | None = None


@dataclass(frozen=True, slots=True)
class _AppRCDeclaration:
    """Typed declarations preserved when registered configuration is rebuilt."""

    app_id: str
    display_name: str
    config_package: str | None
    command_name: str | None
    user_dotenv: UserDotenv | None
    paths: Paths
    layout: Layout | None
    bootstrap_env_prefix: str | None
    workspaces: Workspaces | None
    setup_next_step: str | None


class AppRC:
    """Public facade for one application's AppRC integration.

    Declare independent paths and optional preference/workspace capabilities,
    register sections through ``@MyRC.config(...)``, and capture inputs with
    :meth:`resolve`. Path inspection is read-only; :meth:`ensure_path` creates
    only the requested enabled location.
    """

    def __init__(
        self,
        *,
        app_id: str,
        config_package: str | None = None,
        display_name: str | None = None,
        command_name: str | None = None,
        user_dotenv: UserDotenv | None = None,
        paths: Paths = Paths(),
        layout: Layout | None = None,
        bootstrap_env_prefix: str | None = None,
        workspaces: Workspaces | None = None,
        setup_next_step: str | None = None,
    ) -> None:
        """Build an application declaration with optional writable features.

        :param app_id: Stable application identity.
        :param config_package: Package containing packaged config resources.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_id``.
        :param command_name: Executable name shown in generated instructions.
        :param user_dotenv: User dotenv declaration, or ``None`` to avoid that
            persistent layer.
        :param paths: Independently enabled configuration/data/cache/state paths.
        :param layout: Declared layout fallback, native when omitted.
        :param bootstrap_env_prefix: Optional layout/root/workspace key prefix.
        :param workspaces: Optional direct or registered workspace selection.
        :param setup_next_step: Optional command or instruction shown after
            successful explicit CLI setup.
        """
        self._declaration = _AppRCDeclaration(
            app_id=app_id,
            display_name=display_name or app_id,
            config_package=config_package,
            command_name=command_name,
            user_dotenv=user_dotenv,
            paths=paths,
            layout=layout,
            bootstrap_env_prefix=bootstrap_env_prefix,
            workspaces=workspaces,
            setup_next_step=setup_next_step,
        )
        self._registered_by_key: dict[str, RegisteredConfig] = {}
        self._registered_by_type: dict[type[ConfigBase], RegisteredConfig] = {}
        self._bundles: dict[type[object], tuple[_BundleFieldSpec, ...]] = {}
        self._imported_configs: list[ImportedConfig[Any]] = []
        self._env_key_index: dict[str, tuple[str, str]] = {}
        self._dependency_source_env_keys: set[str] = set()
        self._dependency_control_env_keys: set[str] = set()
        self._dependency_env_prefixes: set[str] = set()
        self._schema = self._build_schema(
            imported_configs=self._imported_configs
        )

    @property
    def schema(self) -> AppConfigSpec:
        """Return immutable declaration metadata for current registrations."""
        return self._schema

    def resolve(
        self,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> ResolvedConfig:
        """Capture configuration inputs without changing process state.

        :param options: Source selection and runtime requirements.
        :param environment: Interpolation and binding inputs, or the process environment.
        :return: Independent snapshot used to build registered configs.
        """
        return resolve_config(
            self.schema,
            registered_types=tuple(self._registered_by_type),
            bundles=self._bundles,
            imported_configs=tuple(self._imported_configs),
            options=options,
            environment=environment,
        )

    def manage(
        self,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> ConfigManager:
        """Capture inputs for setup, inspection, and managed-file operations.

        :param options: Invocation-local selection and path choices.
        :param environment: Explicit inputs, or a copy of the process environment.
        :return: Application-bound manager without prompts or writes.
        """
        return ConfigManager(
            self.schema,
            registered_types=tuple(self._registered_by_type),
            bundles=self._bundles,
            imported_configs=tuple(self._imported_configs),
            options=options,
            environment=environment,
        )

    def installation(
        self, *, environment: Mapping[str, str] | None = None
    ) -> InstallationManager:
        """Capture installation discovery independently of business settings.

        :param environment: Explicit discovery inputs, or current environment.
        :return: Read-only application-bound manager until mutation is requested.
        """
        return InstallationManager(self.schema, environment=environment)

    def paths(
        self,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> AppPaths:
        """Resolve enabled locations without creating or reading settings files.

        :param options: Invocation placement and explicit bootstrap files.
        :param environment: Captured environment, or the process environment.
        :return: Immutable paths with their original layout provenance.
        """
        excluded_keys, excluded_prefixes = dependency_environment_exclusions(
            tuple(self._imported_configs)
        )
        return resolve_app_paths(
            self.schema,
            options or ResolveOptions(),
            dict(os.environ if environment is None else environment),
            excluded_env_keys=excluded_keys,
            excluded_env_prefixes=excluded_prefixes,
        )

    def ensure_path(
        self,
        kind: PathKind,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        adopt: bool = False,
    ) -> Path:
        """Privately initialize one declared location and its ownership marker.

        :param kind: Enabled component or subordinate logs location.
        :param options: Invocation layout and bootstrap inputs.
        :param environment: Explicit environment, or the process environment.
        :param adopt: Explicitly accept an existing nonempty unowned directory.
        :return: Initialized directory.
        """
        return ensure_owned_path(
            self.schema,
            self.paths(options, environment=environment),
            kind,
            adopt=adopt,
        )

    def _resolve_with_paths(
        self,
        options: ResolveOptions,
        environment: Mapping[str, str],
        paths: AppPaths,
    ) -> ResolvedConfig:
        """Resolve settings while retaining an adapter's bootstrap snapshot."""
        return resolve_config(
            self.schema,
            registered_types=tuple(self._registered_by_type),
            bundles=self._bundles,
            imported_configs=tuple(self._imported_configs),
            options=options,
            environment=environment,
            app_paths=paths,
        )

    def _manage_with_paths(
        self,
        options: ResolveOptions,
        environment: Mapping[str, str],
        paths: AppPaths,
    ) -> ConfigManager:
        """Build a settings manager against captured placement and environment."""
        return ConfigManager(
            self.schema,
            registered_types=tuple(self._registered_by_type),
            bundles=self._bundles,
            imported_configs=tuple(self._imported_configs),
            options=options,
            environment=environment,
            app_paths=paths,
        )

    def workspaces(
        self,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> WorkspaceManager:
        """Return explicit workspace operations without changing payloads.

        :param options: Invocation workspace and bootstrap inputs.
        :param environment: Explicit environment, or the process environment.
        :return: Workspace manager bound to one captured path snapshot.
        """
        captured = dict(os.environ if environment is None else environment)
        return WorkspaceManager(
            self.schema,
            options=options,
            environment=captured,
            app_paths=self.paths(options, environment=captured),
        )

    def maintain(
        self,
        options: ResolveOptions | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        handlers: MaintenanceHandlers = MaintenanceHandlers(),
        context: OperationContext | None = None,
    ) -> MaintenanceManager:
        """Return resource operations bound to captured paths or pending authority.

        :param options: Invocation placement and bootstrap inputs.
        :param environment: Explicit environment, or the process environment.
        :param handlers: Explicit application-owned semantic operations.
        :param context: Exact pending operation authorization for staged mutations.
        :return: Manager bound to the captured paths and handlers.
        """
        captured = dict(os.environ if environment is None else environment)
        return MaintenanceManager(
            self.schema,
            options=options,
            environment=captured,
            handlers=handlers,
            operation_context=context,
            app_paths=(
                None
                if context is not None
                else self.paths(options, environment=captured)
            ),
        )

    def import_dependency_config(
        self,
        dependency: AppRC,
        config_type: type[ConfigInstanceT],
        *,
        key: str,
        prefix: str,
        fields: Mapping[str, dataclasses.Field[Any]],
        field_targets: Mapping[str, str] | None = None,
        title: str | None = None,
        rc_path: tuple[str, ...] | None = None,
        include_packaged_defaults: bool = False,
    ) -> ImportedConfig[ConfigInstanceT]:
        """Import one dependency section under parent-owned field names.

        The parent supplies a complete set of field declarations and may map
        several compatible dependency fields to the same parent field. Omitted
        dependency fields must have Python defaults and keep those defaults.
        Every mapped dependency field must be a dataclass field with
        ``init=True`` so parent values can be supplied during construction.
        This method records the dependency schema and adds its parent-owned
        fields to this AppRC. It does not load dependency user or workspace
        files, or dependency environment values. If the section requires a
        workspace, the parent must declare and select its own workspace before
        building the imported config.

        :param dependency: AppRC that registered ``config_type``.
        :param config_type: Dependency ``rc.Config`` section to import.
        :param key: Parent-owned owner key.
        :param prefix: Parent-owned environment prefix.
        :param fields: Parent-owned ``rc.field(...)`` declarations keyed by
            parent field name.
        :param field_targets: Dependency field to parent field mapping.
            Repeated parent field names declare aliases. Omitted dependency
            fields use their Python defaults and are not parent settings. If
            omitted, field names must match exactly.
        :param title: Parent-facing owner title, or a title derived from key.
        :param rc_path: Parent-owned config path, or ``(key,)``.
        :param include_packaged_defaults: Whether selected values from the
            dependency package's ``apprc.defaults.env`` may load below the
            parent's packaged defaults.
        :return: Immutable binding for building the imported section.
        :raises TypeError: If the dependency section or field declarations are
            invalid.
        :raises ValueError: If field mappings, secrets, prefixes, or names
            conflict.
        """
        if not isinstance(dependency, AppRC):
            raise TypeError("dependency must be an AppRC instance.")
        if not isinstance(config_type, type) or not _is_env_config(config_type):
            raise TypeError(
                "import_dependency_config(...) requires an rc.Config section."
            )
        registered = dependency._registered_by_type.get(config_type)
        if registered is None or registered.owner is None:
            raise ValueError(
                f"{config_type.__name__} is not an env-backed config section "
                "registered with the dependency AppRC."
            )
        dependency_env_prefixes = tuple(
            dict.fromkeys(
                item.owner.env_prefix
                for item in dependency._registered_by_type.values()
                if item.owner is not None
            )
        )
        prepared = _prepare_dependency_config(
            config_type=cast(type[ConfigInstanceT], config_type),
            dependency_schema=dependency.schema,
            dependency_owner=registered.owner,
            dependency_env_prefixes=dependency_env_prefixes,
            parent_schema=self.schema,
            parent_registered_keys=self._registered_by_key.keys(),
            parent_registered_types=self._registered_by_type.keys(),
            parent_env_keys=self._env_key_index.keys(),
            parent_source_env_keys=self._dependency_source_env_keys,
            parent_control_env_keys=self._dependency_control_env_keys,
            parent_dependency_env_prefixes=self._dependency_env_prefixes,
            key=key,
            prefix=prefix,
            fields=fields,
            field_targets=field_targets,
            title=title,
            rc_path=rc_path,
            include_packaged_defaults=include_packaged_defaults,
        )
        binding = prepared.binding
        candidate_schema = self._build_schema(
            imported_configs=(*self._imported_configs, binding)
        )
        self._env_key_index.update(prepared.env_key_entries)
        self._dependency_source_env_keys.update(prepared.source_env_keys)
        self._dependency_control_env_keys.update(
            binding.dependency_control_env_keys
        )
        self._dependency_env_prefixes.update(binding.dependency_env_prefixes)
        self._imported_configs.append(binding)
        self._schema = candidate_schema
        return binding

    @dataclass_transform()
    def config(
        self,
        key: str,
        *,
        prefix: str | None = None,
        title: str | None = None,
        rc_path: tuple[str, ...] | None = None,
        requires_workspace: bool = False,
    ) -> Callable[[ConfigClassT], ConfigClassT]:
        """Return the public config registration decorator.

        :param key: Stable config key.
        :param prefix: Required full env prefix for ``rc.Config`` subclasses.
        :param title: Optional display title. AppRC derives one from ``key``
            when omitted.
        :param rc_path: Optional runtime config path. Defaults to ``(key,)``.
        :param requires_workspace: Skip inspection until a workspace is selected.
            Requires a Workspaces declaration and ``rc.Config``.
        :return: Decorator that registers a ``rc.Config`` or ``rc.ConfigBase``
            subclass.
        :raises TypeError: If ``key`` is missing or not a string.
        :raises ValueError: If ``key`` is empty.
        """
        if not isinstance(key, str):
            raise TypeError(
                "@MyRC.config(...) requires a config key string, for example "
                '@MyRC.config("llm", prefix="HAIU_LLM_").'
            )
        if not key:
            raise ValueError("@MyRC.config(...) requires a non-empty key.")

        def decorator(config_type: ConfigClassT) -> ConfigClassT:
            """Register one public config class."""
            return self._register_config(
                config_type,
                key=key,
                prefix=prefix,
                title=title,
                rc_path=rc_path,
                requires_workspace=requires_workspace,
            )

        return decorator

    def bundle(self, bundle_type: BundleClassT) -> BundleClassT:
        """Register an eager aggregate runtime config class.

        :param bundle_type: Keyword-only dataclass whose fields reference
            registered AppRC config classes.
        :return: The same dataclass with eager construction and safe repr.
        :raises TypeError: If the class lacks a typed dataclass constructor or
            a field refers to an unregistered config class.
        """
        if "__dataclass_fields__" not in bundle_type.__dict__:
            raise TypeError(
                "@MyRC.bundle requires an explicit keyword-only dataclass. "
                "Place @dataclass(kw_only=True) directly below "
                "@MyRC.bundle and give each eager child a default_factory."
            )
        resolved_bundle = bundle_type
        bundle_fields = _bundle_fields(
            resolved_bundle,
            registered_by_type=self._registered_by_type,
            imported_configs=self._imported_configs,
        )
        post_init = getattr(resolved_bundle, "__post_init__", None)
        setattr(
            resolved_bundle,
            "__init__",
            _build_bundle_init(
                resolved_bundle,
                bundle_fields,
                post_init,
                registered_by_type=self._registered_by_type,
            ),
        )
        setattr(
            resolved_bundle,
            "__repr__",
            _build_bundle_repr(resolved_bundle, bundle_fields),
        )
        self._bundles[resolved_bundle] = tuple(bundle_fields.values())
        return cast(BundleClassT, resolved_bundle)

    def _build_schema(
        self, *, imported_configs: Iterable[ImportedConfig[Any]]
    ) -> AppConfigSpec:
        """Build validated metadata from direct and explicit imported configs."""
        envs = tuple(
            item.config_type
            for item in self._registered_by_key.values()
            if _is_env_config(item.config_type)
        )
        declaration = self._declaration
        return AppConfigSpec(
            app_id=declaration.app_id,
            display_name=declaration.display_name,
            config_package=declaration.config_package,
            envs=envs,
            additional_owners=tuple(
                item.parent_owner for item in imported_configs
            ),
            user_dotenv=declaration.user_dotenv,
            paths=declaration.paths,
            layout=declaration.layout,
            bootstrap_env_prefix=declaration.bootstrap_env_prefix,
            workspaces=declaration.workspaces,
            setup_next_step=declaration.setup_next_step,
            command_name=declaration.command_name,
        )

    def _register_config(
        self,
        config_type: ConfigClassT,
        *,
        key: str,
        prefix: str | None,
        title: str | None,
        rc_path: tuple[str, ...] | None,
        requires_workspace: bool,
    ) -> ConfigClassT:
        """Validate and register one config class."""
        _validate_config_class(config_type)
        existing = self._registered_by_key.get(key)
        if existing is not None:
            if existing.config_type is config_type:
                return config_type
            raise ValueError(
                f'AppRC config key "{key}" is already registered by '
                f"{existing.config_type.__name__}."
            )
        if any(item.parent_owner.key == key for item in self._imported_configs):
            raise ValueError(f'AppRC owner key "{key}" is already in use.')

        resolved_type = _ensure_dataclass(config_type)
        if requires_workspace and self.schema.workspaces is None:
            raise ValueError(
                "requires_workspace=True requires workspaces=rc.Workspaces()."
            )
        if requires_workspace and not _is_env_config(resolved_type):
            raise ValueError(
                "requires_workspace=True requires an rc.Config section."
            )
        resolved_title = title or _humanize_title(key)
        resolved_rc_path = rc_path or (key,)
        declared_fields = _collect_field_declarations(resolved_type)

        owner: ConfigOwner | None = None
        if _is_env_config(resolved_type):
            owner = _build_owner(
                resolved_type,
                key=key,
                title=resolved_title,
                prefix=prefix,
                rc_path=resolved_rc_path,
                declared_fields=declared_fields,
                requires_workspace=requires_workspace,
            )
            self._validate_unique_env_keys(resolved_type, declared_fields)
            validate_config_owner_inventory((*self.schema.owners, owner))
            setattr(resolved_type, "config_owner", owner)
        else:
            _validate_python_only_registration(
                resolved_type,
                prefix=prefix,
                declared_fields=declared_fields,
            )

        registered = RegisteredConfig(
            key=key,
            config_type=resolved_type,
            title=resolved_title,
            rc_path=resolved_rc_path,
            prefix=prefix,
            declared_fields=declared_fields,
            owner=owner,
        )
        self._registered_by_key[key] = registered
        self._registered_by_type[resolved_type] = registered
        for field_name, spec in declared_fields.items():
            self._env_key_index[spec.env_key] = (
                resolved_type.__name__,
                field_name,
            )
        self._schema = self._build_schema(
            imported_configs=self._imported_configs
        )
        return cast(ConfigClassT, resolved_type)

    def _validate_unique_env_keys(
        self,
        config_type: type[ConfigBase],
        declared_fields: Mapping[str, _FieldDeclaration],
    ) -> None:
        """Reject env keys that another registered config already owns."""
        for field_name, spec in declared_fields.items():
            if (
                spec.env_key in self._dependency_source_env_keys
                or spec.env_key in self._dependency_control_env_keys
                or any(
                    spec.env_key.startswith(prefix)
                    for prefix in self._dependency_env_prefixes
                )
            ):
                raise ValueError(
                    f"Env key {spec.env_key} belongs to an imported dependency "
                    "section and cannot also be parent-owned."
                )
            existing = self._env_key_index.get(spec.env_key)
            current = (config_type.__name__, field_name)
            if existing is not None and existing != current:
                existing_class, existing_field = existing
                raise ValueError(
                    f"Env key {spec.env_key} is used by both "
                    f"{existing_class}.{existing_field} and "
                    f"{config_type.__name__}.{field_name}. Each AppRC field "
                    "must use a unique env key."
                )


__all__ = [
    "AppRC",
    "RegisteredConfig",
]
