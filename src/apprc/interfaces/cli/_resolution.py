"""Host CLI resolution helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

# == 3rd Party ===============================
import typer

# == Internal ================================
from apprc.definition.paths import AppPaths, Layout
from apprc.definition.resolution import ResolveOptions
from apprc.public.app_rc import AppRC
from apprc.runtime.logging import ResolutionLogger
from apprc.runtime.resolution import ResolvedConfig


def parse_log_level(log_level: str) -> str | int:
    """Convert a CLI log-level token into a logging backend value."""
    return int(log_level) if log_level.isdecimal() else log_level


def resolve_cli_config(
    apprc: AppRC,
    *,
    env_files: Sequence[Path],
    env_file_overrides_os_environ: bool,
    load_dotenv_layers: bool,
    workspace: str | None,
    workspace_required: bool = False,
    layout: Layout | None = None,
    environment: Mapping[str, str] | None = None,
    app_paths: AppPaths | None = None,
    log_level: str | None = None,
    setup_logging: Callable[..., Any] | None = None,
    logger: ResolutionLogger | None = None,
) -> ResolvedConfig:
    """Initialize logging and resolve settings against captured CLI inputs."""
    if setup_logging is not None and log_level is not None:
        setup_logging(level=parse_log_level(log_level))
    options = ResolveOptions(
        env_files=tuple(env_files),
        env_file_overrides_os_environ=env_file_overrides_os_environ,
        load_dotenv_layers=load_dotenv_layers,
        workspace=workspace,
        workspace_required=workspace_required,
        layout=layout,
    )
    snapshot = dict(os.environ if environment is None else environment)
    paths = app_paths or apprc.paths(options, environment=snapshot)
    try:
        resolved = apprc._resolve_with_paths(options, snapshot, paths)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if logger is not None:
        logger.info("AppRC resolved configuration for %s", apprc.schema.app_id)
    return resolved
