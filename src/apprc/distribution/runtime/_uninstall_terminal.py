"""Terminal interaction shared by uninstall launch and cleanup processes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare() -> None:
    """Connect Windows-launched uninstall to a visible console when necessary."""
    if os.name != "nt":
        return
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.GetConsoleWindow() and not kernel.AllocConsole():
        raise OSError(ctypes.get_last_error(), "Cannot open uninstall terminal")
    if not sys.stdin.isatty():
        sys.stdin = open("CONIN$", encoding="utf-8")
    if not sys.stderr.isatty():
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    if not sys.stdout.isatty():
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)


def prepare_result_window() -> None:
    """Attach only result output to the new console, preserving control pipes."""
    if (
        os.name == "nt"
        and os.environ.get("_APPRC_UNINSTALL_RESULT_WINDOW") == "1"
    ):
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)


def acknowledge() -> None:
    """Keep the terminal result visible until the user acknowledges it."""
    print(
        "Press Enter to close this uninstall window."
        if os.name == "nt"
        else "Press Enter to close this uninstall terminal.",
        file=sys.stderr,
        flush=True,
    )
    if os.name == "nt":
        with open("CONIN$", encoding="utf-8") as stream:
            stream.readline()
    elif sys.stdin.isatty():
        sys.stdin.readline()


def result_line(message: str, path: str | Path | None = None) -> None:
    """Print a cleanup outcome with optional terminal styling and plain fallback.

    :param message: Outcome or label, never parsed for paths.
    :param path: Structured path value, when available.
    """
    try:
        from rich.console import Console

        if __package__:
            from apprc.interfaces._terminal_styles import path_text
        else:
            from _terminal_styles import path_text  # type: ignore[reportMissingImports]
    except ImportError:
        print(
            message + (f": {path}" if path is not None else ""),
            file=sys.stderr,
            flush=True,
        )
        return
    from rich.text import Text

    line = Text(message)
    if path is not None:
        line.append(": ")
        line.append_text(path_text(str(path)))
    Console(file=sys.stderr, highlight=False, soft_wrap=True).print(line)
