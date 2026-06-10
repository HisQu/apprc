"""Pytest bootstrap helpers for repository-local example imports."""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """Expose the repository-local example package during test collection.

    The dev-only example app lives under ``examples/`` and is usually
    importable through the editable development environment. Pytest collection
    can also run directly from the source tree, so we add that source root to
    ``sys.path`` here to keep the renamed example package importable in tests.

    :return: ``None``.
    """
    example_src = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "apprc_example_app"
        / "src"
    )
    example_src_text = str(example_src)
    if example_src_text not in sys.path:
        sys.path.insert(0, example_src_text)
