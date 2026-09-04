"""Public AppRC application facade."""

# == Standard Library ========================
import dataclasses
import logging
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
from apprc.definition.app_config.spec import AppConfigSpec
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

    :param app_id: Stable application identity.
    :param display_name: Human-readable application name.
    :param config_package: Package containing managed defaults.
    :param command_name: Executable name used in guidance.
    :param storage: Optional persistent-storage declaration.
    :param apprc_dir: Optional application-declared AppRC directory.
    :param apprc_dir_env_key: Explicit directory override key.
    :param legacy_app_ids: Released 0.19 identities accepted by migration.
    """

    app_id: str
    display_name: str
    config_package: str
    command_name: str | None
    storage: Storage | None
    apprc_dir: Path | None
    apprc_dir_env_key: str | None
    legacy_app_ids: tuple[str, ...]


class AppRC:
    """Public facade for one application's AppRC integration.

    App authors create one ``AppRC`` object, add :class:`Storage` when the app
    writes persistent data, register config classes through
    ``@MyRC.config(...)``, and mount runtime behavior with :meth:`mount_cli` or
    :meth:`bootstrap`.
    """

    def __init__(
        self,
        *,
        app_id: str,
        config_package: str,
        display_name: str | None = None,
        command_name: str | None = None,
        storage: Storage | None = None,
        apprc_dir: Path | None = None,
        apprc_dir_env_key: str | None = None,
        legacy_app_ids: tuple[str, ...] = (),
    ) -> None:
        """Build an application declaration with optional storage.

        :param app_id: Stable application identity.
        :param config_package: Package containing packaged config resources.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_id``.
        :param command_name: Executable name shown in generated instructions.
        :param storage: Storage declaration, or ``None`` for config-only apps.
        :param apprc_dir: Optional application-declared AppRC directory.
        :param apprc_dir_env_key: Explicit directory override key.
        :param legacy_app_ids: Released 0.19 identities accepted by migration.
        """
        self._declaration = _AppRCDeclaration(
            app_id=app_id,
            display_name=display_name or app_id,
            config_package=config_package,
            command_name=command_name,
            storage=storage,
            apprc_dir=apprc_dir,
            apprc_dir_env_key=apprc_dir_env_key,
            legacy_app_ids=legacy_app_ids,
        )
        self._registered_by_key: dict[str, RegisteredConfig] = {}
        self._registered_by_type: dict[type[ConfigBase], RegisteredConfig] = {}
        self._env_key_index: dict[str, tuple[str, str]] = {}
        self._bootstrap_state = BootstrapState()
        self._kit = self._build_kit()

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

    def _build_kit(self) -> AppConfigKit:
        """Build a lower-level kit from the current registrations."""
        envs = tuple(
            item.config_type
            for item in self._registered_by_key.values()
            if _is_env_config(item.config_type)
        )
        declaration = self._declaration
        return AppConfigKit(
            app_id=declaration.app_id,
            display_name=declaration.display_name,
            config_package=declaration.config_package,
            envs=envs,
            storage=declaration.storage,
            command_name=declaration.command_name,
            apprc_dir=declaration.apprc_dir,
            apprc_dir_env_key=declaration.apprc_dir_env_key,
            legacy_app_ids=declaration.legacy_app_ids,
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
                self._declaration.app_id,
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
