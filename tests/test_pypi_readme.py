"""Tests for PyPI README generation helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/apprc_dev/build/pypi_readme.py"


def load_pypi_readme_module() -> ModuleType:
    """Load the dev helper directly from the source tree.

    :return: Imported README helper module.
    """
    spec = importlib.util.spec_from_file_location("pypi_readme", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load PyPI README helper.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_convert_github_callouts_renders_plain_markdown() -> None:
    module = load_pypi_readme_module()

    source = (
        "# Example\n\n"
        "> [!IMPORTANT]\n"
        "> ### Prerequisites\n"
        "> - Python >=3.12\n\n"
        "Body\n"
    )

    assert module.convert_github_callouts(source) == (
        "# Example\n\n"
        "**Important**\n\n"
        "### Prerequisites\n"
        "- Python >=3.12\n\n"
        "Body\n"
    )
