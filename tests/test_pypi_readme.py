"""Tests for PyPI README generation helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/apprc_dev/packaging/pypi_readme.py"


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


def test_rewrite_repository_links_uses_github_urls() -> None:
    module = load_pypi_readme_module()

    source = (
        "[Docs](docs/References.md#public-interfaces)\n"
        "[Examples](examples/example_apps)\n"
        "[Env](.env.example_apps)\n"
        "![Figure](docs/assets/apprc-abstract-user-journey.svg)\n"
        '<img src="docs/assets/apprc-abstract-contract-workflows.svg">\n'
        "[Anchor](#local)\n"
        "[External](https://example.com)\n"
    )

    assert module.rewrite_repository_links(source) == (
        "[Docs](https://github.com/HisQu/apprc/blob/main/"
        "docs/References.md#public-interfaces)\n"
        "[Examples](https://github.com/HisQu/apprc/blob/main/"
        "examples/example_apps)\n"
        "[Env](https://github.com/HisQu/apprc/blob/main/"
        ".env.example_apps)\n"
        "![Figure](https://raw.githubusercontent.com/HisQu/apprc/main/"
        "docs/assets/apprc-abstract-user-journey.svg)\n"
        '<img src="https://raw.githubusercontent.com/HisQu/apprc/main/'
        'docs/assets/apprc-abstract-contract-workflows.svg">\n'
        "[Anchor](#local)\n"
        "[External](https://example.com)\n"
    )


def test_pypi_readme_is_generated_from_github_readme() -> None:
    module = load_pypi_readme_module()
    github_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pypi_readme = (ROOT / "README.pypi.md").read_text(encoding="utf-8")

    assert pypi_readme == module.build_pypi_markdown(github_readme)
    assert "](docs/" not in pypi_readme
    assert 'src="docs/assets/' not in pypi_readme
