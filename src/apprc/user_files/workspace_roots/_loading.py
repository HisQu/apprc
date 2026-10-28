"""Read workspace registries from the captured AppRC config path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths
from apprc.user_files.app_home.application import AppFiles
from apprc.user_files.app_home.locations import AppRCDirectoryError
from apprc.user_files.workspace_roots._io import (
    load_workspace_registry_or_empty,
)
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.paths import resolve_workspace_root_path


class MissingWorkspaceRegistryError(ValueError):
    """A registry-backed workspace declaration has no ``apprc.toml`` file."""


@dataclass(frozen=True, slots=True)
class WorkspaceRegistryInspection:
    """Workspace registry state discovered without filesystem writes.

    :param path: Fixed ``apprc.toml`` path.
    :param env_value: Optional selector environment value retained for diagnostics.
    :param exists: Whether the TOML file exists.
    :param error: Read or schema error.
    :param registry: Parsed registry when valid.
    :param workspace_count: Number of live workspace records.
    :param issues: Runtime-blocking findings.
    :param warnings: Non-blocking findings.
    """

    path: Path
    env_value: str | None
    exists: bool
    error: str | None
    registry: WorkspaceRegistry | None
    workspace_count: int
    issues: list[str]
    warnings: list[str]

    @property
    def parse_ok(self) -> bool:
        """Return whether an existing AppRC TOML parsed successfully."""
        return self.error is None


def apprc_toml_path_for_create(
    spec: AppConfigSpec,
    app_paths: AppPaths,
) -> Path:
    """Return the fixed AppRC TOML path for a workspace registry write.

    :param spec: Application declaration with registry-backed workspaces.
    :param app_paths: Captured resolved paths for this invocation.
    :return: AppRC TOML path in the enabled configuration directory.
    """
    workspaces = spec.require_workspaces()
    if not workspaces.registry:
        raise ValueError("Workspace registry is disabled.")
    return AppFiles(spec, app_paths).config_file()


def load_create_or_empty_workspace_registry(path: Path) -> WorkspaceRegistry:
    """Read an existing registry or return an empty one for writes."""
    try:
        return load_workspace_registry_or_empty(path)
    except OSError as exc:
        raise _apprc_toml_read_error(path, exc) from exc


def load_existing_workspace_registry(
    spec: AppConfigSpec,
    *,
    app_paths: AppPaths,
    config_group_name: str = "config",
) -> WorkspaceRegistry:
    """Read the required registry for a registry-backed workspace declaration."""
    path = apprc_toml_path_for_create(spec, app_paths)
    if not path.is_file():
        raise MissingWorkspaceRegistryError(
            f"Workspace registry does not exist: {path}. Create it with `"
            f"{spec.config_command_name()} {config_group_name} setup` or `"
            f"{spec.config_command_name()} {config_group_name} workspace add "
            "NAME ROOT`."
        )
    return load_create_or_empty_workspace_registry(path)


def load_optional_runtime_workspace_registry(
    spec: AppConfigSpec,
    *,
    app_paths: AppPaths,
) -> WorkspaceRegistry | None:
    """Read a registry only when declared and configured for workspaces."""
    if not spec.uses_workspaces():
        return None
    workspaces = spec.require_workspaces()
    if not workspaces.registry:
        return None
    path = apprc_toml_path_for_create(spec, app_paths)
    if not path.is_file():
        return None
    return load_create_or_empty_workspace_registry(path)


def load_runtime_workspace_registry_for_selector(
    spec: AppConfigSpec,
    *,
    app_paths: AppPaths,
    raw_selector: str,
) -> WorkspaceRegistry | None:
    """Read a registry only when its declared capability enables one."""
    del raw_selector
    return load_optional_runtime_workspace_registry(spec, app_paths=app_paths)


def inspect_workspace_registry(
    spec: AppConfigSpec,
    *,
    app_paths: AppPaths,
    raw_selector: str | None = None,
) -> WorkspaceRegistryInspection:
    """Inspect registry state without creating or modifying files."""
    del raw_selector
    path = apprc_toml_path_for_create(spec, app_paths)
    exists = path.is_file()
    if not exists:
        return WorkspaceRegistryInspection(
            path=path,
            env_value=None,
            exists=False,
            error=None,
            registry=None,
            workspace_count=0,
            issues=[f"Workspace registry does not exist: {path}"],
            warnings=[],
        )
    try:
        registry = load_workspace_registry_or_empty(path)
    except (OSError, ValueError) as exc:
        message = f"AppRC TOML is invalid: {exc}"
        return WorkspaceRegistryInspection(
            path=path,
            env_value=None,
            exists=True,
            error=str(exc),
            registry=None,
            workspace_count=0,
            issues=[message],
            warnings=[],
        )
    return WorkspaceRegistryInspection(
        path=path,
        env_value=None,
        exists=True,
        error=None,
        registry=registry,
        workspace_count=len(registry.workspaces),
        issues=[],
        warnings=_duplicate_workspace_root_warnings(registry),
    )


def _duplicate_workspace_root_warnings(
    registry: WorkspaceRegistry,
) -> list[str]:
    """Return warnings for ambiguous aliases retained from earlier registries.

    :param registry: Parsed workspace registry.
    :return: One warning per root owned by multiple names.
    """
    names_by_root: dict[Path, list[str]] = {}
    for name, record in registry.workspaces.items():
        root = resolve_workspace_root_path(
            record.root,
            base=registry.path.parent,
        )
        names_by_root.setdefault(root, []).append(name)
    return [
        "Duplicate workspace root is registered under multiple names "
        f"({', '.join(sorted(names))}): {root}. Repoint or remove an alias."
        for root, names in sorted(
            names_by_root.items(), key=lambda item: item[0]
        )
        if len(names) > 1
    ]


def _apprc_toml_read_error(path: Path, exc: OSError) -> AppRCDirectoryError:
    """Return a domain error for an unreadable registry.

    :param path: Registry path that could not be read.
    :param exc: Filesystem failure.
    :return: Error suitable for CLI adapters.
    """
    return AppRCDirectoryError(
        f"AppRC-managed file could not be read: {Path(path).expanduser()}: {exc}"
    )
