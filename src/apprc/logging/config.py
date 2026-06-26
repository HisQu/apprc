"""Configuration for AppRC's optional structured logging formatter.

Entrypoints call ``setup_logging`` once near startup. That function installs
``AppLogger`` for future named loggers, configures a root or named stdlib
handler, and attaches a structlog ``ProcessorFormatter``. From that point on,
both application semantic loggers and plain dependency loggers can propagate to
the selected handler.

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

from apprc.logging._optional import require_structlog
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


DEFAULT_DEPENDENCY_LEVELS: dict[str, int] = {}


@dataclass
class LoggingConfig:
    """Configuration for one stdlib/structlog setup call.

    The dataclass is the internal normalized shape used after public
    ``setup_logging`` arguments and default dependency levels are merged. It is
    passed through the private setup helpers so those helpers do not need to
    know about public defaults.

    :param level: Root or named logger level name or number.
    :param renderer: Console renderer layout.
    :param colorize: Whether ANSI colors should be emitted.
    :param collapse_same_second: Whether equal timestamp seconds are blanked.
    :param exception_show_locals: Whether safe traceback locals should render.
    :param extra_redact_patterns: Additional secret-name patterns to redact.
    :param dependency_levels: Levels applied to noisy upstream loggers.
    :param force: Whether to replace existing target logger handlers.
    :param logger: Optional named logger to configure instead of the root
        logger.
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
    logger: str | logging.Logger | None = None


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
    logger: str | logging.Logger | None = None,
) -> None:
    """Configure stdlib handlers and optional structlog processors.

    The function is intentionally idempotent by default. If target handlers
    already exist and ``force`` is false, AppRC only updates the target level
    and leaves handler ownership alone. With ``force=True``, target handlers
    are replaced with a ``StreamHandler`` whose formatter runs the full
    structlog processor chain.

    When ``logger`` is provided, AppRC configures that named logger instead of
    the root logger and disables propagation so the named application can be
    embedded without taking over the host application's root logging.

    :param level: Root or named logger level name or number.
    :param renderer: Console renderer layout.
    :param colorize: Whether ANSI colors should be emitted.
    :param collapse_same_second: Whether equal timestamp seconds are blanked.
    :param exception_show_locals: Whether safe traceback locals should render.
    :param extra_redact_patterns: Additional secret-name patterns to redact.
    :param dependency_levels: Optional dependency logger level overrides.
    :param force: Whether to replace existing target logger handlers.
    :param logger: Optional named logger or logger instance to configure
        instead of the root logger.
    """

    structlog_module = require_structlog()
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
        logger=logger,
    )
    _configure_stdlib(config, structlog_module)
    _configure_dependency_loggers(config.dependency_levels)


def _configure_stdlib(config: LoggingConfig, structlog_module: Any) -> None:
    """Install or update the selected stdlib logging handler.

    :param config: Normalized logging configuration.
    :param structlog_module: Imported structlog module from the logging extra.
    :return: ``None``.
    """

    target = _target_logger(config.logger)
    if target.handlers and not config.force:
        target.setLevel(config.level)
        if config.logger is not None:
            target.propagate = False
        return

    target.handlers.clear()
    target.setLevel(config.level)
    if config.logger is not None:
        target.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_processor_formatter(config, structlog_module))
    target.addHandler(handler)


def _target_logger(logger: str | logging.Logger | None) -> logging.Logger:
    """Return the stdlib logger selected for setup.

    :param logger: Optional named logger or logger instance.
    :return: Root logger when ``logger`` is ``None``; otherwise the selected
        named logger.
    """

    if logger is None:
        return logging.getLogger()
    if isinstance(logger, logging.Logger):
        return logger
    return logging.getLogger(logger)


def _processor_formatter(
    config: LoggingConfig,
    structlog_module: Any,
) -> logging.Formatter:
    """Build the formatter that converts ``LogRecord`` objects to output.

    ``ExtraAdder`` copies stdlib ``extra`` fields, including AppRC
    ``extra_struct`` values already merged by ``AppLogger``. The custom
    processors then add record metadata, task/correlation context, semantic
    defaults, and redaction before the renderer receives the event dictionary.

    :param config: Normalized logging configuration.
    :param structlog_module: Imported structlog module from the logging extra.
    :return: Structlog formatter installed on the root handler.
    """

    redact_patterns = logging_redact_patterns(config.extra_redact_patterns)
    shared_processors: list[Any] = [
        structlog_module.contextvars.merge_contextvars,
        structlog_module.stdlib.ExtraAdder(),
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
            structlog_module.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog_module.processors.EventRenamer(to="message"),
            structlog_module.processors.JSONRenderer(),
        ]
        return structlog_module.stdlib.ProcessorFormatter(
            foreign_pre_chain=_foreign_pre_chain(structlog_module),
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
        structlog_module.stdlib.ProcessorFormatter.remove_processors_meta,
        renderer,
    ]
    return structlog_module.stdlib.ProcessorFormatter(
        foreign_pre_chain=_foreign_pre_chain(structlog_module),
        processors=processors,
    )


def _foreign_pre_chain(structlog_module: Any) -> list[Any]:
    """Return processors used for non-structlog stdlib records.

    :param structlog_module: Imported structlog module from the logging extra.
    :return: Pre-chain processors that run before formatter processors.
    """

    return [
        structlog_module.contextvars.merge_contextvars,
        add_runtime_context,
    ]


def _configure_dependency_loggers(levels: dict[str, int]) -> None:
    """Apply level overrides to dependency loggers.

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
