"""Runtime context processors for AppRC logging.

This module owns values that are true at emission or formatting time rather
than values chosen by the caller. ``CID`` stores an optional correlation ID in a
``ContextVar`` so async tasks can carry request/batch identity without passing
it through every function. ``current_task_name`` records the active asyncio task
or OS thread for console scans.

The structlog processors here are deliberately conservative: they use
``setdefault`` so explicit caller fields survive, and they copy stdlib
``LogRecord`` attributes into renderer-friendly names only when a record is
available.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime
from time import perf_counter

import structlog
from structlog.types import EventDict, WrappedLogger


CID: ContextVar[str | None] = ContextVar("apprc_log_cid", default=None)
STARTED_AT = datetime.now().astimezone()
STARTED_MONOTONIC = perf_counter()


def new_cid() -> str:
    """Create a short random correlation ID.

    :return: Eight-character hexadecimal correlation ID.
    """

    return uuid.uuid4().hex[:8]


def set_cid(value: str | None = None) -> str:
    """Bind a correlation ID to the current context.

    The ID is stored both in AppRC's own ``ContextVar`` and in structlog's
    contextvars storage. That lets AppRC's stdlib path and any direct structlog
    path agree on the same ``cid`` field.

    :param value: Explicit correlation ID, or ``None`` to create a new one.
    :return: The active correlation ID.
    """

    cid = value or new_cid()
    CID.set(cid)
    structlog.contextvars.bind_contextvars(cid=cid)
    return cid


def clear_cid() -> None:
    """Remove the current correlation ID from both context stores.

    :return: ``None``.
    """

    CID.set(None)
    structlog.contextvars.unbind_contextvars("cid")


def current_task_name() -> str:
    """Return the active asyncio task name or current thread name.

    :return: Human-readable concurrent workload identifier.
    """

    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task is not None:
        return task.get_name()
    return threading.current_thread().name


def add_runtime_context(
    logger: WrappedLogger | None,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Add task/thread and correlation fields when missing.

    This processor runs for AppRC records and foreign stdlib records. It fills
    ``task`` with the active asyncio task name when possible and otherwise uses
    the current thread name. ``cid`` is ``"-"`` when no correlation ID was
    bound.

    :param logger: Logger currently processed by structlog.
    :param method_name: Logging method name such as ``info`` or ``warning``.
    :param event_dict: Mutable structured log event.
    :return: The updated event dictionary.
    """

    event_dict.setdefault("task", current_task_name())
    event_dict.setdefault("cid", CID.get() or "-")
    return event_dict


def add_log_record_fields(
    logger: WrappedLogger | None,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Copy stdlib ``LogRecord`` fields into renderer-friendly names.

    Structlog's ``ProcessorFormatter`` stores the original record under
    ``_record``. AppRC copies stable pieces such as logger name, level, source
    line, and timestamp so console and JSON renderers do not need to know the
    stdlib ``LogRecord`` API.

    :param logger: Logger currently processed by structlog.
    :param method_name: Logging method name such as ``info`` or ``warning``.
    :param event_dict: Mutable structured log event.
    :return: The updated event dictionary.
    """

    record = event_dict.get("_record")
    if not isinstance(record, logging.LogRecord):
        return event_dict

    event_dict.setdefault("logger", record.name)
    event_dict.setdefault("level", record.levelname.lower())
    event_dict.setdefault("level_name", record.levelname)
    event_dict.setdefault("level_no", record.levelno)
    event_dict.setdefault("module", record.module)
    event_dict.setdefault("function", record.funcName)
    event_dict.setdefault("line", record.lineno)
    event_dict.setdefault("pathname", record.pathname)
    event_dict.setdefault("created", record.created)

    for key in ("event_type", "icon", "task", "cid", "color"):
        if hasattr(record, key):
            event_dict.setdefault(key, getattr(record, key))
    return event_dict


def elapsed_seconds() -> float:
    """Return seconds elapsed since this logging module was imported.

    The console renderer uses this monotonic clock for a process-relative
    elapsed column that is not affected by wall-clock changes.

    :return: Monotonic elapsed seconds.
    """

    return perf_counter() - STARTED_MONOTONIC


__all__ = [
    "CID",
    "STARTED_AT",
    "add_log_record_fields",
    "add_runtime_context",
    "clear_cid",
    "current_task_name",
    "elapsed_seconds",
    "new_cid",
    "set_cid",
]
