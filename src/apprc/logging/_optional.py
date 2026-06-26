"""Optional dependency helpers for AppRC logging."""

from __future__ import annotations

from importlib import import_module
from typing import Any

LOGGING_EXTRA_INSTALL_HINT = (
    "Install AppRC structured logging support with: "
    'python -m pip install "apprc[logging]"'
)


def _is_missing_structlog(exc: ModuleNotFoundError) -> bool:
    """Return whether an import failure is for structlog itself.

    :param exc: Module import failure raised while loading optional logging.
    :return: ``True`` when the optional dependency is missing.
    """

    name = exc.name or ""
    return name == "structlog" or name.startswith("structlog.")


def missing_structlog_error() -> ImportError:
    """Return the public error used when structured logging support is absent.

    :return: Import error with the AppRC logging extra installation hint.
    """

    return ImportError(LOGGING_EXTRA_INSTALL_HINT)


def optional_structlog_contextvars() -> Any | None:
    """Return structlog contextvars support when the logging extra is present.

    :return: ``structlog.contextvars`` module, or ``None`` when the optional
        dependency is not installed.
    """

    try:
        return import_module("structlog.contextvars")
    except ModuleNotFoundError as exc:
        if not _is_missing_structlog(exc):
            raise
        return None


def require_structlog() -> Any:
    """Return the structlog module or raise the AppRC install hint.

    :return: Imported ``structlog`` module.
    :raises ImportError: If the ``apprc[logging]`` extra is missing.
    """

    try:
        return import_module("structlog")
    except ModuleNotFoundError as exc:
        if not _is_missing_structlog(exc):
            raise
        raise missing_structlog_error() from exc


__all__ = [
    "LOGGING_EXTRA_INSTALL_HINT",
    "missing_structlog_error",
    "optional_structlog_contextvars",
    "require_structlog",
]
