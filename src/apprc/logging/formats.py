"""Console renderers for AppRC structlog events.

This module is the last step for human-readable logging. By the time
``AppConsoleRenderer`` runs, ``config`` has already copied stdlib ``extra``
fields, added ``LogRecord`` metadata, filled runtime context, applied semantic
defaults, and redacted sensitive top-level values. The renderer only decides
which columns to show and how to append any remaining structured fields.

``mini``, ``cli``, and ``ipy`` share the same event dictionary but use different
column density. Extra structured fields that are not consumed by the layout are
printed at the end as ``key=value`` pairs so structured logging is visible even
outside JSON mode.
"""

from __future__ import annotations

import logging
from io import StringIO
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from apprc.logging.context import elapsed_seconds
from apprc.logging.exceptions import (
    RedactedRichTracebackFormatter,
    normalize_exc_info,
)
from apprc.logging.levels import event_for_level

RendererMode = Literal["mini", "cli", "ipy"]
TimeBucket = tuple[int, int, int, int, int, int]

# -- Event fields already represented by dedicated console columns
_RENDERER_FIELD_KEYS = frozenset(
    {
        "_from_structlog",
        "_record",
        "cid",
        "color",
        "created",
        "event",
        "event_type",
        "exc_info",
        "exception",
        "function",
        "icon",
        "level",
        "level_name",
        "level_no",
        "line",
        "logger",
        "module",
        "pathname",
        "stack_info",
        "task",
    }
)


ANSI_RESET = "\033[0m"
ANSI: dict[str, str] = {
    "reset": "",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
    # -- Bold --
    "bold": "\033[1m",
    "bold_red": "\033[1;31m",
    "bold_green": "\033[1;32m",
    "bold_yellow": "\033[1;33m",
    "bold_magenta": "\033[1;35m",
    # -- Background --
    "bg_green": "\033[30;42m",
    "bg_red": "\033[30;41m",
    # -- Background + Bold --
    "bg_bold_green": "\033[1;30;42m",
    "bg_bold_red": "\033[1;30;41m",
}


@dataclass
class SecondCollapser:
    """Collapse repeated timestamp cells within the same second.

    Console logs are usually read top to bottom. When many records share one
    wall-clock second, blanking repeated timestamp cells makes message changes
    easier to scan without hiding the first timestamp in each second.

    :param enabled: Whether repeated timestamps should be blanked.
    :param last: Previously rendered wall-clock second.
    """

    enabled: bool = True
    last: TimeBucket | None = None

    @staticmethod
    def _bucket(dt: datetime) -> TimeBucket:
        """Return a second-level bucket for timestamp comparison.

        :param dt: Timestamp to bucket.
        :return: Tuple containing date and time parts down to seconds.
        """

        return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    def render(self, dt: datetime, value: str) -> str:
        """Return ``value`` or a same-width blank for repeated seconds.

        :param dt: Timestamp represented by ``value``.
        :param value: Formatted timestamp cell.
        :return: Original value for a new second, blank otherwise.
        """

        if not self.enabled:
            return value
        bucket = self._bucket(dt)
        same = self.last == bucket
        self.last = bucket
        return " " * len(value) if same else value


@dataclass
class AppConsoleRenderer:
    """Render structlog event dictionaries in AppRC's column style.

    The renderer is a structlog processor: it receives a mutable event
    dictionary and returns the final string for the stdlib handler. It renders
    the selected base layout first, appends unconsumed structured fields, and
    finally appends a rich traceback when ``exc_info`` is present.

    :param mode: Layout variant, matching the old mini/CLI/IPython formats.
    :param colorize: Whether ANSI color codes should be included.
    :param collapse_same_second: Whether equal timestamp seconds are blanked.
    :param exception_formatter: Renderer for ``exc_info`` tracebacks.
    """

    mode: RendererMode = "mini"
    colorize: bool = True
    collapse_same_second: bool = True
    exception_formatter: RedactedRichTracebackFormatter | None = None

    def __post_init__(self) -> None:
        self._collapser = SecondCollapser(enabled=self.collapse_same_second)
        if self.exception_formatter is None:
            self.exception_formatter = RedactedRichTracebackFormatter(
                colorize=self.colorize,
            )

    def __call__(
        self,
        logger: object | None,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> str:
        """Render one log event.

        The method intentionally leaves event mutation to earlier processors.
        It treats the event dictionary as read-only display input and returns
        the final text line expected by ``ProcessorFormatter``.

        :param logger: Logger currently processed by the structured formatter.
        :param method_name: Logging method name such as ``info``.
        :param event_dict: Structured event data.
        :return: Console-ready log line.
        """

        if self.mode == "cli":
            line = self._render_cli(event_dict)
        elif self.mode == "ipy":
            line = self._render_ipy(event_dict)
        else:
            line = self._render_mini(event_dict)
        line = self._append_fields(line, event_dict)
        return self._append_exception(line, event_dict)

    def _render_mini(self, event_dict: dict[str, Any]) -> str:
        """Render the compact default console layout.

        :param event_dict: Structured event data.
        :return: One-line message with time, elapsed time, task, level, source,
            icon, and event text.
        """

        dt = self._datetime(event_dict)
        time_cell = self._collapser.render(dt, dt.strftime("%H:%M:%S"))
        return (
            f"| {self._style(time_cell, 'yellow')}"
            f" | {self._style(self._elapsed(), 'yellow')}"
            f" | {self._style(str(event_dict.get('task', '-')), 'red')} "
            f" | {self._style(str(event_dict.get('level_no', 0)).center(2), self._color(event_dict))}"
            f" | {self._style(self._logger_name(event_dict), 'green'):>20}"
            f":{self._style(str(event_dict.get('line', 0)).ljust(4), 'magenta')}"
            f" {self._style(self._function(event_dict).ljust(12), 'magenta')}"
            f" – {self._icon(event_dict)} - "
            f"{self._style(self._event(event_dict), self._color(event_dict))}"
        )

    def _render_cli(self, event_dict: dict[str, Any]) -> str:
        """Render the wider command-line layout.

        :param event_dict: Structured event data.
        :return: One-line message with a full date cell and expanded level
            label.
        """

        dt = self._datetime(event_dict)
        time_cell = self._collapser.render(dt, dt.strftime("%y/%m/%d-%H:%M:%S"))
        level_no = int(event_dict.get("level_no", 0))
        level_name = str(event_dict.get("level_name", "INFO"))
        return (
            f"| {self._style(time_cell, 'yellow')}"
            f" | {self._style(self._elapsed(), 'yellow')}"
            f" | {self._style(f'{level_no:>2}:{level_name:^14}', self._color(event_dict))}"
            f" | {self._style(self._logger_name(event_dict).rjust(20), 'green')}"
            f":{self._style(str(event_dict.get('line', 0)).ljust(4), 'magenta')}"
            f" | {self._style('[' + str(event_dict.get('task', '-')) + ']', 'red')}"
            f" {self._style(self._function(event_dict).ljust(12), 'magenta')}"
            f" – {self._icon(event_dict)}: "
            f"{self._style(self._event(event_dict), self._color(event_dict))}"
        )

    def _render_ipy(self, event_dict: dict[str, Any]) -> str:
        """Render the compact notebook-friendly layout.

        :param event_dict: Structured event data.
        :return: One-line message with the columns most useful in IPython.
        """

        dt = self._datetime(event_dict)
        time_cell = self._collapser.render(dt, dt.strftime("%H:%M:%S"))
        return (
            f"| {self._style(time_cell, 'yellow')}"
            f" | {self._style('[' + str(event_dict.get('task', '-')) + ']', 'red')}"
            f" {self._style(self._function(event_dict).ljust(12), 'magenta')}"
            f" – {self._icon(event_dict)}: "
            f"{self._style(self._event(event_dict), self._color(event_dict))}"
        )

    def _append_exception(
        self,
        line: str,
        event_dict: dict[str, Any],
    ) -> str:
        """Append a formatted traceback when the event carries ``exc_info``.

        :param line: Already-rendered one-line console message.
        :param event_dict: Structured event data.
        :return: ``line`` with traceback text appended when available.
        """

        exc_info = normalize_exc_info(event_dict.get("exc_info"))
        if exc_info is None:
            return line

        output = StringIO()
        if self.exception_formatter is not None:
            self.exception_formatter(output, exc_info)
        return line + output.getvalue()

    def _append_fields(self, line: str, event_dict: dict[str, Any]) -> str:
        """Append unconsumed structured fields to the rendered line.

        :param line: Already-rendered one-line console message.
        :param event_dict: Structured event data.
        :return: Line with trailing ``key=value`` fields when any remain.
        """

        fields = self._structured_fields(event_dict)
        if not fields:
            return line
        return f"{line} {self._style(fields, 'gray')}"

    @staticmethod
    def _structured_fields(event_dict: dict[str, Any]) -> str:
        """Render structured fields not already shown by console columns.

        :param event_dict: Structured event data.
        :return: Space-separated ``key=value`` text.
        """

        parts = [
            f"{key}={AppConsoleRenderer._field_value(value)}"
            for key, value in event_dict.items()
            if key not in _RENDERER_FIELD_KEYS
        ]
        return " ".join(parts)

    @staticmethod
    def _field_value(value: object) -> str:
        """Return a compact console representation for one field value.

        :param value: Structured field value.
        :return: String value as-is, otherwise ``repr(value)``.
        """

        if isinstance(value, str):
            return value
        return repr(value)

    def _style(self, value: str, color: str) -> str:
        """Apply an ANSI color role when color output is enabled.

        :param value: Text to render.
        :param color: Named color role from ``ANSI``.
        :return: Styled or plain text.
        """

        if not self.colorize:
            return value
        prefix = ANSI.get(color, "")
        if not prefix:
            return value
        return f"{prefix}{value}{ANSI_RESET}"

    @staticmethod
    def _datetime(event_dict: dict[str, Any]) -> datetime:
        """Return the wall-clock timestamp represented by an event.

        :param event_dict: Structured event data.
        :return: Event creation time, falling back to the current time.
        """

        created = event_dict.get("created")
        if isinstance(created, int | float):
            return datetime.fromtimestamp(created).astimezone()
        return datetime.now().astimezone()

    @staticmethod
    def _elapsed() -> str:
        """Return process-relative elapsed time for console columns.

        :return: Human-readable elapsed duration.
        """

        return str(timedelta(seconds=elapsed_seconds()))

    @staticmethod
    def _logger_name(event_dict: dict[str, Any]) -> str:
        """Return the best available logger name for display.

        :param event_dict: Structured event data.
        :return: Logger name, module name, or ``<unknown>``.
        """

        name = event_dict.get("logger") or event_dict.get("module")
        return str(name or "<unknown>")

    @staticmethod
    def _function(event_dict: dict[str, Any]) -> str:
        """Return the source function name for display.

        :param event_dict: Structured event data.
        :return: Function name, or ``<unknown>``.
        """

        return str(event_dict.get("function") or "<unknown>")

    @staticmethod
    def _event(event_dict: dict[str, Any]) -> str:
        """Return the human message text from the event dictionary.

        :param event_dict: Structured event data.
        :return: Event message text.
        """

        return str(event_dict.get("event", ""))

    @staticmethod
    def _icon(event_dict: dict[str, Any]) -> str:
        """Return the semantic event icon.

        :param event_dict: Structured event data.
        :return: Icon text, or an empty string.
        """

        return str(event_dict.get("icon") or "")

    @staticmethod
    def _color(event_dict: dict[str, Any]) -> str:
        """Return the semantic color role.

        :param event_dict: Structured event data.
        :return: Color role name understood by ``ANSI``.
        """

        return str(event_dict.get("color") or "reset")


def add_semantic_defaults(
    logger: object | None,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Fill display metadata for plain stdlib records.

    AppRC semantic methods already attach ``event_type``, ``icon``, and
    ``color`` to the ``LogRecord``. Plain stdlib records from dependency
    loggers do not, so this processor chooses a reasonable semantic display
    style from the numeric logging level.

    :param logger: Logger currently processed by the structured formatter.
    :param method_name: Logging method name such as ``warning``.
    :param event_dict: Mutable structured log event.
    :return: The updated event dictionary.
    """

    event = event_for_level(int(event_dict.get("level_no", logging.INFO)))
    event_dict.setdefault("event_type", event.name)
    event_dict.setdefault("icon", event.icon)
    event_dict.setdefault("color", event.color)
    return event_dict


__all__ = [
    "ANSI",
    "AppConsoleRenderer",
    "RendererMode",
    "SecondCollapser",
    "add_semantic_defaults",
]
