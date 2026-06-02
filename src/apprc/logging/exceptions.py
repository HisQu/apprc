"""Exception formatting and redaction helpers for AppRC logging.

Tracebacks can expose API keys, database URLs, and prompt contents through
local variables or structured fields. This module centralizes the defensive
parts of logging: matching sensitive names, redacting top-level event fields,
rendering console tracebacks with Rich, and producing JSON-ready exception
dictionaries.

Both console and JSON paths use the same wildcard patterns so redaction policy
does not depend on the selected renderer.
"""

from __future__ import annotations

import fnmatch
import linecache
import sys
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TextIO, cast

from rich.console import Console
from rich.traceback import Trace, Traceback
from structlog.processors import ExceptionRenderer
from structlog.tracebacks import ExceptionDictTransformer
from structlog.types import EventDict, WrappedLogger
from structlog.typing import ExcInfo


ColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]

DEFAULT_REDACT_PATTERNS: tuple[str, ...] = (
    "*_PAT",
    "*_KEY",
    "*_TOKEN",
    "*_SECRET",
    "*PASSWORD*",
    "DATABASE_URL",
)
REDACTED_VALUE = "[redacted]"


def logging_redact_patterns(
    extra_patterns: Sequence[str] = (),
) -> tuple[str, ...]:
    """Return the built-in secret-name patterns plus caller additions.

    Patterns are matched case-insensitively with shell-style wildcards by
    ``SecretNameMatcher``. Callers can extend but not remove the built-in
    safety defaults.

    :param extra_patterns: Additional shell-style wildcard patterns.
    :return: Ordered pattern tuple used by redaction processors.
    """

    return (*DEFAULT_REDACT_PATTERNS, *tuple(extra_patterns))


def normalize_exc_info(exc_info: Any) -> ExcInfo | None:
    """Return a concrete exception tuple when one is available.

    Stdlib logging accepts several shapes for ``exc_info``. Renderers need a
    concrete ``(type, exception, traceback)`` tuple, so this helper resolves
    exception objects, existing tuples, and truthy flags that mean "use the
    active exception".

    :param exc_info: Stdlib ``exc_info`` value from a logging event.
    :return: Exception tuple, or ``None`` when no active exception exists.
    """

    if isinstance(exc_info, BaseException):
        return (type(exc_info), exc_info, exc_info.__traceback__)
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        exc_type, exc, traceback = exc_info
        if isinstance(exc_type, type) and isinstance(exc, BaseException):
            return cast(ExcInfo, (exc_type, exc, traceback))
        return None
    if not exc_info:
        return None

    exc_type, exc, traceback = sys.exc_info()
    if exc_type is None or exc is None:
        return None
    return (exc_type, exc, traceback)


@dataclass(frozen=True)
class SecretNameMatcher:
    """Match field names against case-insensitive wildcard patterns.

    The matcher is intentionally based on names rather than values. That keeps
    redaction predictable and avoids scanning arbitrary objects for secret-like
    strings.

    :param patterns: Shell-style wildcard patterns for sensitive names.
    """

    patterns: tuple[str, ...]

    def matches(self, name: str) -> bool:
        """Return whether ``name`` should be treated as sensitive.

        :param name: Event or local-variable field name.
        :return: ``True`` when a configured pattern matches.
        """

        folded_name = name.casefold()
        return any(
            fnmatch.fnmatchcase(folded_name, pattern.casefold())
            for pattern in self.patterns
        )


@dataclass(frozen=True)
class LogFieldRedactor:
    """Redact top-level structured log fields with sensitive names.

    This structlog processor runs before console or JSON rendering. It leaves
    private processor metadata alone, but replaces public event fields like
    ``OPENAI_KEY`` or ``DATABASE_URL`` with ``REDACTED_VALUE``.

    :param patterns: Shell-style wildcard patterns for sensitive names.
    """

    patterns: tuple[str, ...]

    def __call__(
        self,
        logger: WrappedLogger | None,
        method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        """Replace sensitive top-level event values with a marker.

        :param logger: Logger currently processed by structlog.
        :param method_name: Logging method name such as ``info``.
        :param event_dict: Mutable structured log event.
        :return: The updated event dictionary.
        """

        matcher = SecretNameMatcher(self.patterns)
        for key in list(event_dict):
            if key.startswith("_"):
                continue
            if matcher.matches(key):
                event_dict[key] = REDACTED_VALUE
        return event_dict


@dataclass(frozen=True)
class RedactedRichTracebackFormatter:
    """Render rich tracebacks after removing sensitive local variables.

    Rich extracts locals before it renders. AppRC edits that extracted trace
    tree first, deleting any local whose name matches the configured secret
    patterns, and only then prints the traceback to the target stream.

    :param show_locals: Whether safe local variables should be shown.
    :param patterns: Shell-style wildcard patterns for sensitive names.
    :param colorize: Whether ANSI colors should be emitted.
    """

    show_locals: bool = True
    patterns: tuple[str, ...] = DEFAULT_REDACT_PATTERNS
    colorize: bool = True
    width: int | None = None
    code_width: int | None = 88
    extra_lines: int = 3
    max_frames: int = 100

    def __call__(self, sio: TextIO, exc_info: ExcInfo) -> None:
        """Write one formatted exception to ``sio``.

        :param sio: Stream receiving the rendered traceback.
        :param exc_info: Concrete exception tuple.
        :return: ``None``.
        """

        trace = Traceback.extract(
            *exc_info,
            show_locals=self.show_locals,
            locals_max_length=10,
            locals_max_string=80,
            locals_hide_dunder=True,
            locals_hide_sunder=False,
        )
        _redact_rich_trace_locals(trace, SecretNameMatcher(self.patterns))
        _mark_missing_source_frames_for_local_rendering(trace)
        traceback = Traceback(
            trace,
            width=self.width,
            code_width=self.code_width,
            extra_lines=self.extra_lines,
            word_wrap=True,
            show_locals=self.show_locals,
            indent_guides=True,
            locals_max_length=10,
            locals_max_string=80,
            locals_hide_dunder=True,
            locals_hide_sunder=False,
            max_frames=self.max_frames,
        )

        sio.write("\n")
        console = Console(
            file=sio,
            color_system=_color_system(self.colorize),
            no_color=not self.colorize,
            width=self.width,
        )
        console.print(traceback)


@dataclass(frozen=True)
class RedactedExceptionDictTransformer:
    """Return JSON-ready exception dictionaries with redacted locals.

    Structlog's JSON renderer cannot use Rich console output directly. This
    transformer asks structlog for nested exception dictionaries and then
    removes sensitive locals from every frame before JSON serialization.

    :param show_locals: Whether safe local variables should be included.
    :param patterns: Shell-style wildcard patterns for sensitive names.
    """

    show_locals: bool = True
    patterns: tuple[str, ...] = DEFAULT_REDACT_PATTERNS

    def __call__(self, exc_info: ExcInfo) -> list[dict[str, Any]]:
        """Return exception stack dictionaries for JSON rendering.

        :param exc_info: Concrete exception tuple.
        :return: JSON-serializable stack dictionaries.
        """

        transformer = ExceptionDictTransformer(
            show_locals=self.show_locals,
            locals_max_length=10,
            locals_max_string=80,
            locals_hide_dunder=True,
            locals_hide_sunder=False,
            max_frames=50,
            use_rich=True,
        )
        stacks = transformer(exc_info)
        _redact_exception_dict_locals(stacks, SecretNameMatcher(self.patterns))
        return stacks


def json_exception_renderer(
    *,
    show_locals: bool,
    patterns: tuple[str, ...],
) -> ExceptionRenderer:
    """Create a structlog exception renderer for JSON logs.

    The returned processor reads ``exc_info`` from the event dictionary and
    writes an ``exception`` field containing redacted stack dictionaries. It is
    used only by the JSON formatter chain.

    :param show_locals: Whether safe local variables should be included.
    :param patterns: Shell-style wildcard patterns for sensitive names.
    :return: Structlog processor that writes an ``exception`` field.
    """

    transformer = RedactedExceptionDictTransformer(
        show_locals=show_locals,
        patterns=patterns,
    )
    return ExceptionRenderer(transformer)


def _color_system(colorize: bool) -> ColorSystem | None:
    """Return the Rich color-system setting for console tracebacks.

    :param colorize: Whether ANSI colors should be emitted.
    :return: Rich color-system name, or ``None`` for plain text.
    """

    if colorize:
        return "truecolor"
    return None


def _redact_rich_trace_locals(
    trace: Trace,
    matcher: SecretNameMatcher,
) -> None:
    """Delete sensitive local variables from a Rich trace tree.

    :param trace: Extracted Rich traceback tree.
    :param matcher: Name matcher for sensitive locals.
    :return: ``None``.
    """

    for stack in trace.stacks:
        for frame in stack.frames:
            if frame.locals is None:
                continue
            for key in list(frame.locals):
                if matcher.matches(key):
                    del frame.locals[key]
        for exception in stack.exceptions:
            _redact_rich_trace_locals(exception, matcher)


def _mark_missing_source_frames_for_local_rendering(trace: Trace) -> None:
    """Let Rich render locals when traceback source files are unavailable.

    Rich renders locals for pseudo-filenames even when source code cannot be
    loaded. Marking only frames with extracted locals keeps normal source-backed
    traceback rendering unchanged while preserving safe local-variable output
    for remapped or generated traceback paths.

    :param trace: Extracted Rich traceback tree.
    :return: ``None``.
    """

    for stack in trace.stacks:
        for frame in stack.frames:
            if frame.locals is None or frame.filename.startswith("<"):
                continue
            if not linecache.getlines(frame.filename):
                frame.filename = f"<{frame.filename}>"
        for exception in stack.exceptions:
            _mark_missing_source_frames_for_local_rendering(exception)


def _redact_exception_dict_locals(
    stacks: list[dict[str, Any]],
    matcher: SecretNameMatcher,
) -> None:
    """Delete sensitive local variables from JSON exception stacks.

    :param stacks: Structlog exception stack dictionaries.
    :param matcher: Name matcher for sensitive locals.
    :return: ``None``.
    """

    for stack in stacks:
        frames = stack.get("frames")
        if isinstance(frames, list):
            for frame in frames:
                if isinstance(frame, MutableMapping):
                    _redact_frame_dict_locals(frame, matcher)

        exceptions = stack.get("exceptions")
        if isinstance(exceptions, list):
            for nested_stacks in exceptions:
                if isinstance(nested_stacks, list):
                    _redact_exception_dict_locals(nested_stacks, matcher)


def _redact_frame_dict_locals(
    frame: MutableMapping[str, Any],
    matcher: SecretNameMatcher,
) -> None:
    """Delete sensitive local variables from one frame dictionary.

    :param frame: JSON-ready frame mapping from structlog.
    :param matcher: Name matcher for sensitive locals.
    :return: ``None``.
    """

    locals_ = frame.get("locals")
    if not isinstance(locals_, MutableMapping):
        return
    for key in list(locals_):
        if matcher.matches(str(key)):
            del locals_[key]


__all__ = [
    "DEFAULT_REDACT_PATTERNS",
    "LogFieldRedactor",
    "REDACTED_VALUE",
    "RedactedExceptionDictTransformer",
    "RedactedRichTracebackFormatter",
    "SecretNameMatcher",
    "json_exception_renderer",
    "logging_redact_patterns",
    "normalize_exc_info",
]
