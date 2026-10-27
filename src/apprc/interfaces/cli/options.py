"""Common CLI option metadata."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Annotated, TypeAlias

# == 3rd Party ===============================
import typer

COMMON_CLI_FLAG_OPTIONS = frozenset(
    {
        "--env-file-overrides-os-environ",
        "-o",
        "--skip-dotenv-layers",
        "-s",
    }
)
COMMON_CLI_VALUE_OPTIONS = frozenset(
    {
        "--env-file",
        "--log-level",
        "--workspace",
        "--layout",
        "--app-root",
    }
)

EnvFilesOption: TypeAlias = Annotated[
    list[Path] | None,
    typer.Option(
        "--env-file",
        rich_help_panel="Maintenance",
        help=(
            "Load dotenv values from this file before runtime config. "
            "May be repeated."
        ),
    ),
]
EnvFileOverridesOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--env-file-overrides-os-environ",
        "-o",
        rich_help_panel="Maintenance",
        help=(
            "Let --env-file values override existing process env values "
            "in the resolved configuration."
        ),
    ),
]
SkipDotenvLayersOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--skip-dotenv-layers",
        "-s",
        rich_help_panel="Maintenance",
        help="Exclude managed dotenv values from settings.",
    ),
]
WorkspaceOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--workspace",
        rich_help_panel="Maintenance",
        help="Registered workspace name or direct filesystem path.",
    ),
]
LayoutOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--layout",
        help="Select the native or single-root layout.",
        rich_help_panel="Maintenance",
    ),
]
AppRootOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--app-root",
        help="Root directory for single-root layout.",
        rich_help_panel="Maintenance",
    ),
]
LogLevelOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        rich_help_panel="Maintenance",
        help="Configure logging before runtime resolution.",
    ),
]
