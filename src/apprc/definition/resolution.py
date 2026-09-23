"""Explicit inputs and immutable source records for configuration loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Self

from apprc.definition.provenance import ConfigOriginState


@dataclass(frozen=True, slots=True)
class BundleFieldSpec:
    """Construction rules captured when an application registers a bundle.

    :param name: Bundle attribute name.
    :param config_type: Registered child section type.
    :param init: Whether the field accepts constructor injection.
    :param default_factory: Ordinary dataclass factory, when declared.
    """

    name: str
    config_type: type[object]
    init: bool
    default_factory: Callable[[], object] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveOptions:
    """Choose configuration sources for one invocation.

    :param storage: Registered storage name or initialized directory path.
    :param storage_required: Whether absence of a selection prevents loading.
    :param env_files: Explicit dotenv files, in increasing precedence order.
    :param env_file_overrides_os_environ: Whether explicit files beat the
        captured environment.
    :param load_dotenv_layers: Whether dotenv values participate in binding.
        Explicit files still participate in structural storage selection.
    :param apprc_dir: Invocation-local managed-directory override.
    """

    storage: str | None = None
    storage_required: bool = False
    env_files: tuple[Path, ...] = ()
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    apprc_dir: Path | None = None

    def __post_init__(self) -> None:
        """Copy caller-owned sequences without reading any filesystem state."""
        object.__setattr__(
            self, "env_files", tuple(Path(path) for path in self.env_files)
        )


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """Resolved raw inputs and their origins, shared by constructed sections.

    Copying the mappings prevents caller mutations from changing an existing
    resolution. Values are deliberately omitted from representations.

    :param values: Effective environment-key assignments.
    :param origins: Winning source for every effective assignment.
    """

    values: Mapping[str, str] = field(repr=False)
    origins: Mapping[str, ConfigOriginState] = field(repr=False)

    def __post_init__(self) -> None:
        """Detach and freeze the source mappings."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(
            self, "origins", MappingProxyType(dict(self.origins))
        )

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Reuse immutable source data when copying a mutable config object.

        :param memo: Active deep-copy object inventory.
        :return: This immutable snapshot.
        """
        memo[id(self)] = self
        return self
