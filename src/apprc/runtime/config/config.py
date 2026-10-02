"""Public AppRC config base classes."""

from __future__ import annotations

# ===============================================================
# == Standard library
# ===============================================================
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar, Self

# ===============================================================
# == Internal
# ===============================================================
from apprc.runtime.config.base import BaseConfig as ConfigBase
from apprc.runtime.config._loading import (
    owner_env_mapping,
)
import apprc.runtime.config._state_transfer as state_transfer
from apprc.runtime.config._binding import (
    bind_owner_from_env,
    protected_field_names,
)
from apprc.definition.resolution import ConfigSource, ImportedConfig
from apprc.definition.env_config.sentinels import ENV_FIELD_MISSING
from apprc.runtime.config._defaults import (
    resolve_instance_owner_defaults,
)
from apprc.runtime.config._origins import (
    origin_for_field,
    python_constructor_field_names,
    with_field_origin,
)
from apprc.runtime.config._runtime_validation import (
    validate_all_owner_values,
    validate_owner_field_value,
    validate_python_constructor_fields,
    validate_required_fields,
)
from apprc.runtime.provenance import (
    ConfigOriginState,
    ConfigProvenance,
    PythonProvenanceOrigin,
    source_for_origin,
)
from apprc.definition.env_config.schema import ConfigOwner

LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apprc.runtime.resolution import ResolvedConfig


@dataclass(slots=True)
class Config(ConfigBase):
    """Runtime config section registered by an ``AppRC`` declaration.

    Subclasses declare typed fields with :func:`apprc.field` and receive their
    owner schema through ``@MyRC.config(...)``. ``Config`` reads OS environment
    variables from the current Python process via ``os.environ``. It does not
    load dotenv files or application config layers. Use ``MyRC.resolve().build(Settings)`` to construct from captured
    managed sources without changing the environment.
    """

    config_owner: ClassVar[ConfigOwner | None] = None
    _apprc_source: ConfigSource | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )
    _apprc_owner_override: ConfigOwner | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )
    _apprc_imported_field_names: frozenset[str] | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )
    _apprc_imported_binding: ImportedConfig[Any] | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )
    _apprc_field_origins: dict[str, ConfigOriginState] = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )
    bind_from_env_on_init: bool = field(
        default=True,
        repr=False,
        kw_only=True,
        metadata={"internal": True},
    )

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        """Create an instance while recording constructor-provided fields.

        Dataclass ``__post_init__`` runs after normal field assignment, so AppRC
        captures Python constructor arguments in ``__new__`` before env binding
        can decide which fields are protected for this object's lifetime.
        """
        # !! Keep two-argument super(): slotted dataclass inheritance on
        # !! Python 3.12/3.13 breaks zero-argument super().
        self = super(Config, cls).__new__(cls, *args, **kwargs)
        owner = cls._class_config_owner()
        owner_override = kwargs.get("_apprc_owner_override")
        if owner_override is not None:
            if not isinstance(owner_override, ConfigOwner):
                raise TypeError("_apprc_owner_override must be a ConfigOwner.")
            owner = owner_override
        imported_field_names = kwargs.get("_apprc_imported_field_names")
        imported_binding = kwargs.get("_apprc_imported_binding")
        if imported_field_names is not None or imported_binding is not None:
            if not isinstance(imported_binding, ImportedConfig):
                raise TypeError(
                    "Imported config binding state is reserved for "
                    "ResolvedConfig.build()."
                )
            if (
                owner_override is None
                or imported_binding.runtime_owner is not owner_override
            ):
                raise TypeError(
                    "Imported config binding must match its runtime owner."
                )
            if imported_field_names != frozenset(
                imported_binding.field_targets
            ):
                raise TypeError(
                    "Imported config field names must match its binding."
                )
        elif owner_override is not None:
            raise TypeError(
                "Imported config owner state is reserved for "
                "ResolvedConfig.build()."
            )
        constructor_fields = python_constructor_field_names(
            cls,
            owner,
            args,
            kwargs,
        )
        if owner_override is not None:
            constructor_fields -= frozenset(
                field_name
                for field_name, value in kwargs.items()
                if value is ENV_FIELD_MISSING
            )
        object.__setattr__(
            self,
            "_apprc_field_origins",
            {
                field_name: ConfigOriginState(
                    "python_constructor_argument",
                    env_key=owner.env_key(field_name),
                )
                for field_name in constructor_fields
            },
        )
        return self

    def __post_init__(self) -> None:
        """Resolve owner defaults, bind env values, and validate completeness."""
        self._resolve_owner_defaults()
        validate_python_constructor_fields(
            self,
            self._config_owner(),
            self._apprc_field_origins,
        )
        if self.bind_from_env_on_init:
            self._bind_from_env(
                override_python_values=False, source=self._apprc_source
            )
        validate_required_fields(self, self._config_owner())
        validate_all_owner_values(self, self._config_owner())

    # ===============================================================
    # == Reading from os.environ
    # ===============================================================

    def reload(self, override_python_values: bool = False) -> None:
        """Re-bind owner-backed fields from current process ``os.environ``.

        Python constructor arguments, later Python assignments, and scoped
        overrides stay authoritative for the object lifetime by default. Pass
        ``override_python_values=True`` when the current process environment
        should deliberately replace those Python-provided values.

        Imported dependency configs cannot reload from ambient environment;
        resolve their parent AppRC again and build them from that snapshot.

        :param override_python_values: Whether env values may overwrite
            ``python_constructor_argument`` and
            ``python_runtime_assignment`` and ``python_scoped_override`` fields.
        """
        if self._apprc_owner_override is not None:
            raise RuntimeError(
                "Imported configs cannot reload from ambient environment; "
                "resolve the parent AppRC and build the imported config again."
            )
        LOG.warning(f"Reloading from os.environ: {self.__class__.__name__} ...")
        skipped_python_fields = self._bind_from_env(
            override_python_values=override_python_values
        )
        self._warn_skipped_python_fields(skipped_python_fields)

    def bind_from_env(self, override_python_values: bool = False) -> None:
        """Load owner-backed values from current process ``os.environ``.

        This does not load dotenv files or application config layers. Use ``reload_from(resolved)`` to apply a captured application source.
        Owner defaults are always resolved; this method only controls whether
        process env values overlay those defaults.
        Imported dependency configs cannot read ambient environment values.

        :param override_python_values: Whether env values may overwrite fields
            provided through Python constructor arguments, later assignment, or
            scoped overrides.
        """
        if self._apprc_owner_override is not None:
            raise RuntimeError(
                "Imported configs cannot bind from ambient environment; "
                "resolve the parent AppRC and build the imported config again."
            )
        self._bind_from_env(override_python_values=override_python_values)
        validate_required_fields(self, self._config_owner())

    def reload_from(
        self,
        resolved: ResolvedConfig,
        *,
        override_python_values: bool = False,
    ) -> None:
        """Apply a resolution only after all replacement fields validate.

        Source values absent from the new resolution return to Python defaults.
        Constructor, assigned, and scoped values stay authoritative unless the
        caller explicitly requests their replacement. User post-init hooks do
        not run again.

        :param resolved: Resolution containing this registered section type.
        :param override_python_values: Whether to replace Python-owned values.
        :return: None.
        """
        imported_binding = self._apprc_imported_binding
        if (
            self._apprc_owner_override is None
            and imported_binding is None
            and type(self) not in resolved.registered_types
            and any(
                type(self) in (item.config_type, item.runtime_config_type)
                for item in resolved.imported_configs
            )
        ):
            raise ValueError(
                "Standalone dependency configs cannot reload from a parent "
                "resolution; build the config through its ImportedConfig binding."
            )
        if self._apprc_owner_override is not None:
            if imported_binding is None or not any(
                item is imported_binding for item in resolved.imported_configs
            ):
                raise ValueError(
                    "This imported config can only reload from a resolution "
                    "that contains its exact ImportedConfig binding."
                )
            if (
                imported_binding.parent_owner.requires_storage
                and not resolved._has_valid_storage_selection
            ):
                raise ValueError(
                    f"{imported_binding.parent_owner.title} requires a valid "
                    "storage selection in the parent resolution."
                )
        resolved.require_registered(type(self))
        candidate = state_transfer.shallow_clone(self)
        owner = self._config_owner()
        protected = (
            frozenset()
            if override_python_values
            else protected_field_names(self._apprc_field_origins)
        )
        origins = {
            name: origin
            for name, origin in self._apprc_field_origins.items()
            if name in protected
        }
        resolved_defaults: dict[str, Any] = {}
        for spec in owner.fields:
            if spec.name in protected:
                continue
            if spec.has_default():
                env_key = owner.env_key(spec.name)
                if env_key not in resolved_defaults:
                    resolved_defaults[env_key] = spec.resolve_default()
                value = state_transfer.deepcopy_state_value(
                    resolved_defaults[env_key], {}
                )
            else:
                value = ENV_FIELD_MISSING
            object.__setattr__(candidate, spec.name, value)
        object.__setattr__(candidate, "_apprc_field_origins", origins)
        candidate._bind_from_env(
            override_python_values=override_python_values,
            source=resolved.source,
        )
        validate_required_fields(candidate, owner)
        validate_all_owner_values(candidate, owner)
        for spec in owner.fields:
            object.__setattr__(self, spec.name, getattr(candidate, spec.name))
        object.__setattr__(
            self, "_apprc_field_origins", candidate._apprc_field_origins
        )
        object.__setattr__(self, "_apprc_source", resolved.source)

    def _bind_from_env(
        self,
        override_python_values: bool,
        *,
        source: ConfigSource | None = None,
    ) -> list[str]:
        """Bind env values and return Python-owned fields that were skipped."""
        owner = self._config_owner()
        result = bind_owner_from_env(
            owner,
            self._apprc_field_origins,
            override_python_values=override_python_values,
            source=source,
        )
        for item in result.bound_fields:
            object.__setattr__(self, item.name, item.value)
            self._set_field_origin(item.name, item.origin)
        return list(result.skipped_python_fields)

    def _build_config_provenance(
        self,
        field_name: str,
    ) -> ConfigProvenance:
        """Build provenance metadata for one public config field.

        :param field_name: Runtime dataclass field name.
        :return: Provenance metadata for the current field value.
        """
        # !! Keep two-argument super(): slotted dataclass inheritance on
        # !! Python 3.12/3.13 breaks zero-argument super().
        try:
            owner = self._config_owner()
        except RuntimeError:
            return super(Config, self)._build_config_provenance(field_name)
        try:
            spec = owner.field(field_name)
        except KeyError:
            return super(Config, self)._build_config_provenance(field_name)
        env_key = owner.env_key(field_name)
        state = self._field_origin(field_name)
        return ConfigProvenance(
            field_name=field_name,
            source=source_for_origin(state.origin),
            origin=state.origin,
            value=getattr(self, field_name),
            secret=spec.secret,
            env_key=env_key,
            path=state.path,
            resource=state.resource,
        )

    def _is_field_secret(self, field_name: str) -> bool:
        """Apply this instance's owner metadata to display redaction."""
        try:
            secret = self._config_owner().field(field_name).secret
        except (KeyError, RuntimeError):
            secret = False
        return secret or super(Config, self)._is_field_secret(field_name)

    # ===============================================================
    # == Implementation
    # ===============================================================

    @classmethod
    def _class_config_owner(cls) -> ConfigOwner:
        """Return the owner spec registered on this config class."""
        if cls.config_owner is None:
            raise RuntimeError(
                f"{cls.__name__} must be registered with @MyRC.config(...) "
                "before env binding."
            )
        return cls.config_owner

    def _config_owner(self) -> ConfigOwner:
        """Return this instance's owner, or its class registration owner."""
        return self._apprc_owner_override or type(self)._class_config_owner()

    def _owner_field_names(self) -> frozenset[str]:
        """Return owner-backed runtime field names for this config class."""
        try:
            return frozenset(spec.name for spec in self._config_owner().fields)
        except RuntimeError:
            return frozenset()

    def _field_origin(self, field_name: str) -> ConfigOriginState:
        """Return the recorded origin state or the implicit config default."""
        return origin_for_field(
            self._config_owner(),
            self._apprc_field_origins,
            field_name,
        )

    def _set_field_origin(
        self,
        field_name: str,
        origin: ConfigOriginState,
    ) -> None:
        """Record provenance for one owner-backed field."""
        object.__setattr__(
            self,
            "_apprc_field_origins",
            with_field_origin(self._apprc_field_origins, field_name, origin),
        )

    def _resolve_owner_defaults(self) -> None:
        """Resolve omitted owner-backed fields from derived owner defaults."""
        owner = self._config_owner()
        if self._apprc_owner_override is not None:
            for spec in owner.fields:
                if (
                    not spec.has_default()
                    and self._field_origin(spec.name).origin
                    != "python_constructor_argument"
                ):
                    object.__setattr__(self, spec.name, ENV_FIELD_MISSING)
        object.__setattr__(
            self,
            "_apprc_field_origins",
            resolve_instance_owner_defaults(
                self,
                owner,
                field_origins=self._apprc_field_origins,
                copy_value=state_transfer.deepcopy_state_value,
            ),
        )

    def _validate_existing_assignment(self, key: str, value: Any) -> None:
        """Validate owner-backed assignment before storing it."""
        if key not in self._owner_field_names():
            return
        validate_owner_field_value(self._config_owner(), key, value)

    def _after_existing_assignment(
        self,
        key: str,
        value: Any,
        *,
        origin: PythonProvenanceOrigin,
    ) -> None:
        """Record owner-backed assignment provenance after storing it."""
        # !! Keep two-argument super(): slotted dataclass inheritance on
        # !! Python 3.12/3.13 breaks zero-argument super().
        super(Config, self)._after_existing_assignment(
            key,
            value,
            origin=origin,
        )
        if key not in self._owner_field_names():
            return
        self._set_field_origin(
            key,
            ConfigOriginState(
                origin,
                env_key=self._config_owner().env_key(key),
            ),
        )

    def _warn_skipped_python_fields(self, field_names: list[str]) -> None:
        """Warn when env binding leaves Python-owned fields untouched."""
        if not field_names:
            return
        joined = ", ".join(sorted(field_names))
        LOG.warning(
            "Preserving Python-provided config field(s) during env binding for "
            f"{self.__class__.__name__}: {joined}. Pass "
            "override_python_values=True to reload() or bind_from_env() when "
            "the current process environment should replace them."
        )

    def _truncate_prefix(self, s: str) -> str:
        """Remove the owner env prefix from ``s`` when present."""
        prefix = self._config_owner().env_prefix
        return s[len(prefix) :] if s.startswith(prefix) else s

    def truncate_prefix_from_env(
        self, proc_env: dict[str, str], log: bool = True
    ) -> dict[str, str]:
        """Add unprefixed aliases for keys starting with the owner prefix.

        Useful when a dependency expects generic keys (for example ``PORT``)
        but your process env stores namespaced versions.
        """
        _proc_env = proc_env.copy()
        truncated_keys = []
        prefix = self._config_owner().env_prefix
        for k, v in list(_proc_env.items()):
            if k.startswith(prefix):
                _proc_env[self._truncate_prefix(k)] = v
                truncated_keys.append(k)
        if log:
            LOG.info(
                f"Truncated env var keys by prefix '{prefix}': {truncated_keys}"
            )
        return _proc_env

    def current_env_mapping(
        self,
        *,
        prefixed: bool = True,
        include_empty: bool = False,
    ) -> dict[str, str]:
        """Serialize current env-backed fields into concrete env key/value pairs."""
        owner = self._config_owner()
        if self._apprc_imported_field_names is not None:
            fields = tuple(
                spec
                for spec in owner.fields
                if spec.name in self._apprc_imported_field_names
            )
            if self._apprc_imported_binding is not None:
                parent_prefix = (
                    self._apprc_imported_binding.parent_owner.env_prefix
                )
                fields = tuple(
                    replace(
                        spec,
                        env_var=spec.env_var.removeprefix(parent_prefix),
                    )
                    for spec in fields
                )
                owner = replace(
                    owner,
                    env_prefix=parent_prefix,
                    fields=fields,
                )
            else:
                owner = replace(owner, fields=fields)
        return owner_env_mapping(
            owner,
            self,
            prefixed=prefixed,
            include_empty=include_empty,
        )


__all__ = [
    "Config",
    "ConfigBase",
]
