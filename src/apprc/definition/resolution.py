"""Explicit inputs and immutable source records for configuration loading."""

from __future__ import annotations

import glob
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Generic, Protocol, Self, TypeVar

from apprc.definition.env_config.schema import ConfigOwner
from apprc.definition.paths import Layout
from apprc.definition.provenance import ConfigOriginState

ConfigTypeT = TypeVar("ConfigTypeT")


def resolve_editable_environment(project: Path) -> Path:
    """Select the existing environment for a PEP 621 project or uv member.

    Workspace environments are shared by their declared members. Matching the
    project against the workspace member patterns before selecting the root
    environment prevents an unrelated ancestor ``.venv`` from being treated as
    the application's environment.

    :param project: Selected project directory containing ``pyproject.toml``.
    :return: Canonical expected environment path, which may not exist yet.
    """
    selected = project.resolve(strict=True)
    if not (selected / "pyproject.toml").is_file():
        raise ValueError("Selected project has no pyproject.toml.")

    saw_workspace = False
    for candidate in selected.parents:
        metadata_path = candidate / "pyproject.toml"
        if not metadata_path.is_file():
            continue
        with metadata_path.open("rb") as stream:
            document = tomllib.load(stream)
        tool = document.get("tool", {})
        uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
        workspace = uv.get("workspace", {}) if isinstance(uv, dict) else {}
        if not isinstance(workspace, dict):
            raise ValueError("tool.uv.workspace must be a table.")
        members = workspace.get("members", [])
        excludes = workspace.get("exclude", [])
        if (
            not isinstance(members, list)
            or not all(isinstance(item, str) for item in members)
            or not isinstance(excludes, list)
            or not all(isinstance(item, str) for item in excludes)
        ):
            raise ValueError(
                "uv workspace members and excludes must be strings."
            )
        patterns = (*members, *excludes)
        for pattern in patterns:
            path = PurePosixPath(pattern)
            if (
                not pattern
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in pattern
                or PureWindowsPath(pattern).drive
            ):
                raise ValueError(f"Unsafe uv workspace pattern: {pattern}.")
        saw_workspace = saw_workspace or bool(members)
        if not members:
            continue
        relative = selected.relative_to(candidate).as_posix()
        member_matches = {
            Path(match).resolve(strict=False)
            for pattern in members
            for match in glob.glob(str(candidate / pattern), recursive=True)
        }
        excluded_matches = {
            Path(match).resolve(strict=False)
            for pattern in excludes
            for match in glob.glob(str(candidate / pattern), recursive=True)
        }
        workspace_root = candidate.resolve()
        if any(
            not path.is_relative_to(workspace_root)
            for path in member_matches | excluded_matches
        ):
            raise ValueError(
                "A uv workspace pattern escapes its workspace root."
            )
        if selected in excluded_matches:
            raise ValueError(
                f"Selected project is excluded from its uv workspace: {relative}."
            )
        if selected in member_matches:
            return (candidate / ".venv").resolve(strict=False)

    with (selected / "pyproject.toml").open("rb") as stream:
        selected_document = tomllib.load(stream)
    selected_tool = selected_document.get("tool", {})
    selected_uv = (
        selected_tool.get("uv", {}) if isinstance(selected_tool, dict) else {}
    )
    selected_workspace = (
        selected_uv.get("workspace", {})
        if isinstance(selected_uv, dict)
        else {}
    )
    selected_project = selected_document.get("project")
    if not saw_workspace or (
        isinstance(selected_workspace, dict)
        and isinstance(selected_workspace.get("members"), list)
        and isinstance(selected_project, dict)
    ):
        return (selected / ".venv").resolve(strict=False)

    raise ValueError(
        "Selected project is not a declared member of a uv workspace."
    )


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
    :param dependency_control_env_keys: Dependency layout/root/workspace keys
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


def dependency_environment_exclusions(
    imported_configs: tuple[ImportedConfig[object], ...],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Return dependency keys and prefixes excluded from parent inputs.

    :param imported_configs: Parent-owned imports that define dependency keys.
    :return: Exact excluded keys and dependency prefixes.
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
    return excluded_keys, excluded_prefixes


def filter_dependency_environment(
    environment: Mapping[str, str],
    imported_configs: tuple[ImportedConfig[object], ...],
) -> dict[str, str]:
    """Remove imported dependency keys before parent input processing.

    :param environment: Captured process or file-derived environment values.
    :param imported_configs: Parent-owned imports that define dependency keys.
    :return: A new mapping without dependency-owned keys.
    """
    excluded_keys, excluded_prefixes = dependency_environment_exclusions(
        imported_configs
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

    :param workspace: Registered workspace name or initialized directory path.
    :param workspace_required: Whether absence of a selection prevents loading.
    :param env_files: Explicit dotenv files, in increasing precedence order.
    :param env_file_overrides_os_environ: Whether explicit files beat the
        captured environment.
    :param load_dotenv_layers: Whether dotenv values participate in binding.
        Explicit files still participate in structural workspace selection.
    :param layout: Invocation-local placement override.
    """

    workspace: str | None = None
    workspace_required: bool = False
    env_files: tuple[Path, ...] = ()
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    layout: Layout | None = None

    def __post_init__(self) -> None:
        """Copy caller-owned sequences without reading any filesystem state."""
        object.__setattr__(
            self, "env_files", tuple(Path(path) for path in self.env_files)
        )


class CliRuntimeOptionsProtocol(Protocol):
    """Fields accepted by AppRC CLI runtime helpers."""

    @property
    def env_files(self) -> Sequence[Path] | None: ...

    @property
    def env_file_overrides_os_environ(self) -> bool: ...

    @property
    def load_dotenv_layers(self) -> bool: ...

    @property
    def workspace(self) -> str | None: ...

    @property
    def layout(self) -> Layout | None: ...

    @property
    def log_level(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class CliRuntimeOptions:
    """Parsed AppRC runtime options for one CLI invocation."""

    env_files: tuple[Path, ...] = ()
    env_file_overrides_os_environ: bool = False
    load_dotenv_layers: bool = True
    workspace: str | None = None
    layout: Layout | None = None
    log_level: str | None = None

    @classmethod
    def from_typer(
        cls,
        *,
        env_files: Sequence[Path] | None = None,
        env_file_overrides_os_environ: bool = False,
        load_dotenv_layers: bool = True,
        workspace: str | None = None,
        layout: str | None = None,
        app_root: Path | None = None,
        log_level: str | None = None,
    ) -> CliRuntimeOptions:
        """Normalize CLI runtime controls, including paired layout inputs."""
        selected_layout = None
        if layout is not None or app_root is not None:
            mode = layout or (
                "single-root" if app_root is not None else "native"
            )
            if mode == "native":
                if app_root is not None:
                    raise ValueError(
                        "--app-root cannot be combined with --layout native."
                    )
                selected_layout = Layout.native()
            elif mode == "single-root":
                if app_root is None:
                    raise ValueError(
                        "--layout single-root requires --app-root."
                    )
                selected_layout = Layout.single_root(app_root)
            else:
                raise ValueError(f"Unsupported AppRC layout: {mode!r}.")
        return cls(
            env_files=tuple(env_files or ()),
            env_file_overrides_os_environ=env_file_overrides_os_environ,
            load_dotenv_layers=load_dotenv_layers,
            workspace=workspace,
            layout=selected_layout,
            log_level=log_level,
        )

    @classmethod
    def from_options(
        cls,
        options: CliRuntimeOptionsProtocol,
    ) -> CliRuntimeOptions:
        """Return an immutable copy of an option-like object."""
        if isinstance(options, cls):
            return options
        return cls(
            env_files=tuple(options.env_files or ()),
            env_file_overrides_os_environ=options.env_file_overrides_os_environ,
            load_dotenv_layers=options.load_dotenv_layers,
            workspace=options.workspace,
            layout=options.layout,
            log_level=options.log_level,
        )


@dataclass(frozen=True, slots=True)
class _BridgeRuntimeOptions:
    """Capture invocation options and the actual mounted maintenance group."""

    runtime: CliRuntimeOptions = CliRuntimeOptions()
    maintenance_group_name: str = "app"

    def __post_init__(self) -> None:
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]*", self.maintenance_group_name
            )
            is None
        ):
            raise ValueError(
                "maintenance_group_name must be one CLI command name."
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
