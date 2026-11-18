"""Stdlib-only Windows setup diagnostics usable before AppRC imports."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit, urlunsplit

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+")
_SECRET_KEY = re.compile(
    r"token|secret|pass(?:word|wd)?|api.?key|credential", re.I
)


def _sanitize(text: str) -> str:
    """Exclude credential-bearing environment values and URL components."""
    values = sorted(
        {
            value
            for key, value in os.environ.items()
            if value and _SECRET_KEY.search(key)
        },
        key=len,
        reverse=True,
    )
    for value in values:
        text = text.replace(value, "[redacted]")

    def url(match: re.Match[str]) -> str:
        try:
            parts = urlsplit(match.group())
            return urlunsplit(
                (
                    parts.scheme,
                    parts.netloc.rsplit("@", 1)[-1],
                    parts.path,
                    "",
                    "",
                )
            )
        except ValueError:
            return "[redacted URL]"

    return _URL.sub(url, text)


def setup_diagnostic(stage: str, error: BaseException) -> Path | None:
    """Keep one failure report outside any rollback-owned installation tree."""
    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        return None
    directory = Path(local) / "AppRC" / "setup-logs"
    try:
        # > A redirected log location must not receive diagnostics.
        locations = (directory, *directory.parents)
        if any(path.is_symlink() or path.is_junction() for path in locations):
            return None
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if any(path.is_symlink() or path.is_junction() for path in locations):
            return None
        with tempfile.NamedTemporaryFile(
            dir=directory,
            prefix="setup-",
            suffix=".log",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as stream:
            trace = traceback.TracebackException.from_exception(
                error, capture_locals=False
            )
            stream.write(
                _sanitize(f"Setup stage: {stage}\n{''.join(trace.format())}")
            )
            return Path(stream.name)
    except OSError:
        return None


def _console_processes() -> set[int]:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    processes = (wintypes.DWORD * 8)()
    count = kernel.GetConsoleProcessList(processes, len(processes))
    return set(processes[:count]) if 0 < count <= len(processes) else set()


def _process_details(process_ids: set[int]) -> dict[int, tuple[int, str]]:
    """Look up the parent and executable name of the console's launchers."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("default_heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent_pid", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("executable", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel.CreateToolhelp32Snapshot
    snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snapshot.restype = wintypes.HANDLE
    handle = snapshot(0x00000002, 0)  # < TH32CS_SNAPPROCESS
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    first = kernel.Process32FirstW
    next_entry = kernel.Process32NextW
    first.argtypes = next_entry.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry),
    ]
    first.restype = next_entry.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    entry = ProcessEntry()
    entry.size = ctypes.sizeof(entry)
    details: dict[int, tuple[int, str]] = {}
    try:
        found = first(handle, ctypes.byref(entry))
        while found:
            if entry.pid in process_ids:
                details[entry.pid] = (entry.parent_pid, entry.executable)
                if len(details) == len(process_ids):
                    break
            found = next_entry(handle, ctypes.byref(entry))
    finally:
        close(handle)
    return details


def dedicated_setup_console() -> bool:
    """Recognize an isolated setup console without pausing a parent shell."""
    if (
        os.name != "nt"
        or sys.argv[1:]
        or sys.stdin is None
        or sys.stderr is None
        or not sys.stdin.isatty()
        or not sys.stderr.isatty()
    ):
        return False
    bootstrap = os.environ.get("PYAPP")
    if not bootstrap:
        return False
    current, parent = os.getpid(), os.getppid()
    try:
        processes = _console_processes()
        if len(processes) not in {2, 3} or not {current, parent} <= processes:
            return False
        details = _process_details(processes - {current})
    except OSError:
        return False
    bootstrap_name = PureWindowsPath(bootstrap).name.casefold()
    launcher = details.get(parent)
    if launcher is None:
        return False
    if len(processes) == 2:
        return launcher[1].casefold() == bootstrap_name
    # > PyApp starts the Windows venv redirector, which waits for Python.
    bootstrap_pid, launcher_name = launcher
    if (
        bootstrap_pid not in processes - {current, parent}
        or launcher_name.casefold()
        != PureWindowsPath(sys.executable).name.casefold()
    ):
        return False
    root = details.get(bootstrap_pid)
    return root is not None and root[1].casefold() == bootstrap_name


def _acknowledge_setup() -> None:
    print(
        "Press Enter to close this setup window.", file=sys.stderr, flush=True
    )
    try:
        sys.stdin.readline()
    except (OSError, KeyboardInterrupt):
        pass


def run_setup_loader(load: Callable[[], None], state: dict[str, bool]) -> None:
    """Report early startup failures and acknowledge only dedicated setup."""
    dedicated = dedicated_setup_console()
    state["dedicated"] = dedicated
    startup_failed = False
    try:
        load()
    except Exception as error:
        if state.get("dispatched") and not state.get("install"):
            raise
        startup_failed = True
        stage = "Starting Windows setup"
        print(
            f"Installation failed during startup: {_sanitize(str(error))}",
            file=sys.stderr,
            flush=True,
        )
        path = setup_diagnostic(stage, error)
        if path is not None:
            print(f"Setup diagnostic log: {path}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    finally:
        if dedicated and (startup_failed or state.get("install", False)):
            _acknowledge_setup()
