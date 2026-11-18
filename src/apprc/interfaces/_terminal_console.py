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

if __package__:
    from . import _terminal_styles as styles
else:
    import _terminal_styles as styles  # type: ignore[reportMissingImports]

# > Load optional Rich dependencies before standalone cleanup removes their sources.
try:
    from rich.console import Console
    from rich.text import Text
except ImportError:
    Console = None
    Text = None

_COLOR_OVERRIDE = "_APPRC_TERMINAL_COLOR"


def color_environment(
    environment: Mapping[str, str], color: bool | None
) -> dict[str, str]:
    """Carry an explicit color decision through an AppRC child process."""
    result = dict(environment)
    if color is not None:
        result[_COLOR_OVERRIDE] = "1" if color else "0"
    return result


def _color_enabled(
    stream: TextIO, color: bool | None, terminal: bool | None = None
) -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if color is None:
        override = os.environ.get(_COLOR_OVERRIDE)
        if override in {"1", "0"}:
            color = override == "1"
    if color is None:
        return stream.isatty() if terminal is None else terminal
    return color


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
    color = _color_enabled(stream, color, terminal)
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


def _supports_basic_color(stream: TextIO) -> bool:
    """Avoid sending escape sequences to a legacy Windows console."""
    if os.name != "nt" or not stream.isatty():
        # > Redirected streams reach this branch only with an explicit override.
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        return bool(
            kernel.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode))
            and mode.value & 0x0004
        )
    except (OSError, ValueError):
        return False


_BASIC_ANSI = {
    "dim": 2,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "magenta": 35,
    "cyan": 36,
}


def _basic_style(text: str, style: str) -> str:
    code = _BASIC_ANSI.get(style)
    return f"\x1b[{code}m{text}\x1b[0m" if text and code is not None else text


def write_line(
    stream: TextIO,
    message: str,
    *,
    style: str = "",
    path: str | Path | None = None,
    prefix: str = "",
    color: bool | None = None,
) -> None:
    """Write one literal result, including from stdlib-only finalization."""
    separator = ": " if message and path is not None else ""
    if Text is None:
        path_value = str(path) if path is not None else ""
        if _color_enabled(stream, color) and _supports_basic_color(stream):
            prefix = _basic_style(prefix, styles.SUCCESS_STYLE)
            message = _basic_style(message, styles.RESULT_STYLES.get(style, ""))
            path_value = _basic_style(path_value, styles.PATH_STYLE)
        print(
            prefix + message + separator + path_value, file=stream, flush=True
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
