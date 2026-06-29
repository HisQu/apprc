"""Common CLI option metadata."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import Annotated, TypeAlias

# == 3rd Party ===============================
import typer

COMMON_ROOT_FLAG_OPTIONS = frozenset(
    {
        "--env-file-overrides-os-environ",
        "-o",
        "--skip-dotenv-layers",
        "-s",
    }
)
COMMON_ROOT_VALUE_OPTIONS = frozenset(
    {
        "--env-file",
        "--log-level",
        "--storage",
    }
)

EnvFilesOption: TypeAlias = Annotated[
    list[Path] | None,
    typer.Option(
        "--env-file",
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
        help=(
            "Let --env-file values override existing process env values "
            "inside this process."
        ),
    ),
]
SkipDotenvLayersOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--skip-dotenv-layers",
        "-s",
        help=(
            "Select storage but do not merge packaged, storage-local, or "
            "explicit dotenv values into the process env."
        ),
    ),
]
StorageOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--storage",
        help=(
            "Storage selector for this invocation. Registered names resolve "
            "through the AppRC TOML index when one is active."
        ),
    ),
]
LogLevelOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        help="Configure logging before runtime bootstrap.",
    ),
]
