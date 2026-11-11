"""Private validation and generated methods for registered bundles."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    NoReturn,
    cast,
    get_origin,
    get_type_hints,
)

from apprc.definition.resolution import BundleFieldSpec, ImportedConfig
from apprc.public.config import ConfigBase

if TYPE_CHECKING:
    from apprc.public.app_rc import RegisteredConfig

LOG = logging.getLogger("apprc")


def _bundle_fields(
    bundle_type: type[object],
    *,
    registered_by_type: Mapping[type[ConfigBase], RegisteredConfig],
    imported_configs: Sequence[ImportedConfig[Any]],
) -> dict[str, BundleFieldSpec]:
    """Return registered config fields declared by one bundle."""
    type_hints = get_type_hints(bundle_type, include_extras=True)
    dataclass_fields = {
        item.name: item for item in fields(cast(Any, bundle_type))
    }
    bundle_fields: dict[str, BundleFieldSpec] = {}
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
        registered = registered_by_type.get(annotation)
        imported_config = None
        if registered is None:
            candidates = [
                item
                for item in imported_configs
                if item.config_type is annotation
            ]
            if len(candidates) > 1:
                raise TypeError(
                    f"{bundle_type.__name__}.{field_name} refers to "
                    f"{annotation.__name__}, imported more than once. "
                    "Inject the desired imported config explicitly when "
                    "building the bundle."
                )
            imported_config = candidates[0] if candidates else None
        if registered is None and imported_config is None:
            _raise_unregistered_bundle_field(
                bundle_type,
                field_name,
                annotation,
            )
        if imported_config is not None:
            config_type = imported_config.config_type
        else:
            assert registered is not None
            config_type = registered.config_type
        bundle_fields[field_name] = BundleFieldSpec(
            name=field_name,
            config_type=config_type,
            init=dataclass_fields[field_name].init,
            default_factory=_bundle_default_factory(
                bundle_type=bundle_type,
                field_name=field_name,
                config_type=config_type,
                dataclass_field=dataclass_fields[field_name],
            ),
            imported_config=cast(
                ImportedConfig[object] | None, imported_config
            ),
        )
    return bundle_fields


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
    bundle_type: type[object],
    bundle_fields: Mapping[str, BundleFieldSpec],
    post_init: Callable[[object], None] | None,
    *,
    registered_by_type: Mapping[type[ConfigBase], RegisteredConfig],
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
                if spec.imported_config is not None:
                    raise TypeError(
                        f"{bundle_type.__name__}.{field_name} is imported "
                        "from a dependency and requires the parent "
                        "ResolvedConfig. Build the bundle with "
                        f"resolved.build({bundle_type.__name__})."
                    )
                assert issubclass(expected_type, ConfigBase)
                registered = registered_by_type[expected_type]
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

    return __init__


def _build_bundle_repr(
    bundle_type: type[object],
    bundle_fields: Mapping[str, BundleFieldSpec],
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
