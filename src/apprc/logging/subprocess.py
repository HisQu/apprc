"""Subprocess output forwarding for Haiu loggers.

CLI helpers often run external commands that return captured stdout and stderr.
This module converts those captured streams into ordinary Haiu log records:
stdout lines are informational, stderr lines are errors, and the child return
code is passed back to the caller.
"""

from __future__ import annotations

import subprocess
from typing import Any

from apprc.logging.core import AppLogger, get_logger


def forward_cli_output(
    process: subprocess.Popen[Any],
    *,
    logger: AppLogger | None = None,
) -> int:
    """Log captured child-process output and return its exit status.

    ``process.communicate`` is consumed exactly once. Callers should pass a
    ``Popen`` instance configured with captured stdout/stderr when they want
    line forwarding.

    :param process: Process whose captured output should be consumed.
    :param logger: Logger used for forwarded stdout and stderr lines.
    :return: Child-process return code, normalized to ``0`` when unset.
    """

    log = logger or get_logger(__name__)
    stdout, stderr = process.communicate()
    _forward_lines(stdout, logger=log, stderr=False)
    _forward_lines(stderr, logger=log, stderr=True)
    return int(process.returncode or 0)


def _forward_lines(
    chunk: bytes | str | None,
    *,
    logger: AppLogger,
    stderr: bool,
) -> None:
    """Forward one captured output stream line-by-line.

    Byte chunks are decoded with replacement so broken child-process output
    still becomes a log message instead of raising during error handling.

    :param chunk: Raw stream contents returned by ``Popen.communicate``.
    :param logger: Logger used for emitted lines.
    :param stderr: Whether the chunk came from stderr.
    """

    if not chunk:
        return
    text = chunk.decode(errors="replace") if isinstance(chunk, bytes) else chunk
    emit = logger.error if stderr else logger.info
    for line in text.splitlines():
        emit(line)


__all__ = ["forward_cli_output"]
