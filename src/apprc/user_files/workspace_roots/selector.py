"""Resolve active workspace names and filesystem paths."""

from __future__ import annotations

# == Standard Library ===========================================
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == Internal ===================================================
from apprc.user_files.workspace_roots.model import WorkspaceRegistry
from apprc.user_files.workspace_roots.paths import resolve_workspace_root_path

_WINDOWS_DRIVE_SELECTOR_PATTERN = re.compile(r"^[A-Za-z]:")


class WorkspaceSelectorError(ValueError):
    """Readable workspace-selector failure with optional CLI context.

    :param message: Human-facing error text.
    :param param_hint: Optional Typer parameter hint for CLI callers.
    """

    def __init__(self, message: str, *, param_hint: str | None = None) -> None:
        """Store the message and CLI parameter hint."""
        super().__init__(message)
        self.param_hint = param_hint


class MissingWorkspaceSelectorError(WorkspaceSelectorError):
    """No CLI, process, explicit-dotenv, or registry selector was found."""


class WorkspaceNotInitializedError(WorkspaceSelectorError):
    """A selected filesystem root lacks a readable AppRC marker.

    :param message: Human-facing failure text.
    :param workspace_root: Root that setup may initialize.
    :param workspace_name: Associated registry name, when known.
    """

    def __init__(
        self,
        message: str,
        *,
        workspace_root: Path,
        workspace_name: str | None,
        param_hint: str | None = None,
    ) -> None:
        """Store recovery context with the selector error."""
        super().__init__(message, param_hint=param_hint)
        self.workspace_root = workspace_root
        self.workspace_name = workspace_name


type WorkspaceSelectorSourceKind = Literal[
    "cli",
    "process_environment",
    "explicit_dotenv",
    "registry",
]


@dataclass(frozen=True, slots=True)
class WorkspaceSelectorInput:
    """One raw selector together with the layer that supplied it.

    :param source: Existing user-facing source label.
    :param raw_value: Selector text before name or path resolution.
    :param source_kind: Layer that won selector precedence.
    """

    source: str
    raw_value: str
    source_kind: WorkspaceSelectorSourceKind


@dataclass(frozen=True, slots=True)
class WorkspaceSelectorIssue:
    """Selector failure retained for management interfaces.

    Runtime callers still receive :class:`WorkspaceSelectorError`. The config
    editor keeps this richer value so it can explain which input failed
    without treating the registry as damaged.

    :param selector: Raw selector and its winning layer.
    :param message: Resolution failure without interface formatting.
    :param configured_workspace: TOML fallback hidden by the failed override.
    """

    selector: WorkspaceSelectorInput | None
    message: str
    configured_workspace: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSelection:
    """Resolved active workspace selector.

    :param source: User-visible selector source.
    :param raw_value: Original selector value.
    :param workspace_name: Associated registered name, if exactly one exists.
    :param root: Resolved workspace root.
    :param selector_kind: Whether the selector is a name or path.
    :param matching_workspace_names: Registered aliases for a selected path.
    """

    source: str
    raw_value: str
    workspace_name: str | None
    root: Path
    selector_kind: Literal["name", "path"] = "name"
    matching_workspace_names: tuple[str, ...] = ()


def resolve_registered_workspace_name(
    *,
    registry: WorkspaceRegistry,
    name: str,
    source: str = "--workspace",
) -> WorkspaceSelection:
    """Resolve one registered workspace selector.

    :param registry: Parsed workspace registry.
    :param name: Workspace name selected by a CLI option or environment value.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved workspace selection.
    :raises WorkspaceSelectorError: If ``name`` is a path or is not registered.
    """
    selector = name.strip()
    if not selector:
        raise missing_workspace_selector_error("workspace selector")
    if workspace_selector_is_path_like(selector):
        raise WorkspaceSelectorError(
            f"{source} must contain a registered workspace name, not a path: "
            f"{selector!r}.",
            param_hint=source,
        )
    try:
        record = registry.selected(selector)
    except ValueError as exc:
        raise WorkspaceSelectorError(str(exc), param_hint=source) from exc
    return WorkspaceSelection(
        source=source,
        raw_value=selector,
        workspace_name=record.name,
        root=record.root,
        selector_kind="name",
        matching_workspace_names=(record.name,),
    )


def resolve_active_workspace_selection(
    *,
    registry: WorkspaceRegistry | None,
    apprc_toml_path: Path | None = None,
    workspace: str | None,
    workspace_selector_env_key: str,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str] | None = None,
    env_file_overrides_os_environ: bool = False,
) -> WorkspaceSelection | None:
    """Return the active workspace selected by CLI, env, or registry.

    ``--workspace`` always wins. The explicit-dotenv precedence option decides
    whether a selector from an explicit dotenv beats the process environment.
    ``selected_workspace`` is the final fallback.

    :param registry: Parsed workspace registry, when one exists.
    :param apprc_toml_path: Registry path used to resolve relative paths.
    :param workspace: Optional ``--workspace`` name or path.
    :param workspace_selector_env_key: Environment selector key.
    :param original_env: Process environment before dotenv loading.
    :param explicit_values: Values read from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        already exported process values.
    :return: Resolved selection, or ``None`` when no selector is configured.
    """
    selected = select_workspace_selector_input(
        workspace=workspace,
        original_env=original_env,
        explicit_values=explicit_values or {},
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        workspace_selector_env_key=workspace_selector_env_key,
        selected_workspace=(
            registry.selected_workspace if registry is not None else None
        ),
    )
    if selected is None:
        return None
    return resolve_workspace_selector_value(
        registry=registry,
        apprc_toml_path=apprc_toml_path,
        raw_value=selected.raw_value,
        workspace_selector_env_key=workspace_selector_env_key,
        source=selected.source,
    )


def resolve_workspace_selector_value(
    *,
    registry: WorkspaceRegistry | None,
    apprc_toml_path: Path | None = None,
    raw_value: str,
    workspace_selector_env_key: str,
    source: str | None = None,
) -> WorkspaceSelection:
    """Resolve one environment selector as a registered name or path.

    Exact registered names win over path classification. A path associated
    with exactly one registry entry reports that name. Duplicate aliases stay
    readable but make the direct path unassociated so callers cannot claim an
    arbitrary name.

    :param registry: Parsed workspace registry, when one exists.
    :param apprc_toml_path: Fixed registry path used to resolve relative paths.
    :param raw_value: Selector from process or explicit dotenv state.
    :param workspace_selector_env_key: Environment key used in errors.
    :param source: User-visible source shown in diagnostics.
    :return: Resolved named or path-backed workspace.
    """
    selector = raw_value.strip()
    selected_source = source or workspace_selector_env_key
    if not selector:
        raise missing_workspace_selector_error(workspace_selector_env_key)
    if registry is not None and selector in registry.workspaces:
        return resolve_registered_workspace_name(
            registry=registry,
            name=selector,
            source=selected_source,
        )
    if not workspace_selector_is_path_like(selector):
        if registry is None:
            raise ValueError("Named workspaces require a registry.")
        return resolve_registered_workspace_name(
            registry=registry,
            name=selector,
            source=selected_source,
        )

    if registry is None:
        root = resolve_workspace_root_path(selector, base=Path.cwd())
    else:
        registry_path = (
            registry.path if apprc_toml_path is None else apprc_toml_path
        )
        root = resolve_workspace_root_path(selector, base=registry_path.parent)
    matching_names = _matching_workspace_names(registry, root=root)
    return WorkspaceSelection(
        source=selected_source,
        raw_value=selector,
        workspace_name=(
            matching_names[0] if len(matching_names) == 1 else None
        ),
        root=root,
        selector_kind="path",
        matching_workspace_names=matching_names,
    )


def missing_workspace_selector_error(
    workspace_selector_env_key: str,
) -> MissingWorkspaceSelectorError:
    """Return the runtime error for a missing active workspace selector.

    :param workspace_selector_env_key: Environment selector key.
    :return: Error carrying CLI parameter context.
    """
    return MissingWorkspaceSelectorError(
        "No workspace is selected. Pass --workspace NAME_OR_PATH, export "
        f"{workspace_selector_env_key}=NAME_OR_PATH, or run config workspace "
        "select NAME.",
        param_hint=workspace_selector_env_key,
    )


def select_workspace_selector(
    *,
    workspace: str | None,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    workspace_selector_env_key: str,
    selected_workspace: str | None,
) -> tuple[str, str] | None:
    """Return the raw workspace selector selected by documented precedence.

    :param workspace: Optional host-level ``--workspace`` value.
    :param original_env: Process environment captured before dotenv loading.
    :param explicit_values: Values read from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        already exported process values.
    :param workspace_selector_env_key: Environment selector key.
    :param selected_workspace: Default name from ``apprc.toml``.
    :return: Source and selector value, or ``None`` when unset.
    """
    selected = select_workspace_selector_input(
        workspace=workspace,
        original_env=original_env,
        explicit_values=explicit_values,
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        workspace_selector_env_key=workspace_selector_env_key,
        selected_workspace=selected_workspace,
    )
    if selected is None:
        return None
    return selected.source, selected.raw_value


def select_workspace_selector_input(
    *,
    workspace: str | None,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
    workspace_selector_env_key: str,
    selected_workspace: str | None,
) -> WorkspaceSelectorInput | None:
    """Return the winning workspace selector and the layer that supplied it.

    :param workspace: Optional host-level ``--workspace`` value.
    :param original_env: Process environment captured before explicit dotenv
        loading.
    :param explicit_values: Values read from explicit dotenv files.
    :param env_file_overrides_os_environ: Whether explicit values beat the
        process environment.
    :param workspace_selector_env_key: Environment selector key.
    :param selected_workspace: Default name stored in ``apprc.toml``.
    :return: Winning selector input, or ``None`` when no layer selects one.
    """
    if workspace is not None:
        return WorkspaceSelectorInput("--workspace", workspace, "cli")

    process_value = original_env.get(workspace_selector_env_key)
    explicit_value = explicit_values.get(workspace_selector_env_key)
    ordered_values: tuple[
        tuple[str | None, WorkspaceSelectorSourceKind],
        tuple[str | None, WorkspaceSelectorSourceKind],
    ] = (
        (
            (explicit_value, "explicit_dotenv"),
            (process_value, "process_environment"),
        )
        if env_file_overrides_os_environ
        else (
            (process_value, "process_environment"),
            (explicit_value, "explicit_dotenv"),
        )
    )
    for raw_value, source_kind in ordered_values:
        if raw_value:
            return WorkspaceSelectorInput(
                workspace_selector_env_key,
                raw_value,
                source_kind,
            )
    if selected_workspace is not None:
        return WorkspaceSelectorInput(
            "apprc.toml selected_workspace",
            selected_workspace,
            "registry",
        )
    return None


def workspace_selector_is_path_like(value: str) -> bool:
    """Return whether selector text looks like a filesystem path.

    Names remain the default for bare words. Relative filesystem selectors
    therefore use explicit syntax such as ``./data`` or ``data/workspace``.

    :param value: Selector text.
    :return: Whether the value has path syntax.
    """
    path = Path(value).expanduser()
    return (
        value in {".", "..", "~"}
        or "/" in value
        or "\\" in value
        or path.is_absolute()
        or value.startswith("~/")
        or _WINDOWS_DRIVE_SELECTOR_PATTERN.match(value) is not None
    )


def _matching_workspace_names(
    registry: WorkspaceRegistry | None,
    *,
    root: Path,
) -> tuple[str, ...]:
    """Return registered names whose resolved root equals ``root``.

    :param registry: Parsed registry, when one exists.
    :param root: Resolved direct-path selector.
    :return: Sorted matching workspace names.
    """
    if registry is None:
        return ()
    return tuple(
        sorted(
            name
            for name, record in registry.workspaces.items()
            if resolve_workspace_root_path(
                record.root,
                base=registry.path.parent,
            )
            == root
        )
    )
