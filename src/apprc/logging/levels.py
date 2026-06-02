"""Semantic logging events mapped onto stdlib logging levels.

Haiu exposes more intent than stdlib's five common levels. A semantic event
describes how a helper method should travel through stdlib filtering and how it
should look in the console: level number, stable event type, icon, color role,
and whether a progress-style message should gain an ellipsis.

The transport level still comes from stdlib, so dependency filters and pytest
``caplog`` keep working. Semantic metadata is just structured display context
attached to Haiu records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticEvent:
    """Describe one Haiu-specific logging helper.

    Instances are immutable so every log call can reuse shared event metadata
    without defensive copies. The ``name`` becomes ``event_type`` in structured
    output, while ``level`` controls stdlib filtering.

    :param name: Stable event label stored in structured log data.
    :param level: Stdlib logging level used for transport and filtering.
    :param icon: Emoji rendered before the message.
    :param color: ANSI color role used by console renderers.
    :param append_ellipsis: Whether helper messages should end with ``...``.
    :param documentation: Human-readable guidance for when to use the event.
    """

    name: str
    level: int
    icon: str
    color: str = "reset"
    append_ellipsis: bool = False
    documentation: str = ""


SEMANTIC_EVENTS: dict[str, SemanticEvent] = {
    "TRACE": SemanticEvent(
        name="TRACE",
        level=logging.DEBUG,
        icon="🐛",
        color="cyan",
        documentation="Step-by-step debugging",
    ),
    "DEBUG": SemanticEvent(
        name="DEBUG",
        level=logging.DEBUG,
        icon="🐞",
        color="blue",
        documentation="Verbose info",
    ),
    "ACTION_BEGIN": SemanticEvent(
        name="ACTION_BEGIN",
        level=logging.INFO,
        icon="⚛️",
        color="bold_magenta",
        append_ellipsis=True,
        documentation="Begin a smaller action",
    ),
    "ACTION_SUCCESS": SemanticEvent(
        name="ACTION_SUCCESS",
        level=logging.INFO,
        icon="☑️",
        color="bold_green",
        documentation="Finish a smaller action",
    ),
    "INFO": SemanticEvent(
        name="INFO",
        level=logging.INFO,
        icon="📃",
        documentation="General info",
    ),
    "INFO_BEGIN": SemanticEvent(
        name="INFO_BEGIN",
        level=logging.INFO,
        icon="▶️ ",
        color="bold",
        documentation="Bigger Task starting",
    ),
    "WAIT": SemanticEvent(
        name="WAIT",
        level=logging.INFO,
        icon="💤",
        color="bold",
        append_ellipsis=True,
        documentation="Waiting (before retry)",
    ),
    "SAVE": SemanticEvent(
        name="SAVE",
        level=logging.INFO,
        icon="💾",
        color="bold",
        documentation="Saving data",
    ),
    "TELEMETRY": SemanticEvent(
        name="TELEMETRY",
        level=logging.INFO,
        icon="👀",
        color="gray",
        documentation="Timed interval readouts",
    ),
    "SUCCESS": SemanticEvent(
        name="SUCCESS",
        level=logging.INFO,
        icon="✅",
        color="bg_green",
        documentation="Finish the whole script",
    ),
    "WARNING": SemanticEvent(
        name="WARNING",
        level=logging.WARNING,
        icon="⚠️",
        color="yellow",
        documentation="Unexpected things",
    ),
    "RETRY": SemanticEvent(
        name="RETRY",
        level=logging.WARNING,
        icon="🔄",
        color="bold_yellow",
        append_ellipsis=True,
        documentation="Retry upon e.g. transient errors",
    ),
    "FALLBACK": SemanticEvent(
        name="FALLBACK",
        level=logging.WARNING,
        icon="🚑",
        color="bold_yellow",
        append_ellipsis=True,
        documentation="Faulty function substituted",
    ),
    "ERROR": SemanticEvent(
        name="ERROR",
        level=logging.ERROR,
        icon="❌",
        color="bold_red",
        documentation="Custom error",
    ),
    "TRACEBACK": SemanticEvent(
        name="TRACEBACK",
        level=logging.ERROR,
        icon="‼️‼️",
        color="red",
        documentation="Log full error message and traceback",
    ),
    "CRITICAL": SemanticEvent(
        name="CRITICAL",
        level=logging.CRITICAL,
        icon="💀",
        color="bg_bold_red",
        documentation="Unrecoverable failure",
    ),
}

EVENT_BY_STDLIB_LEVEL: dict[int, SemanticEvent] = {
    logging.DEBUG: SEMANTIC_EVENTS["DEBUG"],
    logging.INFO: SEMANTIC_EVENTS["INFO"],
    logging.WARNING: SEMANTIC_EVENTS["WARNING"],
    logging.ERROR: SEMANTIC_EVENTS["ERROR"],
    logging.CRITICAL: SEMANTIC_EVENTS["CRITICAL"],
}


def event_for_level(levelno: int) -> SemanticEvent:
    """Return a display event for a plain stdlib logging level.

    Foreign loggers only provide numeric stdlib levels. This function maps
    those levels to the closest Haiu display metadata so dependency messages
    render in the same console format as Haiu semantic messages.

    :param levelno: Numeric stdlib logging level from a ``LogRecord``.
    :return: Matching semantic event, falling back to ``INFO``.
    """

    if levelno >= logging.CRITICAL:
        return SEMANTIC_EVENTS["CRITICAL"]
    if levelno >= logging.ERROR:
        return SEMANTIC_EVENTS["ERROR"]
    if levelno >= logging.WARNING:
        return SEMANTIC_EVENTS["WARNING"]
    if levelno <= logging.DEBUG:
        return SEMANTIC_EVENTS["DEBUG"]
    return EVENT_BY_STDLIB_LEVEL.get(levelno, SEMANTIC_EVENTS["INFO"])


__all__ = ["SEMANTIC_EVENTS", "SemanticEvent", "event_for_level"]
