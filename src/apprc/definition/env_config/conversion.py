"""Typed conversion shared by runtime binding and managed-value validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typed_settings as ts
from typed_settings.dict_utils import set_path
from typed_settings.types import LoadedSettings, LoaderMeta

from apprc.definition.env_config.schema import ConfigField, ConfigOwner


class OwnerMappingLoader:
    """Load one owner from an env-like mapping using explicit field env names."""

    def __init__(
        self,
        owner: ConfigOwner,
        values: Mapping[str, str],
        *,
        source_name: str,
        base_dir: Path | None = None,
    ) -> None:
        """Store one low-level source.

        :param owner: Owner whose field names should be mapped.
        :param values: Full env-key to string value mapping.
        :param source_name: Human-readable source name for diagnostics.
        :param base_dir: Base directory passed to typed-settings metadata.
        """
        self.owner = owner
        self.values = values
        self.source_name = source_name
        self.base_dir = base_dir

    def __call__(self, settings_cls: type[Any], options: Any) -> LoadedSettings:
        """Return values for options known to this owner."""
        loaded: dict[str, Any] = {}
        for option in options:
            env_key = self.owner.env_key(option.name)
            if env_key in self.values:
                set_path(loaded, option.path, self.values[env_key])
        return LoadedSettings(
            loaded,
            LoaderMeta(self.source_name, base_dir=self.base_dir),
        )


def load_owner_from_sources(
    owner: ConfigOwner,
    sources: tuple[OwnerMappingLoader, ...],
) -> Any:
    """Load one owner with ``typed-settings``.

    :param owner: Owner spec to load.
    :param sources: Ordered sources from low to high precedence.
    :return: A generated settings dataclass instance.
    """
    return ts.load_settings(
        owner.settings_class(),
        sources,
        converter=ts.default_converter(resolve_paths=False),
    )


def parse_env_field_value(spec: ConfigField, raw_value: str) -> Any:
    """Parse one dotenv string through the runtime settings converter.

    :param spec: Field whose declared Python type should be applied.
    :param raw_value: Raw string from a dotenv edit surface.
    :return: Parsed Python value.
    """
    owner = ConfigOwner(
        key=f"field.{spec.name}",
        title=spec.title or spec.name,
        env_prefix="",
        rc_path=(spec.name,),
        fields=(spec,),
    )
    loaded = load_owner_from_sources(
        owner,
        (
            OwnerMappingLoader(
                owner,
                {spec.env_var: raw_value},
                source_name="local-env-edit",
            ),
        ),
    )
    return getattr(loaded, spec.name)
