"""Color selection and literal output shared by CLI and staged uninstall."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

    from rich.console import Console as RichConsole
    from typer import Context

# > Load renderer dependencies before standalone cleanup removes their sources.
try:
    from rich.console import Console
    from rich.text import Text

    if __package__:
        from . import _terminal_styles as styles
    else:
        import _terminal_styles as styles  # type: ignore[reportMissingImports]
except ImportError:
    Console = None
    Text = None
    styles = None

_COLOR_OVERRIDE = "_APPRC_TERMINAL_COLOR"


def color_environment(
    environment: Mapping[str, str], color: bool | None
) -> dict[str, str]:
    """Carry an explicit color decision through an AppRC child process."""
    result = dict(environment)
    if color is not None:
        result[_COLOR_OVERRIDE] = "1" if color else "0"
    return result


def terminal_console(
    stream: TextIO,
    *,
    color: bool | None = None,
    terminal: bool | None = None,
    width: int | None = None,
) -> RichConsole:
    """Use the caller's color override and the actual terminal's capability."""
    if Console is None:
        raise ImportError("Rich terminal rendering is unavailable.")
    if color is None:
        override = os.environ.get(_COLOR_OVERRIDE)
        if override in {"1", "0"}:
            color = override == "1"
    if color is None:
        color = stream.isatty() if terminal is None else terminal
    color = color and "NO_COLOR" not in os.environ
    return Console(
        file=stream,
        width=width,
        force_terminal=color,
        color_system="standard" if color else None,
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


def cli_console(
    ctx: Context | None = None, *, error: bool = False
) -> RichConsole:
    """Construct a console for the selected CLI output stream."""
    from typer import get_text_stream

    return terminal_console(
        get_text_stream("stderr" if error else "stdout"),
        color=ctx.color if ctx is not None else None,
    )


def write_line(
    stream: TextIO,
    message: str,
    *,
    style: str = "",
    path: str | Path | None = None,
    prefix: str = "",
    color: bool | None = None,
) -> None:
    """Write one literal result, with a plain fallback when Rich is unavailable."""
    separator = ": " if message and path is not None else ""
    if Text is None or styles is None:
        print(
            prefix
            + message
            + separator
            + (str(path) if path is not None else ""),
            file=stream,
            flush=True,
        )
        return
    line = Text.assemble(
        (prefix, styles.SUCCESS_STYLE),
        (message, styles.RESULT_STYLES.get(style, "")),
    )
    if path is not None:
        line.append(separator)
        line.append_text(styles.path_text(path))
    terminal_console(stream, color=color).print(line)


def cli_line(
    ctx: Context | None,
    message: str,
    *,
    style: str = "",
    path: str | Path | None = None,
    error: bool = False,
) -> None:
    """Print a semantic CLI result on stdout or stderr."""
    from typer import get_text_stream

    write_line(
        get_text_stream("stderr" if error else "stdout"),
        message,
        style=style,
        path=path,
        color=ctx.color if ctx is not None else None,
    )


def human_report(json_output: bool = False) -> bool:
    """Select a human report only for an implicit terminal invocation."""
    from typer import get_text_stream

    return not json_output and get_text_stream("stdout").isatty()
