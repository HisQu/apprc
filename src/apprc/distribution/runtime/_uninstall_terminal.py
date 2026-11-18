"""Terminal interaction shared by uninstall launch and cleanup processes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


# > Load optional rendering before the finalizer deletes its staged modules.
try:
    if __package__:
        from apprc.interfaces._terminal_console import write_line
    else:
        from _terminal_console import write_line  # type: ignore[reportMissingImports]
except ImportError:
    write_line = None

RESULT_ICON_FILENAME = "uninstall.ico"


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


def apply_result_icon(icon: Path) -> None:
    """Set the icon of a visible Windows console owned by the result session."""
    if (
        os.name != "nt"
        or os.environ.get("_APPRC_UNINSTALL_RESULT_WINDOW") != "1"
    ):
        return
    import ctypes
    from ctypes import wintypes

    try:
        if not icon.is_file():
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel.GetConsoleWindow.restype = wintypes.HWND
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        window = kernel.GetConsoleWindow()
        if not window or not user.IsWindowVisible(window):
            return
        user.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user.LoadImageW.restype = wintypes.HANDLE
        # > IMAGE_ICON with a default-sized image loaded from the staged file.
        handle = user.LoadImageW(None, str(icon), 1, 0, 0, 0x10 | 0x40)
        if not handle:
            return
        user.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        result = ctypes.c_size_t()
        for size in (0, 1):
            # > WM_SETICON for the small and large window icon.
            user.SendMessageTimeoutW(
                window, 0x80, size, handle, 0x2, 250, ctypes.byref(result)
            )
    except OSError:
        return


def prepare_result_window(icon: Path | None = None) -> None:
    """Attach only result output to the new console, preserving control pipes."""
    if (
        os.name == "nt"
        and os.environ.get("_APPRC_UNINSTALL_RESULT_WINDOW") == "1"
    ):
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        if icon is not None:
            apply_result_icon(icon)


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


def result_line(
    message: str, path: str | Path | None = None, *, style: str = ""
) -> None:
    """Print a cleanup outcome on stderr, separate from the control stream."""
    if write_line is None:
        print(
            message + (f": {path}" if path is not None else ""),
            file=sys.stderr,
            flush=True,
        )
        return
    write_line(sys.stderr, message, path=path, style=style)
