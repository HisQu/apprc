"""Public AppRC application facade."""

from __future__ import annotations

# == Standard Library ========================
import dataclasses
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    NoReturn,
    TypeGuard,
    TypeVar,
    cast,
    dataclass_transform,
    get_origin,
    get_type_hints,
)

# == 3rd Party ===============================

# == Internal ================================
import apprc.utils as ut
from apprc.services.manager import ConfigManager
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.resolution import (
    BundleFieldSpec as _BundleFieldSpec,
    ResolveOptions,
)
from apprc.runtime.resolution import ResolvedConfig, resolve_config
from apprc.definition.app_config.storage import Storage
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.env_config._validation import validate_config_owner
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.public.config import Config, ConfigBase
from apprc.public.field import (
    _FIELD_DECLARATION_METADATA_KEY,
    _FieldDeclaration,
)

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
    :param declared_fields: Field declarations registered on this class.
    """

    key: str
    config_type: type[ConfigBase]
    title: str
    rc_path: tuple[str, ...]
    prefix: str | None
    declared_fields: Mapping[str, _FieldDeclaration]


@dataclass(frozen=True, slots=True)
class _AppRCDeclaration:
    """Typed values shared by every rebuild of one public facade.

    :param app_id: Stable application identity.
    :param display_name: Human-readable application name.
    :param config_package: Package that may contain managed defaults.
    :param command_name: Executable name used in guidance.
    :param user_dotenv: Optional user-wide dotenv declaration.
    :param storage: Optional persistent-storage declaration.
    :param apprc_dir: Optional application-declared AppRC directory.
    :param apprc_dir_env_key: Explicit directory override key.
    :param legacy_app_ids: Released 0.19 identities accepted by migration.
    """

    app_id: str
    display_name: str
    config_package: str | None
    command_name: str | None
    user_dotenv: UserDotenv | None
    storage: Storage | None
    apprc_dir: Path | None
    apprc_dir_env_key: str | None
    legacy_app_ids: tuple[str, ...]


class AppRC:
    """Public facade for one application's AppRC integration.

    App authors create one ``AppRC`` object, add :class:`UserDotenv` when the
    app needs persistent user overrides, add :class:`Storage` when the app
    writes persistent data, register config classes through
    ``@MyRC.config(...)``, and load inputs with :meth:`resolve`.
    :meth:`manage` provides noninteractive setup and editing.
    """

    def __init__(
        self,
        *,
        app_id: str,
        config_package: str | None = None,
        display_name: str | None = None,
        command_name: str | None = None,
        user_dotenv: UserDotenv | None = None,
        storage: Storage | None = None,
        apprc_dir: Path | None = None,
        apprc_dir_env_key: str | None = None,
        legacy_app_ids: tuple[str, ...] = (),
    ) -> None:
        """Build an application declaration with optional writable features.

        :param app_id: Stable application identity.
        :param config_package: Package containing packaged config resources.
        :param display_name: Human-readable name, or ``None`` to use
            ``app_id``.
        :param command_name: Executable name shown in generated instructions.
        :param user_dotenv: User dotenv declaration, or ``None`` to avoid that
            persistent layer.
        :param storage: Storage declaration, or ``None`` for storage-free apps.
        :param apprc_dir: Optional application-declared AppRC directory.
        :param apprc_dir_env_key: Explicit directory override key.
        :param legacy_app_ids: Released 0.19 identities accepted by migration.
        """
        self._declaration = _AppRCDeclaration(
            app_id=app_id,
            display_name=display_name or app_id,
            config_package=config_package,
            command_name=command_name,
            user_dotenv=user_dotenv,
            storage=storage,
            apprc_dir=apprc_dir,
            apprc_dir_env_key=apprc_dir_env_key,
            legacy_app_ids=legacy_app_ids,
        )
        self._registered_by_key: dict[str, RegisteredConfig] = {}
        self._registered_by_type: dict[type[ConfigBase], RegisteredConfig] = {}
        self._bundles: dict[type[object], tuple[_BundleFieldSpec, ...]] = {}
        self._env_key_index: dict[str, tuple[str, str]] = {}
        self._schema = self._build_schema()

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
            options=options,
            environment=environment,
        )

    @dataclass_transform()
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
        self._bundles[resolved_bundle] = tuple(bundle_fields.values())
        return cast(BundleClassT, resolved_bundle)

    def _build_schema(self) -> AppConfigSpec:
        """Build validated schema metadata from current registrations."""
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
            user_dotenv=declaration.user_dotenv,
            storage=declaration.storage,
            command_name=declaration.command_name,
            apprc_dir=declaration.apprc_dir,
            apprc_dir_env_key=declaration.apprc_dir_env_key,
            legacy_app_ids=declaration.legacy_app_ids,
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
        declared_fields = _collect_field_declarations(resolved_type)

        if _is_env_config(resolved_type):
            owner = self._build_owner(
                resolved_type,
                key=key,
                title=resolved_title,
                prefix=prefix,
                rc_path=resolved_rc_path,
                declared_fields=declared_fields,
            )
            self._validate_unique_env_keys(resolved_type, declared_fields)
            setattr(resolved_type, "config_owner", owner)
        else:
            self._validate_python_only_registration(
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
        )
        self._registered_by_key[key] = registered
        self._registered_by_type[resolved_type] = registered
        for field_name, spec in declared_fields.items():
            self._env_key_index[spec.env_key] = (
                resolved_type.__name__,
                field_name,
            )
        self._schema = self._build_schema()
        return cast(ConfigClassT, resolved_type)

    def _build_owner(
        self,
        config_type: type[ConfigBase],
        *,
        key: str,
        title: str,
        prefix: str | None,
        rc_path: tuple[str, ...],
        declared_fields: Mapping[str, _FieldDeclaration],
    ) -> ConfigOwner:
        """Build an internal owner from registered field declarations."""
        if prefix is None or not prefix:
            raise ValueError(
                f"{config_type.__name__} inherits rc.Config, so "
                f'@MyRC.config("{key}", ...) requires prefix="...".'
            )
        _validate_prefix(
            config_type=config_type,
            config_key=key,
            prefix=prefix,
            fields=declared_fields,
        )
        owner = ConfigOwner(
            key=key,
            title=title,
            env_prefix=prefix,
            rc_path=rc_path,
            fields=_derive_config_fields(
                config_type=config_type,
                prefix=prefix,
                declared_fields=declared_fields,
            ),
        )
        validate_config_owner(owner)
        return owner

    def _validate_unique_env_keys(
        self,
        config_type: type[ConfigBase],
        declared_fields: Mapping[str, _FieldDeclaration],
    ) -> None:
        """Reject env keys that another registered config already owns."""
        for field_name, spec in declared_fields.items():
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
        declared_fields: Mapping[str, _FieldDeclaration],
    ) -> None:
        """Validate a ``ConfigBase`` registration."""
        if prefix is not None:
            raise ValueError(
                f"{config_type.__name__} inherits rc.ConfigBase, so it is "
                "Python-only config. Do not pass prefix=... unless the class "
                "inherits rc.Config."
            )
        if not declared_fields:
            return
        field_name = next(iter(declared_fields))
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
                default_factory=self._bundle_default_factory(
                    bundle_type=bundle_type,
                    field_name=field_name,
                    config_type=registered.config_type,
                    dataclass_field=dataclass_fields[field_name],
                ),
            )
        return bundle_fields

    @staticmethod
    def _bundle_default_factory(
        *,
        bundle_type: type[object],
        field_name: str,
        config_type: type[ConfigBase],
        dataclass_field: dataclasses.Field[Any],
    ) -> Callable[[], object] | None:
        """Return the factory for an eager keyword-only bundle field.

        :param bundle_type: Bundle class being registered.
        :param field_name: Registered child attribute.
        :param config_type: Registered child type used by the factory.
        :param dataclass_field: Standard dataclass field declaration.
        :return: Factory for an eager field, or ``None`` for ``init=False``.
        :raises TypeError: If the constructor contract cannot be typed.
        """
        if not dataclass_field.init:
            return None
        if not dataclass_field.kw_only:
            raise TypeError(
                f"{bundle_type.__name__}.{field_name} must be keyword-only. "
                "Declare the bundle with @dataclass(kw_only=True)."
            )
        factory = dataclass_field.default_factory
        if factory is dataclasses.MISSING:
            raise TypeError(
                f"{bundle_type.__name__}.{field_name} requires "
                f"field(default_factory={config_type.__name__})."
            )
        return cast(Callable[[], object], factory)

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
                    assert issubclass(expected_type, ConfigBase)
                    registered = self_app._registered_by_type[expected_type]
                    LOG.debug(
                        'Constructing config "%s" using %s.',
                        registered.key,
                        expected_type.__name__,
                    )
                    if spec.default_factory is None:
                        raise TypeError(
                            f"{bundle_type.__name__}.{field_name} has no "
                            "default factory."
                        )
                    value = spec.default_factory()
                    if not isinstance(value, expected_type):
                        raise TypeError(
                            f"{bundle_type.__name__}.{field_name} default "
                            f"factory returned {type(value).__name__}; "
                            f"expected {expected_type.__name__}."
                        )
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


def _collect_field_declarations(
    config_type: type[ConfigBase],
) -> dict[str, _FieldDeclaration]:
    """Collect ``rc.field(...)`` markers from one dataclass."""
    declared_fields: dict[str, _FieldDeclaration] = {}
    for item in fields(config_type):
        spec = item.metadata.get(_FIELD_DECLARATION_METADATA_KEY)
        if spec is None:
            continue
        if not isinstance(spec, _FieldDeclaration):
            raise TypeError(
                f"{_FIELD_DECLARATION_METADATA_KEY!r} metadata must contain "
                f"an AppRC field declaration, got {type(spec).__name__}."
            )
        declared_fields[item.name] = spec
    return declared_fields


def _validate_prefix(
    *,
    config_type: type[ConfigBase],
    config_key: str,
    prefix: str,
    fields: Mapping[str, _FieldDeclaration],
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


def _derive_config_fields(
    *,
    config_type: type[ConfigBase],
    prefix: str,
    declared_fields: Mapping[str, _FieldDeclaration],
) -> tuple[ConfigField, ...]:
    """Normalize field declarations after class types become available."""
    type_hints = get_type_hints(config_type, include_extras=True)
    derived: list[ConfigField] = []
    for field_name, spec in declared_fields.items():
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
