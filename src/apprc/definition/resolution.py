"""Explicit inputs and immutable source records for configuration loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Generic, Self, TypeVar

from apprc.definition.provenance import ConfigOriginState
from apprc.definition.env_config.schema import ConfigOwner

ConfigTypeT = TypeVar("ConfigTypeT")


@dataclass(frozen=True, slots=True, eq=False)
class ImportedConfig(Generic[ConfigTypeT]):
    """Parent-owned binding for one dependency config section.

    The handle keeps the dependency class separate from the parent-owned
    section owner used to resolve it. ``field_targets`` maps selected
    dependency fields to parent-owned fields; repeated values represent aliases.

    :param dependency_app_id: Dependency AppRC identity for diagnostics.
    :param config_type: Dependency config class built by this binding.
    :param parent_owner: Parent-owned fields exposed to resolution tools.
    :param dependency_owner: Dependency schema captured at import time.
    :param runtime_owner: Instance owner used when building the dependency.
    :param field_targets: Dependency field name to parent field name mapping.
    :param dependency_control_env_keys: Dependency storage and directory keys
        excluded from parent input.
    :param config_package: Optional dependency package for opted-in defaults.
    :param dependency_env_prefixes: Declared dependency field prefixes excluded
        from parent inputs.
    :param include_packaged_defaults: Whether to load selected dependency
        packaged defaults below the parent's packaged defaults.
    :param runtime_config_type: Config class used to build parent-redacted
        dependency instances when needed.
    """

    dependency_app_id: str
    config_type: type[ConfigTypeT]
    parent_owner: ConfigOwner
    dependency_owner: ConfigOwner
    runtime_owner: ConfigOwner
    field_targets: Mapping[str, str]
    dependency_env_prefixes: tuple[str, ...] = ()
    dependency_control_env_keys: tuple[str, ...] = ()
    config_package: str | None = None
    include_packaged_defaults: bool = False
    runtime_config_type: type[ConfigTypeT] | None = None

    def __post_init__(self) -> None:
        """Detach the field map from caller-owned mutable state."""
        object.__setattr__(
            self, "field_targets", MappingProxyType(dict(self.field_targets))
        )
        object.__setattr__(
            self,
            "dependency_env_prefixes",
            tuple(dict.fromkeys(self.dependency_env_prefixes)),
        )
        object.__setattr__(
            self,
            "dependency_control_env_keys",
            tuple(dict.fromkeys(self.dependency_control_env_keys)),
        )
        if self.runtime_config_type is None:
            object.__setattr__(self, "runtime_config_type", self.config_type)

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Keep this immutable binding's identity across runtime copies."""
        memo[id(self)] = self
        return self

    @property
    def dependency_env_keys(self) -> frozenset[str]:
        """Return dependency field keys that must stay out of parent inputs."""
        return frozenset(
            {
                self.dependency_owner.env_key(field_name)
                for field_name in self.field_targets
            }
            | set(self.dependency_control_env_keys)
        )


def filter_dependency_environment(
    environment: Mapping[str, str],
    imported_configs: tuple[ImportedConfig[object], ...],
) -> dict[str, str]:
    """Remove imported dependency keys before parent input processing.

    :param environment: Captured process or file-derived environment values.
    :param imported_configs: Parent-owned imports that define dependency keys.
    :return: A new mapping without dependency-owned keys.
    """
    excluded_keys = frozenset(
        key for item in imported_configs for key in item.dependency_env_keys
    )
    excluded_prefixes = tuple(
        dict.fromkeys(
            prefix
            for item in imported_configs
            for prefix in item.dependency_env_prefixes
        )
    )
    return {
        key: value
        for key, value in environment.items()
        if key not in excluded_keys
        and not any(key.startswith(prefix) for prefix in excluded_prefixes)
    }


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
    imported_config: ImportedConfig[object] | None = None


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
