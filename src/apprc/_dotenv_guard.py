"""Stdlib-only helpers for guarding dotenv autoload side effects."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def _disable_dotenv_autoload() -> Iterator[None]:
    """Temporarily disable libraries that auto-load ``.env`` files.

    Some libraries import ``python-dotenv`` through their dependency graph.
    Setting ``PYTHON_DOTENV_DISABLED`` around those imports preserves the
    application's explicit environment loading policy while restoring the
    user's original process environment afterward.

    :return: Context manager that restores ``PYTHON_DOTENV_DISABLED``.
    """
    prev = os.environ.get("PYTHON_DOTENV_DISABLED")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("PYTHON_DOTENV_DISABLED", None)
        else:
            os.environ["PYTHON_DOTENV_DISABLED"] = prev
