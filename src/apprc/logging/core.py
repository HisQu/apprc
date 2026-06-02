"""Named stdlib loggers with Haiu semantic helper methods.

This module owns the emission side of the logging pipeline. ``get_logger``
returns a normal stdlib logger whose class is ``AppLogger``. Calls such as
``LOG.success("done", extra_struct={"rows": 12})`` still travel through
``logging.Logger._log``; Haiu only prepares the message, logging level,
``extra`` fields, semantic metadata, and stack attribution before stdlib builds
the ``LogRecord``.

The formatter installed by ``config`` later turns that ``LogRecord`` into a
structlog event dictionary. Keeping stdlib as the transport lets pytest's
``caplog``, dependency loggers, and existing libraries behave normally while
Haiu keeps structured fields for console and JSON rendering.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from typing import Any, cast

from apprc.logging.context import CID, current_task_name
from apprc.logging.levels import SEMANTIC_EVENTS, SemanticEvent


_DEPTH_BASE_WRAPPER = 3
_DEPTH_OVERRIDE: ContextVar[int] = ContextVar(
    "apprc_log_depth_override",
    default=_DEPTH_BASE_WRAPPER,
)

_MISSING = object()
_RESERVED_LOG_RECORD_KEYS = frozenset(
    logging.LogRecord(
        name="",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
) | {"message", "asctime"}


# ===============================================================
# == Main Logger Class
# ===============================================================


class AppLogger(logging.getLoggerClass()):
    """Stdlib logger class with Haiu's semantic logging methods.

    This class is a real ``logging.Logger`` subclass, so callers can pass it to
    code that expects stdlib logger methods such as ``setLevel`` or
    ``isEnabledFor``. Semantic methods like ``action_begin`` and ``traceback``
    choose a configured logging level, icon, color role, and optional ellipsis
    from ``SEMANTIC_EVENTS``.

    Structured fields must be passed with ``extra_struct`` or stdlib
    ``extra``. Both mappings are validated against reserved ``LogRecord`` names,
    merged, and passed to ``Logger._log`` as ``extra``. Bare unknown keyword
    arguments are rejected so calls stay close to the stdlib logging interface.

    The base class is captured with ``logging.getLoggerClass()`` at import time
    so Haiu extends any logger class already active before this module loads.
    Later class changes are not rebased; stdlib logging does not support that
    safely.
    """

    @contextlib.contextmanager
    def depth(self, depth: int = 0) -> Iterator[None]:
        """Adjust callsite attribution for a group of helper calls.

        Stdlib logging uses ``stacklevel`` to decide which frame appears as the
        caller. Haiu wrapper helpers add their own frames, so this context
        manager raises the default stack skip for every semantic log call inside
        the block.

        :param depth: Additional user-space stack frames to skip.
        :return: Context manager that restores the prior depth on exit.
        """

        token = _DEPTH_OVERRIDE.set(_DEPTH_BASE_WRAPPER + int(depth))
        try:
            yield
        finally:
            _DEPTH_OVERRIDE.reset(token)

    def telemetry_async(
        self,
        label: str = "",
        interval: float = 30.0,
        include_threads: bool = True,
        extras: Any | None = None,
    ) -> Any:
        """Create a telemetry context manager using this logger.

        :param label: Human-readable telemetry scope label.
        :param interval: Seconds between telemetry updates.
        :param include_threads: Whether active OS thread count is reported.
        :param extras: Optional callback returning extra metrics.
        :return: Async telemetry context manager.
        """

        from apprc.logging.functions.telemetry import async_telemetry

        return async_telemetry(
            label=label,
            interval=interval,
            logger=self,
            include_threads=include_threads,
            extras=extras,
        )

    def trace(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "TRACE",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def debug(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "DEBUG",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def action_begin(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "ACTION_BEGIN",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def action_success(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "ACTION_SUCCESS",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def info_begin(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "INFO_BEGIN",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def info(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "INFO",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def wait(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "WAIT",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def save(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "SAVE",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def telemetry(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "TELEMETRY",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def success(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "SUCCESS",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def warning(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "WARNING",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    warn = warning

    def fallback(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "FALLBACK",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def retry(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "RETRY",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def error(
        self,
        msg: Any = "",
        *args: Any,
        exc: BaseException | None = None,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        if exc is not None:
            msg = (
                f"[{type(exc).__name__}] {msg}" if msg else "An error occurred."
            )
        return self._emit_semantic(
            "ERROR",
            msg or "An error occurred.",
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def traceback(
        self,
        msg: Any = "",
        *args: Any,
        exc: BaseException | bool | tuple[Any, Any, Any] | None = None,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        text = str(msg)
        if text and not text.endswith(":"):
            text = f"{text}:"
        kwargs["exc_info"] = self._exc_info(exc)
        return self._emit_semantic(
            "TRACEBACK",
            text or "Traceback:",
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def critical(
        self,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._emit_semantic(
            "CRITICAL",
            msg,
            *args,
            prefix=prefix,
            extra_struct=extra_struct,
            **kwargs,
        )

    def _emit_semantic(
        self,
        event_name: str,
        msg: Any,
        *args: Any,
        prefix: str = "",
        extra_struct: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Emit one semantic event through stdlib logging.

        Haiu keeps the stdlib logging interface for control keyword arguments
        and reserves ``extra_struct`` for structlog event fields. This helper
        validates ``extra`` and ``extra_struct`` before stdlib sees them,
        merges both mappings into one ``extra`` dict, adds Haiu display
        metadata, and finally calls ``Logger._log``.

        :param event_name: Semantic event key from ``SEMANTIC_EVENTS``.
        :param msg: Human-readable event text.
        :param args: Optional printf-style formatting arguments.
        :param prefix: Optional text prepended to the message.
        :param extra_struct: Structured values added to the structlog event.
        :param kwargs: Stdlib logging controls and Haiu exception shortcuts.
        :return: Value returned by ``Logger._log``.
        """

        event = SEMANTIC_EVENTS[event_name]
        if not self.isEnabledFor(event.level):
            return None

        text = self._message_text(msg, prefix=prefix, event=event)
        stacklevel = self._stacklevel(
            kwargs.pop("stacklevel", None),
            kwargs.pop("depth", 0),
        )
        if "exception" in kwargs and "exc_info" not in kwargs:
            kwargs["exc_info"] = self._exc_info(kwargs.pop("exception"))
        if "exc" in kwargs and "exc_info" not in kwargs:
            kwargs["exc_info"] = self._exc_info(kwargs.pop("exc"))

        exc_info = kwargs.pop("exc_info", None)
        stack_info = bool(kwargs.pop("stack_info", False))
        extra = self._extra_from_kwargs(
            kwargs,
            extra_struct=extra_struct,
        )
        extra.setdefault("task", current_task_name())
        extra.setdefault("cid", CID.get() or "-")
        extra.update(event_type=event.name, icon=event.icon, color=event.color)
        return super()._log(
            event.level,
            text,
            args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )

    @staticmethod
    def _extra_from_kwargs(
        kwargs: dict[str, Any],
        *,
        extra_struct: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the stdlib ``extra`` dict for one semantic log call.

        ``extra`` is the stdlib escape hatch and ``extra_struct`` is Haiu's
        named lane for fields that should appear in structlog output. This
        helper keeps both, but refuses collisions and reserved ``LogRecord``
        names before stdlib can raise a less contextual error.

        :param kwargs: Remaining keyword arguments after logging controls were
            removed.
        :param extra_struct: Structured fields destined for the event dict.
        :return: Combined mapping safe to pass as ``Logger._log(extra=...)``.
        """

        extra_arg = kwargs.pop("extra", _MISSING)
        AppLogger._reject_unknown_kwargs(kwargs)
        extra = (
            dict(extra_arg)
            if extra_arg is not _MISSING and extra_arg is not None
            else {}
        )
        struct_extra = dict(extra_struct or {})
        AppLogger._validate_extra_keys("extra", extra)
        AppLogger._validate_extra_keys("extra_struct", struct_extra)
        duplicate_keys = extra.keys() & struct_extra.keys()
        if duplicate_keys:
            keys = ", ".join(sorted(str(key) for key in duplicate_keys))
            raise KeyError(
                "Duplicate logging structured field(s) in extra and "
                f"extra_struct: {keys}"
            )
        extra.update(struct_extra)
        return extra

    @staticmethod
    def _reject_unknown_kwargs(kwargs: Mapping[str, Any]) -> None:
        """Raise when a caller used bare structured logging fields.

        :param kwargs: Keyword arguments not claimed as stdlib controls.
        :raise TypeError: If any unsupported keyword argument remains.
        """

        if not kwargs:
            return
        keys = ", ".join(sorted(str(key) for key in kwargs))
        raise TypeError(
            "Unsupported logging keyword argument(s): "
            f"{keys}. Put structured fields in extra_struct={{...}}."
        )

    @staticmethod
    def _validate_extra_keys(source: str, extra: Mapping[str, Any]) -> None:
        """Reject structured fields that would overwrite ``LogRecord`` data.

        :param source: Name of the user-facing mapping being checked.
        :param extra: Structured fields supplied by the caller.
        :raise KeyError: If any field collides with stdlib logging attributes.
        """

        collisions = set(extra) & _RESERVED_LOG_RECORD_KEYS
        if not collisions:
            return
        keys = ", ".join(sorted(str(key) for key in collisions))
        raise KeyError(f"{source} contains reserved LogRecord field(s): {keys}")

    @staticmethod
    def _message_text(msg: Any, *, prefix: str, event: SemanticEvent) -> str:
        """Return the final human-readable message for stdlib logging.

        :param msg: Caller-provided message object.
        :param prefix: Optional text prepended before the message.
        :param event: Semantic event controlling ellipsis behavior.
        :return: String passed as the stdlib log message.
        """

        text = str(msg)
        if event.append_ellipsis and not text.endswith("..."):
            text = f"{text} ..."
        if not prefix:
            return text
        spacer = "" if prefix.endswith(" ") else " "
        return f"{prefix}{spacer}{text}"

    @staticmethod
    def _stacklevel(stacklevel: Any, depth: Any) -> int:
        """Resolve explicit and contextual stack attribution controls.

        :param stacklevel: Optional stdlib ``stacklevel`` override.
        :param depth: Haiu-specific extra frames to skip.
        :return: Stack level sent to ``Logger._log``.
        """

        if stacklevel is not None:
            return int(stacklevel)
        return _DEPTH_OVERRIDE.get() + int(depth)

    @staticmethod
    def _exc_info(
        exc: BaseException | bool | tuple[Any, Any, Any] | None,
    ) -> bool | tuple[type[BaseException], BaseException, Any] | None:
        """Normalize Haiu exception shortcuts into stdlib ``exc_info``.

        ``True`` means stdlib should read the active exception from
        ``sys.exc_info``. An exception object becomes an explicit tuple so the
        right traceback survives even after leaving the ``except`` block.

        :param exc: Exception object, bool flag, tuple, or ``None``.
        :return: Value accepted by stdlib logging as ``exc_info``.
        """

        if exc is None:
            return True
        if exc is False:
            return None
        if exc is True:
            return True
        if isinstance(exc, BaseException):
            return (type(exc), exc, exc.__traceback__)
        return cast(tuple[type[BaseException], BaseException, Any], exc)


# ===============================================================
# == PUBLIC API
# ===============================================================


def install_app_logger_class() -> type[AppLogger]:
    """Install ``AppLogger`` as the stdlib class for future loggers.

    ``logging.setLoggerClass`` affects only loggers created after the call; it
    cannot safely change logger objects that already exist in the logging
    manager. ``get_logger`` calls this before asking stdlib for a name so Haiu
    modules get semantic methods even when they create module-level loggers at
    import time. ``setup_logging`` calls it too because entrypoints are the
    natural place for global logging configuration.

    :return: The active Haiu logger class.
    """

    current = logging.getLoggerClass()
    if issubclass(current, AppLogger):
        return cast(type[AppLogger], current)
    logging.setLoggerClass(AppLogger)
    return AppLogger


def get_logger(name: str) -> AppLogger:
    """Return a named stdlib logger with Haiu semantic methods.

    The helper installs ``AppLogger`` before it calls ``logging.getLogger`` so
    new Haiu module loggers are real stdlib loggers with methods like
    ``action_begin``. If a plain stdlib logger for ``name`` already exists,
    stdlib returns that existing object; this function does not mutate its
    class because that would be unsafe for arbitrary logger subclasses.

    :param name: Stdlib logger name, usually ``__name__``.
    :return: Named logger, typed as ``AppLogger`` for Haiu-created names.
    """

    install_app_logger_class()
    return cast(AppLogger, logging.getLogger(name))


HaiuLogger = AppLogger
install_haiu_logger_class = install_app_logger_class

__all__ = [
    "AppLogger",
    "HaiuLogger",
    "get_logger",
    "install_app_logger_class",
    "install_haiu_logger_class",
]
