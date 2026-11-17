"""Terminal interaction shared by uninstall launch and cleanup processes."""

from __future__ import annotations

import os
import sys


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


def acknowledge() -> None:
    """Keep the terminal result visible until the user acknowledges it."""
    print(
        "Press Enter to close this uninstall terminal.",
        file=sys.stderr,
        flush=True,
    )
    if os.name == "nt":
        with open("CONIN$", encoding="utf-8") as stream:
            stream.readline()
    elif sys.stdin.isatty():
        sys.stdin.readline()
