"""Configuration for Haiu's stdlib-backed structlog logging.

Entrypoints call ``setup_logging`` once near startup. That function installs
``AppLogger`` for future named loggers, configures the root stdlib handler,
and attaches a structlog ``ProcessorFormatter``. From that point on, both Haiu
semantic loggers and plain dependency loggers can propagate to the same root
handler.

The processor chain has two jobs. First it enriches stdlib records with
structured fields, runtime context, semantic display defaults, and redaction.
Then it chooses the final representation: a human console renderer for
``mini``/``cli``/``ipy`` modes, or JSON with serialized exceptions for machine
consumption.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import structlog

from apprc.logging.context import (
    add_log_record_fields,
    add_runtime_context,
)
from apprc.logging.core import install_app_logger_class
from apprc.logging.exceptions import (
    LogFieldRedactor,
    RedactedRichTracebackFormatter,
    json_exception_renderer,
    logging_redact_patterns,
)
from apprc.logging.formats import (
    AppConsoleRenderer,
    RendererMode,
    add_semantic_defaults,
)


LoggingRenderer = Literal["mini", "cli", "ipy", "json"]


DEFAULT_DEPENDENCY_LEVELS: dict[str, int] = {
    "PIL": logging.WARNING,
    "lightrag": logging.INFO,
    "matplotlib": logging.WARNING,
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "openai": logging.INFO,
}


@dataclass
class LoggingConfig:
    """Configuration for one stdlib/structlog setup call.

    The dataclass is the internal normalized shape used after public
    ``setup_logging`` arguments and default dependency levels are merged. It is
    passed through the private setup helpers so those helpers do not need to
    know about public defaults.

    :param level: Root logging level name or number.
    :param renderer: Console renderer layout.
    :param colorize: Whether ANSI colors should be emitted.
    :param collapse_same_second: Whether equal timestamp seconds are blanked.
    :param exception_show_locals: Whether safe traceback locals should render.
    :param extra_redact_patterns: Additional secret-name patterns to redact.
    :param dependency_levels: Levels applied to noisy upstream loggers.
    :param force: Whether to replace existing root handlers.
    """

    level: str | int = "INFO"
    renderer: LoggingRenderer = "mini"
    colorize: bool = True
    collapse_same_second: bool = True
    exception_show_locals: bool = True
    extra_redact_patterns: tuple[str, ...] = ()
    dependency_levels: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_DEPENDENCY_LEVELS)
    )
    force: bool = False


def setup_logging(
    level: str | int = "INFO",
    *,
    renderer: LoggingRenderer = "mini",
    colorize: bool = True,
    collapse_same_second: bool = True,
    exception_show_locals: bool = True,
    extra_redact_patterns: Sequence[str] = (),
    dependency_levels: dict[str, int] | None = None,
    force: bool = False,
) -> None:
    """Configure stdlib handlers and structlog processors.

    The function is intentionally idempotent by default. If root handlers
    already exist and ``force`` is false, Haiu only updates the root level and
    leaves handler ownership alone. With ``force=True``, root handlers are
    replaced with a ``StreamHandler`` whose formatter runs the full structlog
    processor chain.

    :param level: Root logging level name or number.
    :param renderer: Console renderer layout.
    :param colorize: Whether ANSI colors should be emitted.
    :param collapse_same_second: Whether equal timestamp seconds are blanked.
    :param exception_show_locals: Whether safe traceback locals should render.
    :param extra_redact_patterns: Additional secret-name patterns to redact.
    :param dependency_levels: Optional dependency logger level overrides.
    :param force: Whether to replace existing root handlers.
    """

    install_app_logger_class()
    effective_dependency_levels = {
        **DEFAULT_DEPENDENCY_LEVELS,
        **(dependency_levels or {}),
    }
    config = LoggingConfig(
        level=level,
        renderer=renderer,
        colorize=colorize,
        collapse_same_second=collapse_same_second,
        exception_show_locals=exception_show_locals,
        extra_redact_patterns=tuple(extra_redact_patterns),
        dependency_levels=effective_dependency_levels,
        force=force,
    )
    _configure_stdlib(config)
    _configure_dependency_loggers(config.dependency_levels)


def _configure_stdlib(config: LoggingConfig) -> None:
    """Install or update the root stdlib logging handler.

    :param config: Normalized logging configuration.
    :return: ``None``.
    """

    root = logging.getLogger()
    if root.handlers and not config.force:
        root.setLevel(config.level)
        return

    root.handlers.clear()
    root.setLevel(config.level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_processor_formatter(config))
    root.addHandler(handler)


def _processor_formatter(
    config: LoggingConfig,
) -> structlog.stdlib.ProcessorFormatter:
    """Build the formatter that converts ``LogRecord`` objects to output.

    ``ExtraAdder`` copies stdlib ``extra`` fields, including Haiu
    ``extra_struct`` values already merged by ``AppLogger``. The custom
    processors then add record metadata, task/correlation context, semantic
    defaults, and redaction before the renderer receives the event dictionary.

    :param config: Normalized logging configuration.
    :return: Structlog formatter installed on the root handler.
    """

    redact_patterns = logging_redact_patterns(config.extra_redact_patterns)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.ExtraAdder(),
        add_log_record_fields,
        add_runtime_context,
        add_semantic_defaults,
        LogFieldRedactor(redact_patterns),
    ]
    if config.renderer == "json":
        processors = [
            *shared_processors,
            json_exception_renderer(
                show_locals=config.exception_show_locals,
                patterns=redact_patterns,
            ),
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.EventRenamer(to="message"),
            structlog.processors.JSONRenderer(),
        ]
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_foreign_pre_chain(),
            processors=processors,
        )

    renderer = AppConsoleRenderer(
        mode=cast(RendererMode, config.renderer),
        colorize=config.colorize,
        collapse_same_second=config.collapse_same_second,
        exception_formatter=RedactedRichTracebackFormatter(
            show_locals=config.exception_show_locals,
            patterns=redact_patterns,
            colorize=config.colorize,
        ),
    )
    processors = [
        *shared_processors,
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        renderer,
    ]
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_foreign_pre_chain(),
        processors=processors,
    )


def _foreign_pre_chain() -> list[Any]:
    """Return processors used for non-structlog stdlib records.

    :return: Pre-chain processors that run before formatter processors.
    """

    return [
        structlog.contextvars.merge_contextvars,
        add_runtime_context,
    ]


def _configure_dependency_loggers(levels: dict[str, int]) -> None:
    """Route noisy dependency loggers through the root Haiu handler.

    :param levels: Logger-name to stdlib-level mapping.
    :return: ``None``.
    """

    for name, level in levels.items():
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)


__all__ = [
    "DEFAULT_DEPENDENCY_LEVELS",
    "LoggingConfig",
    "LoggingRenderer",
    "setup_logging",
]
