"""Shared behavior for AppRC runtime config objects."""

from __future__ import annotations

# == Stdlib =============================
import logging
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

# == Typing ===============================
from types import ModuleType
from typing import Any, Literal, Mapping, Self

# == Internal ================================
import apprc.runtime.provenance as provenance_api
import apprc.definition.env_config._state_transfer as state_transfer
import apprc.definition.env_config._post_env_overrides as post_env_overrides
from apprc._dotenv_guard import (
    _disable_dotenv_autoload as _disable_dotenv_autoload,
)

LOG = logging.getLogger(__name__)


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

    _apprc_provenance_origins: dict[
        str,
        provenance_api.ConfigOriginState,
    ] = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"internal": True},
    )

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        """Create an instance while recording constructor provenance.

        Dataclass ``__init__`` stores values after ``__new__`` returns, so the
        constructor argument inventory must be captured before normal field
        assignment erases which values were omitted and which were explicit.

        :param args: Positional constructor arguments.
        :param kwargs: Keyword constructor arguments.
        :return: New config instance with initial provenance state.
        """
        # ! Keep two-argument super(): slotted dataclass inheritance on
        # ! Python 3.12/3.13 breaks zero-argument super().
        self = super(BaseConfig, cls).__new__(cls)
        object.__setattr__(
            self,
            "_apprc_provenance_origins",
            provenance_api.constructor_field_origins(cls, args, kwargs),
        )
        return self

    # ===========================================================
    # -- Persistent overrides
    # ===========================================================

    @classmethod
    def create_or_update(
        cls, cfg: Self | None = None, **overrides: Any
    ) -> Self:
        """Return an effective persistent config instance.

        This helper supports library-style constructors that accept both an
        existing config object and top-level convenience parameters. When
        ``cfg`` is absent, a new config is constructed from current defaults,
        env binding, and non-``None`` constructor overrides. When ``cfg`` is
        provided, non-``None`` overrides are assigned to that existing instance
        and intentionally persist for that object's lifetime.

        Use :meth:`scoped` for request-local overrides that must not mutate an
        existing config instance.

        :param cfg: Existing config instance to update, or ``None`` to build one.
        :param overrides: Field-name overrides. ``None`` means no override.
        :return: Created or updated persistent config instance.
        :raises KeyError: If an override names a non-public config field.
        """
        return post_env_overrides.create_or_update(cls, cfg, **overrides)

    # ===========================================================
    # -- Implementation
    # ===========================================================

    # ===========================================================
    # -- Mutation warning system
    # ===========================================================

    def __setattr__(self, key, value):
        """Assign one attribute and log post-init config mutations.

        Callers should normally use plain assignment so this hook can record the
        mutation. New attributes set during construction are quiet. Reassigning
        an existing attribute logs a warning. Use ``object.__setattr__`` only
        inside config internals that intentionally bypass runtime mutation
        logging.
        """
        existed = state_transfer.has_instance_attr(self, key)
        if not existed:
            object.__setattr__(self, key, value)
            return
        self._assign_existing_value(
            key,
            value,
            origin="python_runtime_assignment",
        )
        val = self._format_field_value_for_log(key, value)
        LOG.warning(f"Config modified: {self.__class__.__name__}.{key} = {val}")

    def _assign_existing_value(
        self,
        key: str,
        value: Any,
        *,
        origin: provenance_api.PythonProvenanceOrigin,
    ) -> None:
        """Store an existing value and record its Python lifecycle origin.

        :param key: Runtime attribute name.
        :param value: Candidate replacement value.
        :param origin: Python lifecycle event that owns the new value.
        """
        self._validate_existing_assignment(key, value)
        object.__setattr__(self, key, value)
        self._after_existing_assignment(key, value, origin=origin)

    def _validate_existing_assignment(self, key: str, value: Any) -> None:
        """Validate a post-init assignment before storing it.

        Subclasses override this when assignment has domain-specific invariants.

        :param key: Runtime attribute name.
        :param value: Candidate replacement value.
        """

    def _after_existing_assignment(
        self,
        key: str,
        value: Any,
        *,
        origin: provenance_api.PythonProvenanceOrigin,
    ) -> None:
        """Record subclass-specific state after a post-init assignment.

        :param key: Runtime attribute name.
        :param value: Replacement value already stored on the instance.
        :param origin: Python lifecycle event that owns the new value.
        """
        if key not in {
            item.name for item in provenance_api.public_config_fields(self)
        }:
            return
        provenance_api.set_field_origin(
            self,
            key,
            provenance_api.ConfigOriginState(origin),
        )

    def _format_field_value_for_log(self, key: str, value: Any) -> str:
        """Return ``repr(value)`` unless the dataclass field is redacted."""
        field_def = next((f for f in fields(self) if f.name == key), None)
        if field_def is not None and not field_def.repr:
            return "<redacted>"
        return repr(value)

    # ===========================================================
    # -- Copying
    # ===========================================================

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
        clone = state_transfer.shallow_clone(self)
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
        result = state_transfer.deepcopy_with_log_signal(self, memo)
        if result.should_log:
            self._log_copy("deepcopy")
        return result.clone

    # ===========================================================
    # -- Scoped overrides
    # ===========================================================

    def scoped(
        self,
        overrides: Mapping[str, Any] | None = None,
        /,
        *,
        skip_none: bool = True,
        **kwargs: Any,
    ) -> Self:
        """Return a request-local clone with public field overrides applied.

        Scoped overrides are for per-call or per-task effective config. They
        deep-copy the current resolved state, validate through the same hooks as
        direct assignment, record ``python_scoped_override`` provenance, and
        leave this config unchanged.

        :param overrides: Optional mapping of public field-name overrides.
        :param skip_none: Whether ``None`` values mean no override.
        :param kwargs: Additional public field-name overrides; these win over
            ``overrides``.
        :return: Cloned config with scoped override values applied.
        :raises KeyError: If an override names a non-public config field.
        """
        return post_env_overrides.scoped(
            self,
            overrides,
            skip_none=skip_none,
            kwargs=kwargs,
        )

    def scoped_from(
        self,
        values: Mapping[str, Any],
        /,
        *,
        skip_none: bool = True,
    ) -> Self:
        """Return a scoped clone from a larger local-value mapping.

        This convenience method is intended for inventories such as
        ``locals()``. Non-config names are ignored; known public field names are
        delegated to :meth:`scoped`.

        :param values: Mapping that may contain public config field names.
        :param skip_none: Whether ``None`` values mean no override.
        :return: Cloned config with matching scoped override values applied.
        """
        return post_env_overrides.scoped_from(
            self,
            values,
            skip_none=skip_none,
        )

    # ===========================================================
    # -- Provenance
    # ===========================================================

    def provenance_of(
        self,
        field_name: str,
    ) -> provenance_api.ConfigProvenance:
        """Return provenance metadata for one public config field.

        :param field_name: Runtime dataclass field name.
        :return: Resolved provenance metadata.
        :raises KeyError: If ``field_name`` is not public config state.
        """
        return provenance_api.provenance_of(self, field_name)

    def provenance(self) -> dict[str, provenance_api.ConfigProvenance]:
        """Return provenance metadata for all public config fields.

        :return: Mapping from field name to provenance metadata.
        """
        return provenance_api.provenance(self)

    def _build_config_provenance(
        self,
        field_name: str,
    ) -> provenance_api.ConfigProvenance:
        """Build provenance for one public BaseConfig field.

        :param field_name: Runtime dataclass field name.
        :return: Resolved provenance metadata.
        """
        return provenance_api.base_config_provenance_of(self, field_name)

    # ===========================================================
    # -- Serialization
    # ===========================================================

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
