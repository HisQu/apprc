"""Base classes for runtime config objects.

This module is the bridge between application dataclasses and AppRC's
normalized config inventory. Application code normally declares a
:class:`BaseEnv` subclass with :func:`apprc.config.schema.env_field` attributes
and decorates it with :func:`apprc.config.schema.env_owner`. AppRC derives the
owner schema from that class, then uses it to bind environment variables,
serialize public config state, and log surprising runtime mutations.

Keep this module focused on runtime config object behavior. File discovery,
multi-storage tables, dotenv layer precedence, and CLI editing live in sibling
modules so beginners can look up one problem at a time:

* :mod:`apprc.config.schema` owns env field authoring and owner derivation.
* :mod:`apprc.config.environment` owns entrypoint dotenv bootstrap.
* :mod:`apprc.config.app_spec` owns the optional AppRC TOML env contract.
* :mod:`apprc.config.storage.registry` owns optional multi-storage tables.
* :mod:`apprc.config.local_env` owns storage-local dotenv overrides.
"""

from __future__ import annotations

# == Stdlib =============================
import os
from copy import deepcopy as _deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from importlib import import_module
from pathlib import Path

# == Typing ===============================
from types import ModuleType
from typing import Any, ClassVar, Literal, Mapping, Self

# == Internal ================================
from apprc.logging import get_logger
from apprc._dotenv_guard import (
    _disable_dotenv_autoload as _disable_dotenv_autoload,
)
from apprc.config.schema import (
    CONFIG_MISSING,
    ENV_FIELD_MISSING,
    ConfigOwner,
    load_owner_from_env,
    owner_env_mapping,
    provided_owner_field_names,
)

LOG = get_logger(__name__)

_DEEPCOPY_LOG_DEPTH_KEY = ("apprc.config.base_config", "deepcopy_log_depth")

type ConfigFieldSourceKey = Literal[
    "python_arg",
    "python_assignment",
    "process_env",
    "owner_default",
]

_CONFIG_FIELD_SOURCE_LABELS: dict[ConfigFieldSourceKey, str] = {
    "python_arg": "Python argument",
    "python_assignment": "Python assignment",
    "process_env": "Process environment",
    "owner_default": "Owner default",
}


@dataclass(frozen=True, slots=True, repr=False)
class ConfigFieldSource:
    """Resolved source metadata for one env-backed config field.

    :param field_name: Runtime dataclass field name.
    :param source: Stable source key that explains why the current value won.
    :param label: Human-readable source label.
    :param env_key: Full OS environment variable key owned by the field.
    :param value: Current runtime value stored on the config object.
    :param secret: Whether display surfaces should redact this value.
    :param display_value: Redacted value for UIs, logs, and repr output.
    """

    field_name: str
    source: ConfigFieldSourceKey
    label: str
    env_key: str
    value: Any
    secret: bool = False
    display_value: Any = field(init=False)

    def __post_init__(self) -> None:
        """Store the safe display value for this immutable provenance record."""
        value = "<redacted>" if self.secret else self.value
        object.__setattr__(self, "display_value", value)

    def __repr__(self) -> str:
        """Return a debug representation that never prints secret raw values."""
        return (
            f"{self.__class__.__name__}("
            f"field_name={self.field_name!r}, "
            f"source={self.source!r}, "
            f"label={self.label!r}, "
            f"env_key={self.env_key!r}, "
            f"value={self.display_value!r}, "
            f"secret={self.secret!r}, "
            f"display_value={self.display_value!r})"
        )


def resolve_package_root(pkg: ModuleType | str) -> Path:
    """Return the filesystem directory for a regular (non-namespace) package.

    Requires an `__init__.py` on disk (i.e., rejects PEP 420 namespace packages).
    Intentionally fails for non-filesystem imports (frozen/zip/etc.).

    This prefers :attr:`module.__spec__.origin` (PEP 451)
    and falls back to :attr:`module.__file__` when needed.

    :param pkg: Imported package module or import path, e.g. ``your_app.rag``.
    :return: Package directory on disk.
    :raises RuntimeError: If no usable directory can be determined.
    """
    module = pkg if isinstance(pkg, ModuleType) else import_module(pkg)
    origin = None if module.__spec__ is None else module.__spec__.origin
    if isinstance(origin, str):
        origin_path = Path(origin)
        if origin_path.name == "__init__.py" and origin_path.is_file():
            return origin_path.resolve().parent
    module_file = getattr(module, "__file__", None)
    if module_file:
        module_path = Path(module_file).resolve()
        if module_path.name == "__init__.py" and module_path.is_file():
            return module_path.parent
    raise RuntimeError(
        f"Cannot determine package directory for {module.__name__!r}. "
        "Expected a regular package with an __init__.py on disk."
    )


# ===============================================================
# == Base Config Class
# ===============================================================


@dataclass(slots=True)
class BaseConfig:
    """Shared config behavior with explicit runtime mutation logging.

    Policy:
    - Normal attribute assignment is the default way to change config values at
      runtime.
    - Post-init reassignment is intentionally logged via ``__setattr__`` so
      callers can see when effective settings were mutated during execution.
    - Bypassing ``__setattr__`` with ``object.__setattr__`` suppresses that
      logging and should therefore be reserved for config internals only, such
      as early construction, env-binding bootstrapping, or sentinel bookkeeping.
    - Shallow and deep copies transfer already-resolved object state without
      calling constructors, re-reading ``os.environ``, or logging mutation
      warnings.
    - Copy operations emit a dedicated ``Config copied`` warning so cloned
      runtime configs stay visible without being confused with mutation.

    During initial dataclass construction we avoid warning noise, but any later
    reassignment to an existing instance attribute is logged.
    """

    # -----------------------------------------------------------------
    # -- Mutation warning system
    # -----------------------------------------------------------------
    @staticmethod
    def _slot_names(obj_type: type) -> set[str]:
        """Collect slot names from ``obj_type`` and all bases in MRO order.
        :param obj_type: Class to inspect for __slots__.
        """
        names: set[str] = set()
        for cls in obj_type.__mro__:
            slots = cls.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                names.add(slots)
                continue
            for name in slots:
                names.add(name)
        return names

    def _has_instance_attr(self, key: str) -> bool:
        """Return ``True`` only when ``key`` is already set on this instance.
        For regular instances this checks ``__dict__`` directly. For
        slotted instances it checks slot membership, then probes
        ``object.__getattribute__`` to distinguish "slot exists" from
        "slot has a value yet".
        """
        d = getattr(self, "__dict__", None)
        if isinstance(d, dict):
            # Non-slotted instances: ignore class/default attributes.
            return key in d
        if key in self._slot_names(type(self)):
            try:
                object.__getattribute__(self, key)
            except AttributeError:
                return False
            return True
        return False

    def _assigned_state_items(self) -> tuple[tuple[str, Any], ...]:
        """Return assigned instance state for lifecycle-neutral copying.

        Copying config objects is state transfer, not runtime mutation. This
        helper collects both dynamic ``__dict__`` attributes and assigned slot
        values so copy operations can bypass ``__setattr__`` centrally.

        :return: Assigned instance attributes as ``(name, value)`` pairs.
        """
        items: list[tuple[str, Any]] = []
        seen: set[str] = set()
        d = getattr(self, "__dict__", None)
        if isinstance(d, dict):
            for key, value in d.items():
                items.append((key, value))
                seen.add(key)
        for slot_name in self._slot_names(type(self)):
            if slot_name in {"__dict__", "__weakref__"} or slot_name in seen:
                continue
            try:
                value = object.__getattribute__(self, slot_name)
            except AttributeError:
                continue
            items.append((slot_name, value))
        return tuple(items)

    @staticmethod
    def _deepcopy_state_value(value: Any, memo: dict[Any, Any]) -> Any:
        """Deep-copy one state value while preserving process singletons.

        Module objects are not deepcopyable and represent imported process
        singletons, so config copies should keep them by identity.

        :param value: State value to copy.
        :param memo: Active ``copy.deepcopy`` memo.
        :return: Deep-copied value or identity-preserved singleton.
        """
        if isinstance(value, ModuleType):
            return value
        return _deepcopy(value, memo)

    def _log_copy(self, kind: Literal["copy", "deepcopy"]) -> None:
        """Log that this config object was copied.

        Copying is lifecycle-neutral state transfer, but it is still operationally
        useful to see when runtime configs are cloned. This message is distinct
        from ``Config modified`` warnings so copy visibility does not imply
        mutation.

        :param kind: Copy operation kind.
        """
        LOG.warning(f"Config copied: {self.__class__.__name__} ({kind})")

    def __copy__(self) -> Self:
        """Return a shallow config clone without logging mutations.

        Copy construction intentionally bypasses ``__init__``, ``__post_init__``,
        env binding, and ``__setattr__``. The clone receives the current
        resolved state exactly as stored on this instance, then emits one
        dedicated copy warning.

        :return: Shallow copy of this config object.
        """
        clone = object.__new__(type(self))
        for key, value in self._assigned_state_items():
            object.__setattr__(clone, key, value)
        self._log_copy("copy")
        return clone

    def __deepcopy__(self, memo: dict[Any, Any]) -> Self:
        """Return a deep config clone without logging mutations.

        Deep copying is lifecycle-neutral state transfer: it preserves the
        already-resolved config, honors recursive object graphs through
        ``memo``, and does not re-read process environment variables. One
        dedicated copy warning is logged for the top-level config object in a
        deep-copy graph.

        :param memo: Active ``copy.deepcopy`` memo.
        :return: Deep copy of this config object.
        """
        obj_id = id(self)
        if obj_id in memo:
            return memo[obj_id]
        depth = int(memo.get(_DEEPCOPY_LOG_DEPTH_KEY, 0))
        log_this_copy = depth == 0
        memo[_DEEPCOPY_LOG_DEPTH_KEY] = depth + 1
        try:
            clone = object.__new__(type(self))
            memo[obj_id] = clone
            for key, value in self._assigned_state_items():
                object.__setattr__(
                    clone,
                    key,
                    self._deepcopy_state_value(value, memo),
                )
        finally:
            next_depth = int(memo.get(_DEEPCOPY_LOG_DEPTH_KEY, 1)) - 1
            if next_depth > 0:
                memo[_DEEPCOPY_LOG_DEPTH_KEY] = next_depth
            else:
                memo.pop(_DEEPCOPY_LOG_DEPTH_KEY, None)
        if log_this_copy:
            self._log_copy("deepcopy")
        return clone

    def __setattr__(self, key, value):
        """Assign one attribute and log post-init config mutations.

        Callers should normally use plain assignment so this hook can record the
        mutation. New attributes set during construction are quiet. Reassigning
        an existing attribute logs a warning. Use ``object.__setattr__`` only
        inside config internals that intentionally bypass runtime mutation
        logging.
        """
        existed = self._has_instance_attr(key)
        if existed:
            self._validate_existing_assignment(key, value)
        object.__setattr__(self, key, value)
        if not existed:
            return
        self._after_existing_assignment(key, value)
        val = self._format_field_value_for_log(key, value)
        LOG.warning(f"Config modified: {self.__class__.__name__}.{key} = {val}")

    def _validate_existing_assignment(self, key: str, value: Any) -> None:
        """Validate a post-init assignment before storing it.

        Subclasses override this when assignment has domain-specific invariants.

        :param key: Runtime attribute name.
        :param value: Candidate replacement value.
        """

    def _after_existing_assignment(self, key: str, value: Any) -> None:
        """Record subclass-specific state after a post-init assignment.

        :param key: Runtime attribute name.
        :param value: Replacement value already stored on the instance.
        """

    def _format_field_value_for_log(self, key: str, value: Any) -> str:
        """Return ``repr(value)`` unless the dataclass field is redacted."""
        field_def = next((f for f in fields(self) if f.name == key), None)
        if field_def is not None and not field_def.repr:
            return "<redacted>"
        return repr(value)

    # -----------------------------------------------------------------
    # -- Serialization
    # -----------------------------------------------------------------

    @classmethod
    def _serialize_public_value(
        cls,
        value: Any,
    ) -> Any:
        """Turn dataclass fields into JSON-friendly public data."""
        if is_dataclass(value):
            return {
                f.name: cls._serialize_public_value(
                    "<redacted>" if not f.repr else getattr(value, f.name)
                )
                for f in fields(value)
                if not f.name.startswith("_") and not f.metadata.get("internal")
            }
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, ModuleType):
            return value.__name__
        if isinstance(value, Mapping):
            return {
                str(key): cls._serialize_public_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [cls._serialize_public_value(item) for item in value]
        if isinstance(value, set):
            return sorted(cls._serialize_public_value(item) for item in value)
        return value

    def to_dict(self) -> dict[str, Any]:
        """Serialize this config object into a JSON-friendly public mapping."""
        return {
            f.name: self._serialize_public_value(
                "<redacted>" if not f.repr else getattr(self, f.name)
            )
            for f in fields(self)
            if not f.name.startswith("_") and not f.metadata.get("internal")
        }


@dataclass(slots=True)
class BaseEnv(BaseConfig):
    """Runtime config section backed by a derived ``ConfigOwner``.

    Subclasses declare typed fields with ``env_field(...)`` and receive their
    owner schema through ``@env_owner(...)``. ``BaseEnv`` reads OS environment
    variables from the current Python process via ``os.environ``. It does not
    load dotenv files or application config layers; application entrypoints
    should call their bootstrap helper before constructing ``BaseEnv`` objects
    when they want dotenv layers merged into ``os.environ``.
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
            label=_CONFIG_FIELD_SOURCE_LABELS[source],
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
                f"{cls.__name__} must declare a ConfigOwner before env binding."
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
