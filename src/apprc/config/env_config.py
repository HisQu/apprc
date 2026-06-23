"""Runtime base class for env-backed AppRC config sections."""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Mapping, Self

# == Internal ================================
from apprc.config.base_config import BaseConfig
from apprc.config.loading import (
    load_owner_from_env,
    owner_env_mapping,
    provided_owner_field_names,
)
from apprc.config.provenance import (
    CONFIG_FIELD_SOURCE_LABELS,
    ConfigFieldSource,
    ConfigFieldSourceKey,
)
from apprc.config.schema import ConfigOwner
from apprc.config.sentinels import CONFIG_MISSING, ENV_FIELD_MISSING
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
    _apprc_field_sources: dict[str, ConfigFieldSourceKey] = field(
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
        self = super().__new__(cls)
        python_arg_fields = cls._python_arg_field_names(args, kwargs)
        object.__setattr__(
            self,
            "_apprc_field_sources",
            {field_name: "python_arg" for field_name in python_arg_fields},
        )
        return self

    def __post_init__(self) -> None:
        """Resolve owner defaults, bind env values, and validate completeness."""
        self._resolve_owner_defaults()
        self._validate_python_fields()
        if self.bind_from_env_on_init:
            self.bind_from_env()
        self._validate_required_fields()
        self._validate_all_owner_choices()

    def reload(self, override_python_values: bool = False) -> None:
        """Re-bind owner-backed fields from current process ``os.environ``.

        Python constructor arguments and later Python assignments stay
        authoritative for the object lifetime by default. Pass
        ``override_python_values=True`` when the current process environment
        should deliberately replace those Python-provided values.

        :param override_python_values: Whether env values may overwrite
            ``python_arg`` and ``python_assignment`` fields.
        """
        LOG.warning(
            f"♻️  Reloading from os.environ: {self.__class__.__name__} ..."
        )
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
            provided through Python constructor arguments or later assignment.
        """
        self._bind_from_env(override_python_values=override_python_values)
        self._validate_required_fields()

    def _bind_from_env(self, override_python_values: bool) -> list[str]:
        """Bind env values and return Python-owned fields that were skipped."""
        owner = self._config_owner()
        binding_env, skipped_python_fields = self._env_values_for_binding(
            owner,
            override_python_values=override_python_values,
        )
        loaded = load_owner_from_env(owner, binding_env)
        provided_fields = provided_owner_field_names(owner, binding_env)
        for spec in owner.fields:
            if spec.name not in provided_fields or not hasattr(
                loaded,
                spec.name,
            ):
                continue
            loaded_value = getattr(loaded, spec.name)
            self._validate_owner_choice(owner, spec.name, loaded_value)
            object.__setattr__(self, spec.name, loaded_value)
            self._record_process_env_source(spec.name)
        return skipped_python_fields

    def source_of(self, field_name: str) -> ConfigFieldSource:
        """Return provenance metadata for one owner-backed field.

        :param field_name: Runtime dataclass field name.
        :return: Source metadata for the current field value.
        :raises KeyError: If ``field_name`` is not declared by this config owner.
        """
        owner = self._config_owner()
        spec = owner.field(field_name)
        env_key = owner.env_key(field_name)
        source = self._field_source(field_name)
        return ConfigFieldSource(
            field_name=field_name,
            source=source,
            label=CONFIG_FIELD_SOURCE_LABELS[source],
            env_key=env_key,
            value=getattr(self, field_name),
            secret=spec.secret,
        )

    def sources(self) -> dict[str, ConfigFieldSource]:
        """Return provenance metadata for all owner-backed fields.

        :return: Mapping from field name to source metadata.
        """
        return {
            spec.name: self.source_of(spec.name)
            for spec in self._config_owner().fields
        }

    # -----------------------------------------------------------------
    # -- Helpers
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

    @classmethod
    def _python_arg_field_names(
        cls,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> frozenset[str]:
        """Return owner-backed fields provided to the Python constructor.

        :param args: Positional constructor arguments passed to ``__new__``.
        :param kwargs: Keyword constructor arguments passed to ``__new__``.
        :return: Owner-backed field names supplied directly by Python code.
        """
        owner_field_names = cls._owner_field_names()
        positional_init_fields = [
            item.name for item in fields(cls) if item.init and not item.kw_only
        ]
        positional_names = set(positional_init_fields[: len(args)])
        keyword_names = set(kwargs)
        return frozenset((positional_names | keyword_names) & owner_field_names)

    def _field_source(self, field_name: str) -> ConfigFieldSourceKey:
        """Return the recorded source key or the implicit owner default."""
        self._config_owner().field(field_name)
        return self._apprc_field_sources.get(field_name, "owner_default")

    def _set_field_source(
        self,
        field_name: str,
        source: ConfigFieldSourceKey,
    ) -> None:
        """Record provenance for one owner-backed field."""
        next_sources = dict(self._apprc_field_sources)
        next_sources[field_name] = source
        object.__setattr__(self, "_apprc_field_sources", next_sources)

    def _resolve_owner_defaults(self) -> None:
        """Resolve omitted owner-backed fields from derived owner defaults."""
        owner = self._config_owner()
        dataclass_fields = {item.name: item for item in fields(self)}
        for spec in owner.fields:
            if self._field_source(spec.name) == "python_arg":
                continue
            field_def = dataclass_fields.get(spec.name)
            if field_def is None:
                raise RuntimeError(
                    f"{self.__class__.__name__}.{spec.name} is declared by "
                    f"{owner.key} but missing from the runtime dataclass."
                )
            if spec.default is CONFIG_MISSING:
                continue
            object.__setattr__(
                self,
                spec.name,
                self._deepcopy_state_value(spec.default, {}),
            )
            self._set_field_source(spec.name, "owner_default")

    def _validate_python_fields(self) -> None:
        """Validate constructor-provided values against owner metadata."""
        owner = self._config_owner()
        for field_name, source in self._apprc_field_sources.items():
            if source != "python_arg":
                continue
            self._validate_owner_choice(
                owner,
                field_name,
                getattr(self, field_name),
            )

    def _validate_required_fields(self) -> None:
        """Raise when required owner-backed fields remain unresolved."""
        owner = self._config_owner()
        missing_keys = [
            owner.env_key(spec.name)
            for spec in owner.fields
            if getattr(self, spec.name) is ENV_FIELD_MISSING
        ]
        if not missing_keys:
            return
        joined = ", ".join(missing_keys)
        raise RuntimeError(
            f"Missing required config value(s) for {self.__class__.__name__}: "
            f"{joined}. Provide Python constructor values or current-process "
            "os.environ values before constructing this config."
        )

    def _validate_all_owner_choices(self) -> None:
        """Validate resolved owner-backed values after all binding steps."""
        owner = self._config_owner()
        for spec in owner.fields:
            value = getattr(self, spec.name)
            if value is ENV_FIELD_MISSING:
                continue
            self._validate_owner_choice(owner, spec.name, value)

    def _validate_existing_assignment(self, key: str, value: Any) -> None:
        """Validate owner-backed assignment before storing it."""
        if key not in self._owner_field_names():
            return
        self._validate_owner_choice(self._config_owner(), key, value)

    def _after_existing_assignment(self, key: str, value: Any) -> None:
        """Record owner-backed assignment provenance after storing it."""
        if key not in self._owner_field_names():
            return
        self._record_python_assignment(key)

    def _record_python_assignment(self, field_name: str) -> None:
        """Record a post-construction assignment as a Python override."""
        if field_name not in self._owner_field_names():
            return
        self._set_field_source(field_name, "python_assignment")

    def _record_process_env_source(self, field_name: str) -> None:
        """Record that the current process environment owns one field."""
        self._set_field_source(field_name, "process_env")

    def _protected_field_names(self) -> frozenset[str]:
        """Return fields whose Python value should beat normal env binding."""
        return frozenset(
            field_name
            for field_name, source in self._apprc_field_sources.items()
            if source in {"python_arg", "python_assignment"}
        )

    def _env_values_for_binding(
        self,
        owner: ConfigOwner,
        *,
        override_python_values: bool,
    ) -> tuple[Mapping[str, str], list[str]]:
        """Return an env mapping with protected Python fields removed."""
        if override_python_values:
            return os.environ, []
        skipped_fields = sorted(
            provided_owner_field_names(owner, os.environ)
            & self._protected_field_names()
        )
        if not skipped_fields:
            return os.environ, []
        skipped_keys = {
            owner.env_key(field_name) for field_name in skipped_fields
        }
        return (
            {
                key: value
                for key, value in os.environ.items()
                if key not in skipped_keys
            },
            skipped_fields,
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

    @staticmethod
    def _validate_owner_choice(
        owner: ConfigOwner,
        field_name: str,
        value: Any,
    ) -> None:
        """Reject owner-backed values outside a declared choice set.

        :param owner: Config owner that declares the field.
        :param field_name: Owner-local field name.
        :param value: Candidate Python or env-loaded value.
        :raises ValueError: If the value is not one of the declared choices.
        """
        spec = owner.field(field_name)
        if (
            value is ENV_FIELD_MISSING
            or not spec.choices
            or value in spec.choices
        ):
            return
        choices = ", ".join(spec.choices)
        env_key = owner.env_key(field_name)
        raise ValueError(
            f"{env_key}={value!r} is invalid; {field_name} must be one of: "
            f"{choices}."
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
