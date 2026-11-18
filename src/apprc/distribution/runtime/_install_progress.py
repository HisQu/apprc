"""Private progress messages for one installation invocation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_Kind = Literal["stage", "result", "detail", "warning", "version"]


@dataclass(frozen=True, slots=True)
class InstallProgress:
    """An observed stage or result with an optional structured path."""

    kind: _Kind
    message: str
    status: str = ""
    path: str | Path | None = None


_reporter: ContextVar[Callable[[InstallProgress], None] | None] = ContextVar(
    "apprc_install_progress", default=None
)
installation_color: ContextVar[bool | None] = ContextVar(
    "apprc_install_color", default=None
)


@contextmanager
def installation_color_override(color: bool | None) -> Iterator[None]:
    """Carry Click's explicit color choice through an argument-only delegate."""
    token = installation_color.set(color)
    try:
        yield
    finally:
        installation_color.reset(token)


@contextmanager
def installation_progress(
    reporter: Callable[[InstallProgress], None],
) -> Iterator[None]:
    """Bind the terminal observer for this installation only."""
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


def report(
    kind: _Kind,
    message: str,
    status: str = "",
    path: str | Path | None = None,
) -> None:
    """Send a plain event to the installation's terminal observer."""
    reporter = _reporter.get()
    if reporter is not None:
        try:
            reporter(InstallProgress(kind, message, status, path))
        except OSError:
            # > A closed output stream must not interrupt the transaction.
            _reporter.set(None)


def warn(
    logger: logging.Logger, message: str, error: BaseException | None = None
) -> None:
    """Use one warning channel, falling back to logging outside the CLI."""
    if error is not None:
        message = f"{message}: {error}"
    if _reporter.get() is None:
        logger.warning("%s", message)
    else:
        report("warning", message)
