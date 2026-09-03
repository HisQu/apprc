"""Public AppRC application facade."""

# == Standard Library ========================
import dataclasses
import logging
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    NoReturn,
    TypeGuard,
    TypeVar,
    cast,
    get_origin,
    get_type_hints,
)

# == 3rd Party ===============================
import typer

# == Internal ================================
import apprc.utils as ut
from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.spec import (
    DEFAULT_APP_ENV_FILENAME,
    DEFAULT_APPRC_TOML_FILENAME,
    DEFAULT_DEFAULTS_ENV_FILENAME,
    LEGACY_APP_ENV_FILENAME,
    LEGACY_DEFAULTS_ENV_FILENAME,
    LEGACY_STORAGE_ENV_FILENAME,
    AppConfigSpec,
)
from apprc.definition.app_config.storage import Storage
from apprc.definition.env_config._validation import validate_config_owner
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.interfaces.cli.mount import mount_config_cli
from apprc.public.config import Config, ConfigBase
from apprc.public.field import (
    PUBLIC_FIELD_METADATA_KEY,
    PublicFieldSpec,
)
from apprc.runtime._bootstrap_state import BootstrapState
from apprc.runtime.result import BootstrapLogger, EnvBootstrapResult

ConfigClassT = TypeVar("ConfigClassT", bound=type[ConfigBase])
BundleClassT = TypeVar("BundleClassT", bound=type[object])

LOG = logging.getLogger("apprc")


@dataclass(frozen=True, slots=True)
class RegisteredConfig:
    """Normalized public registration state for one config class.

    :param key: Stable config key used by the AppRC public API.
    :param config_type: Registered Python config class.
    :param title: Human-readable display title.
    :param rc_path: Runtime config path components.
    :param prefix: Required env prefix for env-backed config classes.
    :param env_fields: Public field markers declared on this class.
    """

    key: str
    config_type: type[ConfigBase]
    title: str
    rc_path: tuple[str, ...]
    prefix: str | None
    env_fields: Mapping[str, PublicFieldSpec]


@dataclass(frozen=True, slots=True)
class _BundleFieldSpec:
    """Normalized bundle field registration.

    :param name: Attribute name on the bundle class.
    :param config_type: Registered config type expected for the field.
    :param init: Whether constructor injection and eager construction apply.
    """

    name: str
    config_type: type[ConfigBase]
    init: bool


@dataclass(frozen=True, slots=True)
class _AppRCDeclaration:
    """Typed values shared by every rebuild of one public facade.

    :param app_name: Stable application name.
    :param display_name: Human-readable application name.
    :param config_package: Package containing managed defaults.
    :param command_name: Executable name used in guidance.
    :param storage: Optional persistent-storage declaration.
    :param defaults_env_filename: Packaged defaults basename.
    :param app_env_filename: Per-user app dotenv basename.
    :param apprc_toml_filename: AppRC TOML basename.
    """

    app_name: str
    display_name: str
    config_package: str
    command_name: str | None
    storage: Storage | None
    defaults_env_filename: str
    app_env_filename: str
    apprc_toml_filename: str


class AppRC:
    """Public facade for one application's AppRC integration.

    App authors create one ``AppRC`` object, add :class:`Storage` when the app
    writes data outside its config home, register config classes through
    ``@MyRC.config(...)``, and mount runtime behavior with :meth:`mount_cli` or
    :meth:`bootstrap`.
    """

    def __init__(
        self,
        *,
        app_name: str,
        config_package: str,
        display_name: str | None = None,
        command_name: str | None = None,
        storage: Storage | None = None,
        defaults_env_filename: str = DEFAULT_DEFAULTS_ENV_FILENAME,
        app_env_filename: str = DEFAULT_APP_ENV_FILENAME,
        apprc_toml_filename: str = DEFAULT_APPRC_TOML_FILENAME,
        _legacy_mode: str | None = None,
        _legacy_kit_kwargs: Mapping[str, object] | None = None,
    ) -> None:
        """Build an application declaration with optional storage.

        :param app_name: Lowercase application name.
        :param config_package: Package containing packaged config resources.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_name``.
        :param command_name: Executable name shown in generated instructions.
        :param storage: Storage declaration, or ``None`` for config-only apps.
        :param defaults_env_filename: Packaged defaults dotenv filename.
        :param app_env_filename: Per-user app dotenv filename.
        :param apprc_toml_filename: AppRC TOML filename in the config home.
        """
        self._declaration = _AppRCDeclaration(
            app_name=app_name,
            display_name=display_name or app_name,
            config_package=config_package,
            command_name=command_name,
            storage=storage,
            defaults_env_filename=defaults_env_filename,
            app_env_filename=app_env_filename,
            apprc_toml_filename=apprc_toml_filename,
        )
        self._legacy_kit_kwargs = (
            self._build_legacy_kit_kwargs(
                declaration=self._declaration,
                legacy_mode=_legacy_mode,
                legacy_kit_kwargs=_legacy_kit_kwargs or {},
            )
            if _legacy_mode is not None
            else None
        )
        self._registered_by_key: dict[str, RegisteredConfig] = {}
        self._registered_by_type: dict[type[ConfigBase], RegisteredConfig] = {}
        self._env_key_index: dict[str, tuple[str, str]] = {}
        self._bootstrap_state = BootstrapState()
        self._kit = self._build_kit()

    @classmethod
    def env_only(
        cls,
        *,
        app_name: str,
        display_name: str | None = None,
        config_package: str,
        **kwargs: object,
    ) -> "AppRC":
        """Create an env/package/shell-only AppRC integration.

        :param app_name: Lowercase application name.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_name``.
        :param config_package: Package containing packaged config resources.
        :param kwargs: Lower-level AppRC kit constructor options.
        :return: Public AppRC facade.
        """
        cls._warn_legacy_constructor("env_only")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            _legacy_mode="env_only",
            _legacy_kit_kwargs=kwargs,
        )

    @classmethod
    def storage_only(
        cls,
        *,
        app_name: str,
        display_name: str | None = None,
        config_package: str,
        storage_env_key: str | None = None,
        **kwargs: object,
    ) -> "AppRC":
        """Create an integration that requires one active storage selector.

        :param app_name: Lowercase application name.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_name``.
        :param config_package: Package containing packaged config resources.
        :param storage_env_key: Optional storage selector env key.
        :param kwargs: Lower-level AppRC kit constructor options.
        :return: Public AppRC facade.
        """
        cls._warn_legacy_constructor("storage_only")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            storage=Storage(
                env_key=storage_env_key,
                prompt_on_first_run=False,
                env_filename=LEGACY_STORAGE_ENV_FILENAME,
            ),
            _legacy_mode="storage_only",
            _legacy_kit_kwargs=kwargs,
        )

    @classmethod
    def app_wide_config(
        cls,
        *,
        app_name: str,
        display_name: str | None = None,
        config_package: str,
        **kwargs: object,
    ) -> "AppRC":
        """Create an integration centered on app-wide config.

        :param app_name: Lowercase application name.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_name``.
        :param config_package: Package containing packaged config resources.
        :param kwargs: Lower-level AppRC kit constructor options.
        :return: Public AppRC facade.
        """
        cls._warn_legacy_constructor("app_wide_config")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            _legacy_mode="app_wide_config",
            _legacy_kit_kwargs=kwargs,
        )

    @classmethod
    def app_wide_storage(
        cls,
        *,
        app_name: str,
        display_name: str | None = None,
        config_package: str,
        storage_env_key: str | None = None,
        **kwargs: object,
    ) -> "AppRC":
        """Create an integration with app-wide config and storage roots.

        :param app_name: Lowercase application name.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_name``.
        :param config_package: Package containing packaged config resources.
        :param storage_env_key: Optional storage selector env key.
        :param kwargs: Lower-level AppRC kit constructor options.
        :return: Public AppRC facade.
        """
        cls._warn_legacy_constructor("app_wide_storage")
        return cls(
            app_name=app_name,
            display_name=display_name,
            config_package=config_package,
            storage=Storage(
                env_key=storage_env_key,
                prompt_on_first_run=False,
                env_filename=LEGACY_STORAGE_ENV_FILENAME,
            ),
            _legacy_mode="app_wide_storage",
            _legacy_kit_kwargs=kwargs,
        )

    @staticmethod
    def _warn_legacy_constructor(name: str) -> None:
        """Warn that a capability constructor will be removed in 0.21.

        :param name: Deprecated constructor name used by the caller.
        """
        warnings.warn(
            f"AppRC.{name}(...) is deprecated in AppRC 0.20 and will be "
            "removed in 0.21. Instantiate AppRC(...) directly and pass "
            "storage=rc.Storage(...) when the app needs storage.",
            DeprecationWarning,
            stacklevel=2,
        )

    @property
    def kit(self) -> AppConfigKit:
        """Return the lower-level kit used by advanced internal integrations."""
        return self._kit

    @property
    def spec(self) -> AppConfigSpec:
        """Return the current lower-level application spec."""
        return self._kit.spec

    def config(
        self,
        key: str,
        *,
        prefix: str | None = None,
        title: str | None = None,
        rc_path: tuple[str, ...] | None = None,
    ) -> Callable[[ConfigClassT], ConfigClassT]:
        """Return the public config registration decorator.

        :param key: Stable config key.
        :param prefix: Required full env prefix for ``rc.Config`` subclasses.
        :param title: Optional display title. AppRC derives one from ``key``
            when omitted.
        :param rc_path: Optional runtime config path. Defaults to ``(key,)``.
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
            )

        return decorator

    def bundle(self, bundle_type: BundleClassT) -> BundleClassT:
        """Register an eager aggregate runtime config class.

        :param bundle_type: Class whose annotated fields reference registered
            AppRC config classes.
        :return: Dataclass-like bundle class with a custom eager constructor.
        :raises TypeError: If an annotated field refers to an unregistered
            config class.
        """
        resolved_bundle = self._ensure_dataclass(
            bundle_type,
            init=False,
            repr=False,
        )
        bundle_fields = self._bundle_fields(resolved_bundle)
        post_init = getattr(resolved_bundle, "__post_init__", None)
        setattr(
            resolved_bundle,
            "__init__",
            self._build_bundle_init(
                resolved_bundle,
                bundle_fields,
                post_init,
            ),
        )
        setattr(
            resolved_bundle,
            "__repr__",
            self._build_bundle_repr(resolved_bundle, bundle_fields),
        )
        return cast(BundleClassT, resolved_bundle)

    def mount_cli(self, cli: typer.Typer, **kwargs: Any) -> typer.Typer:
        """Mount AppRC's generated CLI commands on a Typer app.

        :param cli: Typer application that receives the AppRC config command
            group.
        :param kwargs: Advanced options forwarded to the lower-level Typer
            mounting helper.
        :return: Mounted generated config Typer application.
        :raises TypeError: If ``cli`` is not a Typer application.
        """
        if not isinstance(cli, typer.Typer):
            raise TypeError(
                "AppRC.mount_cli currently supports typer.Typer instances only."
            )
        return mount_config_cli(cli, self._kit, **kwargs)

    def bootstrap(
        self,
        *,
        env_files: Sequence[Path] | None = None,
        env_file_overrides_os_environ: bool = False,
        load_dotenv_layers: bool = True,
        storage: str | None = None,
        logger: BootstrapLogger | None = None,
    ) -> EnvBootstrapResult:
        """Prepare AppRC runtime layers for non-Typer use.

        :param env_files: Optional run-local dotenv files.
        :param env_file_overrides_os_environ: Whether explicit dotenv values
            beat existing process env values inside this process.
        :param load_dotenv_layers: Whether packaged defaults, app, storage, and
            explicit dotenv layers should be merged into ``os.environ``.
        :param storage: Optional storage selector for apps with storage.
        :param logger: Optional application logger for bootstrap status.
        :return: Bootstrap summary for diagnostics and tests.
        """
        return self._kit.bootstrap(
            env_files=tuple(env_files or ()),
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            storage=storage,
            logger=logger,
        )

    @property
    def bootstrap_result(self) -> EnvBootstrapResult | None:
        """Return the latest successful process bootstrap, when available.

        :return: Bootstrap summary shared by Python and mounted CLI paths, or
            ``None`` before the first successful bootstrap.
        """
        return self._bootstrap_state.result

    def ensure_bootstrapped(self) -> EnvBootstrapResult:
        """Load default AppRC layers only when bootstrap has not run.

        High-level convenience functions may call this method before direct
        config construction. Application entrypoints that need custom env
        files, precedence, or an explicit storage selector should call
        :meth:`bootstrap` themselves.

        :return: Existing or newly created bootstrap summary.
        """
        return self._kit._ensure_bootstrapped()

    @staticmethod
    def _build_legacy_kit_kwargs(
        *,
        declaration: _AppRCDeclaration,
        legacy_mode: str,
        legacy_kit_kwargs: Mapping[str, object],
    ) -> dict[str, object]:
        """Return arguments used only by deprecated mode constructors.

        :param declaration: Typed public declaration values.
        :param legacy_mode: Deprecated constructor name.
        :param legacy_kit_kwargs: Extra 0.19 constructor arguments.
        :return: Normalized lower-level compatibility arguments.
        """
        if "envs" in legacy_kit_kwargs:
            raise TypeError(
                "AppRC mode constructors do not accept envs=.... Register "
                "config classes with @MyRC.config(...)."
            )
        common: dict[str, object] = {
            "app_name": declaration.app_name,
            "display_name": declaration.display_name,
            "config_package": declaration.config_package,
            "command_name": declaration.command_name,
        }
        resolved = {**common, **legacy_kit_kwargs}
        resolved.setdefault(
            "shared_env_filename",
            LEGACY_DEFAULTS_ENV_FILENAME,
        )
        resolved.setdefault(
            "app_wide_env_filename",
            LEGACY_APP_ENV_FILENAME,
        )
        resolved.setdefault(
            "storage_env_filename",
            LEGACY_STORAGE_ENV_FILENAME,
        )
        resolved.setdefault(
            "index_filename",
            AppConfigSpec.derive_legacy_apprc_toml_filename(
                declaration.app_name
            ),
        )
        resolved["_legacy_constructor"] = legacy_mode
        if legacy_mode in {"env_only", "app_wide_config"}:
            resolved["storage_layer"] = "disabled"
            resolved["named_storage_layer"] = "disabled"
        else:
            resolved["storage_layer"] = "required"
            resolved["named_storage_layer"] = "optional"
            if (
                declaration.storage is not None
                and declaration.storage.env_key is not None
            ):
                resolved.setdefault(
                    "storage_env_key",
                    declaration.storage.env_key,
                )
        resolved["app_wide_layer"] = (
            "default"
            if legacy_mode in {"app_wide_config", "app_wide_storage"}
            else "optional"
        )
        return resolved

    def _build_kit(self) -> AppConfigKit:
        """Build a lower-level kit from the current registrations."""
        envs = tuple(
            item.config_type
            for item in self._registered_by_key.values()
            if _is_env_config(item.config_type)
        )
        if self._legacy_kit_kwargs is not None:
            return AppConfigKit(
                **cast(Any, self._legacy_kit_kwargs),
                envs=envs,
                _bootstrap_state=self._bootstrap_state,
            )
        declaration = self._declaration
        return AppConfigKit(
            app_name=declaration.app_name,
            display_name=declaration.display_name,
            config_package=declaration.config_package,
            envs=envs,
            storage=declaration.storage,
            command_name=declaration.command_name,
            defaults_env_filename=declaration.defaults_env_filename,
            app_env_filename=declaration.app_env_filename,
            apprc_toml_filename=declaration.apprc_toml_filename,
            _bootstrap_state=self._bootstrap_state,
        )

    def _register_config(
        self,
        config_type: ConfigClassT,
        *,
        key: str,
        prefix: str | None,
        title: str | None,
        rc_path: tuple[str, ...] | None,
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

        resolved_type = self._ensure_dataclass(config_type)
        resolved_title = title or _humanize_title(key)
        resolved_rc_path = rc_path or (key,)
        public_fields = _collect_public_fields(resolved_type)

        if _is_env_config(resolved_type):
            owner = self._build_owner(
                resolved_type,
                key=key,
                title=resolved_title,
                prefix=prefix,
                rc_path=resolved_rc_path,
                public_fields=public_fields,
            )
            self._validate_unique_env_keys(resolved_type, public_fields)
            setattr(resolved_type, "config_owner", owner)
        else:
            self._validate_python_only_registration(
                resolved_type,
                prefix=prefix,
                public_fields=public_fields,
            )

        registered = RegisteredConfig(
            key=key,
            config_type=resolved_type,
            title=resolved_title,
            rc_path=resolved_rc_path,
            prefix=prefix,
            env_fields=public_fields,
        )
        if self.bootstrap_result is not None and _is_env_config(resolved_type):
            LOG.warning(
                "Registering config %s after AppRC bootstrap for %s. Values "
                "still bind from the current process environment, but "
                "bootstrap provenance for this late registration is "
                "incomplete. Import the root config bundle before bootstrap.",
                resolved_type.__name__,
                self._declaration.app_name,
            )
        self._registered_by_key[key] = registered
        self._registered_by_type[resolved_type] = registered
        for field_name, spec in public_fields.items():
            self._env_key_index[spec.env_key] = (
                resolved_type.__name__,
                field_name,
            )
        self._kit = self._build_kit()
        return cast(ConfigClassT, resolved_type)

    def _build_owner(
        self,
        config_type: type[ConfigBase],
        *,
        key: str,
        title: str,
        prefix: str | None,
        rc_path: tuple[str, ...],
        public_fields: Mapping[str, PublicFieldSpec],
    ) -> ConfigOwner:
        """Build an internal owner from public env field markers."""
        if prefix is None or not prefix:
            raise ValueError(
                f"{config_type.__name__} inherits rc.Config, so "
                f'@MyRC.config("{key}", ...) requires prefix="...".'
            )
        _validate_prefix(
            config_type=config_type,
            config_key=key,
            prefix=prefix,
            fields=public_fields,
        )
        owner = ConfigOwner(
            key=key,
            title=title,
            env_prefix=prefix,
            rc_path=rc_path,
            fields=_derive_internal_fields(
                config_type=config_type,
                prefix=prefix,
                public_fields=public_fields,
            ),
        )
        validate_config_owner(owner)
        return owner

    def _validate_unique_env_keys(
        self,
        config_type: type[ConfigBase],
        public_fields: Mapping[str, PublicFieldSpec],
    ) -> None:
        """Reject env keys that another registered config already owns."""
        for field_name, spec in public_fields.items():
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

    def _validate_python_only_registration(
        self,
        config_type: type[ConfigBase],
        *,
        prefix: str | None,
        public_fields: Mapping[str, PublicFieldSpec],
    ) -> None:
        """Validate a ``ConfigBase`` registration."""
        if prefix is not None:
            raise ValueError(
                f"{config_type.__name__} inherits rc.ConfigBase, so it is "
                "Python-only config. Do not pass prefix=... unless the class "
                "inherits rc.Config."
            )
        if not public_fields:
            return
        field_name = next(iter(public_fields))
        raise TypeError(
            f"{config_type.__name__}.{field_name} uses rc.field(...), but "
            f"{config_type.__name__} inherits rc.ConfigBase. Use rc.Config "
            "for env-backed config, or use normal Python/dataclass defaults "
            "for rc.ConfigBase."
        )

    def _bundle_fields(
        self,
        bundle_type: type[object],
    ) -> dict[str, _BundleFieldSpec]:
        """Return registered config fields declared by one bundle."""
        type_hints = get_type_hints(bundle_type, include_extras=True)
        dataclass_fields = {
            item.name: item for item in fields(cast(Any, bundle_type))
        }
        bundle_fields: dict[str, _BundleFieldSpec] = {}
        for field_name, annotation in type_hints.items():
            if get_origin(annotation) is ClassVar:
                continue
            dataclass_field = dataclass_fields.get(field_name)
            if (
                field_name.startswith("_")
                or dataclass_field is not None
                and dataclass_field.metadata.get("internal")
            ):
                continue
            if not isinstance(annotation, type):
                _raise_unregistered_bundle_field(
                    bundle_type,
                    field_name,
                    annotation,
                )
            registered = self._registered_by_type.get(annotation)
            if registered is None:
                _raise_unregistered_bundle_field(
                    bundle_type,
                    field_name,
                    annotation,
                )
            assert registered is not None
            bundle_fields[field_name] = _BundleFieldSpec(
                name=field_name,
                config_type=registered.config_type,
                init=dataclass_fields[field_name].init,
            )
        return bundle_fields

    def _build_bundle_init(
        self,
        bundle_type: type[object],
        bundle_fields: Mapping[str, _BundleFieldSpec],
        post_init: Callable[[object], None] | None,
    ) -> Callable[..., None]:
        """Build the custom eager bundle constructor."""

        def __init__(self: object, **kwargs: object) -> None:
            """Construct every child config eagerly."""
            init_fields = {
                field_name
                for field_name, spec in bundle_fields.items()
                if spec.init
            }
            unknown = set(kwargs) - init_fields
            if unknown:
                joined = ", ".join(sorted(unknown))
                raise TypeError(
                    f"{bundle_type.__name__} got unexpected config "
                    f"argument(s): {joined}."
                )
            LOG.debug("Constructing AppRC bundle %s.", bundle_type.__name__)
            for field_name, spec in bundle_fields.items():
                if not spec.init:
                    continue
                expected_type = spec.config_type
                if field_name in kwargs:
                    value = kwargs[field_name]
                    if not isinstance(value, expected_type):
                        raise TypeError(
                            f"{bundle_type.__name__}.{field_name} expected "
                            f"{expected_type.__name__}, got "
                            f"{type(value).__name__}."
                        )
                else:
                    registered = self_app._registered_by_type[expected_type]
                    LOG.debug(
                        'Constructing config "%s" using %s.',
                        registered.key,
                        expected_type.__name__,
                    )
                    value = expected_type()
                object.__setattr__(self, field_name, value)
            if post_init is not None:
                post_init(self)

        self_app = self
        return __init__

    def _build_bundle_repr(
        self,
        bundle_type: type[object],
        bundle_fields: Mapping[str, _BundleFieldSpec],
    ) -> Callable[[object], str]:
        """Build a secret-safe bundle repr."""

        def __repr__(self: object) -> str:
            """Return a minimal repr that never prints child values."""
            parts = [
                f"{field_name}=<{spec.config_type.__name__}>"
                for field_name, spec in bundle_fields.items()
            ]
            return f"{bundle_type.__name__}({', '.join(parts)})"

        return __repr__

    def _ensure_dataclass(
        self,
        cls: type[Any],
        *,
        init: bool = True,
        repr: bool = True,
    ) -> type[Any]:
        """Return ``cls`` as a dataclass without reprocessing subclasses."""
        if "__dataclass_fields__" in cls.__dict__:
            return cls
        return dataclasses.dataclass(
            slots=ut.dataclass_slots_preserving_class_identity(cls),
            init=init,
            repr=repr,
        )(cls)


def _validate_config_class(config_type: type[object]) -> None:
    """Reject classes outside the public config inheritance model."""
    if not isinstance(config_type, type):
        raise TypeError("@MyRC.config(...) can only decorate classes.")
    if not issubclass(config_type, ConfigBase):
        raise TypeError(
            f"{config_type.__name__} must inherit from rc.Config or "
            "rc.ConfigBase before it can be registered with "
            "@MyRC.config(...)."
        )


def _is_env_config(
    config_type: type[object],
) -> TypeGuard[type[Config]]:
    """Return whether ``config_type`` reads env-backed AppRC fields."""
    return issubclass(config_type, Config)


def _collect_public_fields(
    config_type: type[ConfigBase],
) -> dict[str, PublicFieldSpec]:
    """Collect ``rc.field(...)`` markers from one dataclass."""
    public_fields: dict[str, PublicFieldSpec] = {}
    for item in fields(config_type):
        spec = item.metadata.get(PUBLIC_FIELD_METADATA_KEY)
        if spec is None:
            continue
        if not isinstance(spec, PublicFieldSpec):
            raise TypeError(
                f"{PUBLIC_FIELD_METADATA_KEY!r} metadata must contain "
                f"PublicFieldSpec, got {type(spec).__name__}."
            )
        public_fields[item.name] = spec
    return public_fields


def _validate_prefix(
    *,
    config_type: type[ConfigBase],
    config_key: str,
    prefix: str,
    fields: Mapping[str, PublicFieldSpec],
) -> None:
    """Ensure every public env key starts with the config prefix."""
    for field_name, spec in fields.items():
        if spec.env_key.startswith(prefix) and spec.env_key != prefix:
            continue
        raise ValueError(
            f"{config_type.__name__}.{field_name} uses env key "
            f'{spec.env_key}, but config "{config_key}" requires prefix '
            f"{prefix}. Use an env key starting with {prefix} or change the "
            "config prefix."
        )


def _derive_internal_fields(
    *,
    config_type: type[ConfigBase],
    prefix: str,
    public_fields: Mapping[str, PublicFieldSpec],
) -> tuple[ConfigField, ...]:
    """Convert public field markers into internal owner-local fields."""
    type_hints = get_type_hints(config_type, include_extras=True)
    derived: list[ConfigField] = []
    for field_name, spec in public_fields.items():
        python_type = spec.python_type or type_hints.get(field_name, Any)
        if python_type is Any:
            raise TypeError(
                f"{config_type.__name__}.{field_name} must have a type "
                "annotation or rc.field(..., python_type=...)."
            )
        derived.append(
            ConfigField(
                name=field_name,
                env_var=_derive_internal_env_suffix(
                    full_env_key=spec.env_key,
                    prefix=prefix,
                ),
                python_type=cast(type[Any], python_type),
                default=spec.default,
                default_factory=spec.default_factory,
                packaged_default=spec.packaged_default,
                title=spec.title or "",
                explanation_short=spec.explanation_short,
                explanation_long=spec.explanation_long,
                secret=spec.secret,
                editable=spec.editable,
                required=spec.inferred_required(),
                choices=spec.choices,
            )
        )
    return tuple(derived)


def _derive_internal_env_suffix(
    *,
    full_env_key: str,
    prefix: str,
) -> str:
    """Return the owner-local env suffix for a public full env key."""
    return full_env_key.removeprefix(prefix)


def _humanize_title(key: str) -> str:
    """Return a simple human display title from a config key."""
    words = key.replace("-", "_").split("_")
    return " ".join(word.capitalize() for word in words if word) or key


def _raise_unregistered_bundle_field(
    bundle_type: type[object],
    field_name: str,
    annotation: object,
) -> NoReturn:
    """Raise the standard error for invalid bundle annotations."""
    type_name = getattr(annotation, "__name__", repr(annotation))
    raise TypeError(
        f"{bundle_type.__name__}.{field_name} refers to {type_name}, but "
        f"{type_name} is not registered with this AppRC instance.\nDecorate "
        "it with @MyRC.config(...)."
    )


__all__ = [
    "AppRC",
    "RegisteredConfig",
]
