"""Base classes for runtime config objects.

This module is the bridge between application dataclasses and AppRC's
declarative config inventory. Application code normally declares a dataclass
that inherits :class:`BaseEnv` and points it at a :class:`ConfigOwner`. AppRC
then uses the owner to bind environment variables, serialize public config
state, and log surprising runtime mutations.

Keep this module focused on runtime config object behavior. File discovery,
storage registries, dotenv layer precedence, and CLI editing live in sibling
modules so beginners can look up one problem at a time:

* :mod:`apprc.config.schema` owns field/owner declarations.
* :mod:`apprc.config.environment` owns entrypoint dotenv bootstrap.
* :mod:`apprc.config.apprc_toml` owns the AppRC TOML env contract.
* :mod:`apprc.config.storage_registry` owns storage tables in that TOML.
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
import apprc.utils as ut
from apprc.logging import get_logger
from apprc._dotenv_guard import (
    _disable_dotenv_autoload as _disable_dotenv_autoload,
)
from apprc.config.schema import (
    ConfigOwner,
    load_owner_from_env,
    owner_env_mapping,
    provided_owner_field_names,
)

LOG = get_logger(__name__)

_DEEPCOPY_LOG_DEPTH_KEY = ("apprc.config.base_config", "deepcopy_log_depth")


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
    return ut.package_root_dir(module)


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
        object.__setattr__(self, key, value)
        if not existed:
            return
        val = self._format_field_value_for_log(key, value)
        LOG.warning(f"Config modified: {self.__class__.__name__}.{key} = {val}")

    # -----------------------------------------------------------------
    # -- Wrappers
    # -----------------------------------------------------------------

    @staticmethod
    def resolve_package_root(pkg: ModuleType | str) -> Path:
        """Thin wrapper so subclasses can call the module helper as a method."""
        return resolve_package_root(pkg=pkg)

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
    """Runtime config section backed by a structured ``ConfigOwner``.

    ``BaseEnv`` intentionally knows only about structured owner metadata.
    Subclasses declare normal typed dataclass fields, while their
    :class:`apprc.config.schema.ConfigOwner` owns env names, docs metadata, and
    editor metadata.
    """

    config_owner: ClassVar[ConfigOwner | None] = None
    bind_from_env_on_init: bool = field(
        default=True,
        repr=False,
        kw_only=True,
        metadata={"internal": True},
    )

    def __post_init__(self) -> None:
        """Bind owner-backed fields from the current process env."""
        if self.bind_from_env_on_init:
            self.bind_from_env()

    def reload(self) -> None:
        """Re-bind owner-backed fields from the current process env."""
        LOG.warning(f"♻️  Reloading from .env: {self.__class__.__name__} ...")
        self.bind_from_env()

    def bind_from_env(self) -> None:
        """Load owner-backed values using ``typed-settings``."""
        owner = self._config_owner()
        loaded = load_owner_from_env(owner)
        provided_fields = provided_owner_field_names(owner, os.environ)
        for spec in owner.fields:
            if not hasattr(loaded, spec.name):
                continue
            if spec.name in provided_fields or not self._has_instance_attr(
                spec.name
            ):
                object.__setattr__(self, spec.name, getattr(loaded, spec.name))

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
