"""Common CLI option metadata."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypeAlias

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
        rich_help_panel="AppRC: Runtime Options",
        help=(
            "Load explicitly selected dotenv files in order for runtime "
            "configuration; later files take precedence over earlier files. "
            "Repeat the option to add more files."
        ),
    ),
]
EnvFileOverridesOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--env-file-overrides-os-environ",
        "-o",
        rich_help_panel="AppRC: Runtime Options",
        help=(
            "Let explicitly selected --env-file values override process "
            "environment values when resolving configuration."
        ),
    ),
]
SkipDotenvLayersOption: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--skip-dotenv-layers",
        "-s",
        rich_help_panel="AppRC: Runtime Options",
        help=(
            "Exclude dotenv layers from settings, including --env-file values; "
            "explicit files still participate in path and workspace selectors."
        ),
    ),
]
WorkspaceOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--workspace",
        rich_help_panel="AppRC: Runtime Options",
        help=(
            "Select a registered workspace by name or select a direct "
            "filesystem path."
        ),
    ),
]
LayoutOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--layout",
        help=(
            "Override the native or single-root layout for this invocation "
            "without changing the saved installation layout."
        ),
        rich_help_panel="AppRC: Runtime Options",
    ),
]
AppRootOption: TypeAlias = Annotated[
    Path | None,
    typer.Option(
        "--app-root",
        help=(
            "Select the single-root directory for this invocation; this "
            "option does not change the saved installation layout."
        ),
        rich_help_panel="AppRC: Runtime Options",
    ),
]
LogLevelOption: TypeAlias = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        rich_help_panel="AppRC: Runtime Options",
        help=(
            "Configure logging before application business settings are "
            "resolved."
        ),
    ),
]


if TYPE_CHECKING:
    import argparse


def native_runtime_parser() -> argparse.ArgumentParser:
    """Declare native selectors once for root capture and install validation.

    :return: Parser usable as a parent without consuming installer arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", action="append", type=Path)
    parser.add_argument(
        "--env-file-overrides-os-environ", "-o", action="store_true"
    )
    parser.add_argument("--skip-dotenv-layers", "-s", action="store_true")
    parser.add_argument("--workspace")
    parser.add_argument("--layout")
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--log-level")
    return parser
