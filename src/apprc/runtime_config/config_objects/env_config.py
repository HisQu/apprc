"""Runtime base class for env-backed AppRC config sections."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self

# == Internal ================================
from apprc.runtime_config.config_objects.base_config import BaseConfig
from apprc.runtime_config._env_loading import (
    owner_env_mapping,
)
import apprc.runtime_config.config_objects._state_transfer as state_transfer
from apprc.runtime_config.config_objects._env_binding import bind_owner_from_env
from apprc.runtime_config.config_objects._env_defaults import (
    resolve_instance_owner_defaults,
)
from apprc.runtime_config.config_objects._env_origins import (
    origin_for_field,
    python_constructor_field_names,
    with_field_origin,
)
from apprc.runtime_config.config_objects._env_validation import (
    validate_all_owner_values,
    validate_owner_field_value,
    validate_python_constructor_fields,
    validate_required_fields,
)
from apprc.runtime_config.provenance import (
    ConfigOriginState,
    ConfigProvenance,
    PythonProvenanceOrigin,
    source_for_origin,
)
from apprc.runtime_config.contract.schema import ConfigOwner
from apprc.logging import get_logger

LOG = get_logger(__name__)


@dataclass(slots=True)
class EnvConfig(BaseConfig):
    """Runtime config section backed by a derived ``ConfigOwner``.

    Subclasses declare typed fields with ``env_field(...)`` and receive their
    owner schema through ``@env_owner(...)``. ``EnvConfig`` reads OS
    environment variables from the current Python process via ``os.environ``.
    It does not load dotenv files or application config layers; application
    entrypoints should call their bootstrap helper before constructing
    ``EnvConfig`` objects when they want dotenv layers merged into
    ``os.environ``.
    """

    config_owner: ClassVar[ConfigOwner | None] = None
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
        self = super().__new__(cls, *args, **kwargs)
        constructor_fields = python_constructor_field_names(
            cls,
            cls._config_owner(),
            args,
            kwargs,
        )
        object.__setattr__(
            self,
            "_apprc_field_origins",
            {
                field_name: ConfigOriginState(
                    "python_constructor_argument",
                    env_key=cls._config_owner().env_key(field_name),
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
            self.bind_from_env()
        validate_required_fields(self, self._config_owner())
        validate_all_owner_values(self, self._config_owner())

    # -----------------------------------------------------------
    # --- Logic for Reading from os.environ
    # -----------------------------------------------------------

    def reload(self, override_python_values: bool = False) -> None:
        """Re-bind owner-backed fields from current process ``os.environ``.

        Python constructor arguments, later Python assignments, and scoped
        overrides stay authoritative for the object lifetime by default. Pass
        ``override_python_values=True`` when the current process environment
        should deliberately replace those Python-provided values.

        :param override_python_values: Whether env values may overwrite
            ``python_constructor_argument`` and
            ``python_runtime_assignment`` and ``python_scoped_override`` fields.
        """
        LOG.warning(f"Reloading from os.environ: {self.__class__.__name__} ...")
        skipped_python_fields = self._bind_from_env(
            override_python_values=override_python_values
        )
        self._warn_skipped_python_fields(skipped_python_fields)

    def bind_from_env(self, override_python_values: bool = False) -> None:
        """Load owner-backed values from current process ``os.environ``.

        This does not load dotenv files or application config layers. Call the
        application bootstrap helper once at the entrypoint when those layers
        should populate ``os.environ`` before runtime configs are constructed.
        Owner defaults are always resolved; this method only controls whether
        process env values overlay those defaults.

        :param override_python_values: Whether env values may overwrite fields
            provided through Python constructor arguments, later assignment, or
            scoped overrides.
        """
        self._bind_from_env(override_python_values=override_python_values)
        validate_required_fields(self, self._config_owner())

    def _bind_from_env(self, override_python_values: bool) -> list[str]:
        """Bind env values and return Python-owned fields that were skipped."""
        owner = self._config_owner()
        result = bind_owner_from_env(
            owner,
            self._apprc_field_origins,
            override_python_values=override_python_values,
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
        if self.config_owner is None:
            return super()._build_config_provenance(field_name)
        owner = self._config_owner()
        try:
            spec = owner.field(field_name)
        except KeyError:
            return super()._build_config_provenance(field_name)
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
        )

    # -----------------------------------------------------------------
    # -- Implementation
    # -----------------------------------------------------------------

    @classmethod
    def _config_owner(cls) -> ConfigOwner:
        """Return the required owner spec for this config class."""
        if cls.config_owner is None:
            raise RuntimeError(
                f"{cls.__name__} must be decorated with @env_owner before "
                "env binding."
            )
        return cls.config_owner

    @classmethod
    def _owner_field_names(cls) -> frozenset[str]:
        """Return owner-backed runtime field names for this config class."""
        if cls.config_owner is None:
            return frozenset()
        return frozenset(spec.name for spec in cls._config_owner().fields)

    def _field_origin(self, field_name: str) -> ConfigOriginState:
        """Return the recorded origin state or the implicit EnvConfig default."""
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
        super()._after_existing_assignment(key, value, origin=origin)
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
        return owner_env_mapping(
            self._config_owner(),
            self,
            prefixed=prefixed,
            include_empty=include_empty,
        )
