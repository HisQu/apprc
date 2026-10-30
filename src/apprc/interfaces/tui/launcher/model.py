"""Captured input and app-owned command declarations for the launcher."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from apprc.definition.installation import (
    InstallationError,
    InstallationInspection,
)
from apprc.definition.paths import AppPaths
from apprc.definition.resolution import ResolveOptions
from apprc.public.app_rc import AppRC


@dataclass(frozen=True, slots=True)
class LauncherContext:
    """One captured view used by launcher actions and config management.

    :param apprc: Host application declaration.
    :param spec: Host-owned action declarations.
    :param options: Captured path-selection controls.
    :param environment: Immutable invocation environment.
    :param paths: Resolved captured paths, unavailable when authority is unsafe.
    :param cwd: External working directory captured at invocation.
    :param path_error: Original placement failure shown without invalidating the record.
    """

    apprc: AppRC
    spec: LauncherSpec
    options: ResolveOptions
    environment: Mapping[str, str]
    inspection: InstallationInspection
    paths: AppPaths | None
    cwd: Path
    path_error: str | None = None


LauncherHandler = Callable[[LauncherContext, bool], Awaitable[object] | object]


@dataclass(frozen=True, slots=True)
class LauncherAction:
    """One application-owned command presented on the launcher home screen.

    :param id: Stable action ID used only within this app-owned spec.
    :param label: User-visible action label.
    :param argv: Argument-vector factory; no shell command is accepted.
    :param interactive: Whether the child needs terminal foreground control.
    :param group: Home-screen grouping for primary and project actions.
    """

    id: str
    label: str
    argv: Callable[[LauncherContext, bool], Sequence[str]]
    interactive: bool = True
    group: Literal["main", "project"] = "main"

    def __post_init__(self) -> None:
        """Reject ambiguous identifiers and empty visible labels."""
        if not self.id or not self.id.isidentifier():
            raise ValueError(
                "Launcher action IDs must be non-empty identifiers."
            )
        if not self.label.strip():
            raise ValueError("Launcher action labels must not be empty.")


@dataclass(frozen=True, slots=True)
class LauncherSpec:
    """App-owned launcher actions; no global lifecycle registry is involved.

    :param actions: Primary and project commands declared by the application.
    :param title: Optional title shown on the home screen.
    """

    actions: tuple[LauncherAction, ...] = ()
    title: str = "Application launcher"

    def __post_init__(self) -> None:
        """Reject duplicate action IDs before the UI is created."""
        identifiers = tuple(action.id for action in self.actions)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Launcher action IDs must be unique.")


@dataclass(frozen=True, slots=True)
class _SavedUninstallRequested:
    """Mark Textual completion after the authored saved entry handshakes."""


_SAVED_UNINSTALL_REQUESTED = _SavedUninstallRequested()


def run_launcher(
    apprc: AppRC,
    *,
    spec: LauncherSpec,
    options: ResolveOptions | None = None,
    environment: Mapping[str, str] | None = None,
    handlers: Mapping[str, LauncherHandler] | None = None,
) -> None:
    """Run one Textual launcher using captured paths and installation state.

    An invalid or pending receipt remains visible as diagnostics but never
    produces substitute resource paths. Ordinary business config resolution is
    not performed; a missing business setting therefore does not prevent access
    to management actions.

    :param apprc: Host application declaration.
    :param spec: App-owned actions to display and execute.
    :param options: Invocation controls used only to capture declared paths.
    :param environment: Optional exact environment snapshot.
    :param handlers: Optional app-owned handlers keyed by action ID.
    """
    from apprc.interfaces.tui.launcher.app import LauncherApp

    cwd = Path.cwd()

    captured_environment = MappingProxyType(
        dict(os.environ if environment is None else environment)
    )
    selected_options = options or ResolveOptions()
    installation = apprc.installation(environment=captured_environment)
    inspection = installation.inspect()
    paths: AppPaths | None = None
    path_error: str | None = None
    if inspection.status in {"missing", "ready", "removed-retained"}:
        try:
            paths = apprc.paths(
                selected_options, environment=captured_environment
            )
        except InstallationError as error:
            # > Preserve why placement is unusable without manufacturing paths.
            path_error = str(error)
    context = LauncherContext(
        apprc=apprc,
        spec=spec,
        options=selected_options,
        environment=captured_environment,
        inspection=inspection,
        paths=paths,
        cwd=cwd,
        path_error=path_error,
    )
    app = LauncherApp(context=context, handlers=handlers or {})
    result = app.run()
    if result is _SAVED_UNINSTALL_REQUESTED:
        raise SystemExit(0)
