"""Build PyPI-safe project documentation from the GitHub README."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CALLOUT_RE = re.compile(r"^> \[!(?P<label>[A-Z]+)\]\s*$")
GITHUB_BLOB_URL = "https://github.com/HisQu/apprc/blob/main"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/HisQu/apprc/main"
HTML_SRC_RE = re.compile(
    r"(?P<prefix>\bsrc=\")(?P<target>[^\"]+)(?P<suffix>\")"
)
MARKDOWN_IMAGE_RE = re.compile(
    r"(?P<prefix>!\[[^\]]*\]\()(?P<target>[^)\s]+)(?P<suffix>\))"
)
MARKDOWN_LINK_RE = re.compile(
    r"(?<!!)(?P<prefix>\[[^\]]+\]\()(?P<target>[^)\s]+)(?P<suffix>\))"
)


def convert_github_callouts(markdown: str) -> str:
    """Render GitHub alert blocks as plain Markdown.

    PyPI renders Markdown, but GitHub alert syntax is not portable enough for
    package descriptions. This keeps the source README pleasant on GitHub while
    producing conservative Markdown for package metadata.

    :param markdown: README text that may contain GitHub alert blocks.
    :return: Markdown with alert syntax replaced by bold labels.
    """
    lines = markdown.splitlines()
    converted: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = CALLOUT_RE.match(line)
        if match is None:
            converted.append(line)
            index += 1
            continue

        converted.append(f"**{match.group('label').title()}**")
        converted.append("")
        index += 1

        while index < len(lines) and lines[index].startswith(">"):
            quoted_line = lines[index]
            if quoted_line == ">":
                converted.append("")
            elif quoted_line.startswith("> "):
                converted.append(quoted_line[2:])
            else:
                converted.append(quoted_line[1:])
            index += 1

    output = "\n".join(converted)
    if markdown.endswith("\n"):
        return f"{output}\n"
    return output


def rewrite_repository_links(markdown: str) -> str:
    """Rewrite local repository links for PyPI's rendering context.

    :param markdown: README text with repository-relative links.
    :return: Markdown whose local docs, examples, and asset links point at
        GitHub.
    """
    markdown = HTML_SRC_RE.sub(_rewrite_html_src_match, markdown)
    markdown = MARKDOWN_IMAGE_RE.sub(_rewrite_markdown_image_match, markdown)
    return MARKDOWN_LINK_RE.sub(_rewrite_markdown_link_match, markdown)


def build_pypi_markdown(markdown: str) -> str:
    """Return PyPI-safe Markdown generated from the GitHub README.

    :param markdown: GitHub-facing README text.
    :return: Converted Markdown for package metadata.
    """
    return rewrite_repository_links(convert_github_callouts(markdown))


def build_pypi_readme(source: Path, destination: Path) -> None:
    """Convert one README file and write the PyPI metadata variant.

    :param source: GitHub-facing README file.
    :param destination: Generated PyPI-facing README file.
    """
    markdown = source.read_text(encoding="utf-8")
    destination.write_text(build_pypi_markdown(markdown), encoding="utf-8")


def _rewrite_html_src_match(match: re.Match[str]) -> str:
    """Return one HTML image tag with a PyPI-readable source."""
    target = _pypi_target(match.group("target"), image=True)
    return f"{match.group('prefix')}{target}{match.group('suffix')}"


def _rewrite_markdown_image_match(match: re.Match[str]) -> str:
    """Return one Markdown image with a PyPI-readable source."""
    target = _pypi_target(match.group("target"), image=True)
    return f"{match.group('prefix')}{target}{match.group('suffix')}"


def _rewrite_markdown_link_match(match: re.Match[str]) -> str:
    """Return one Markdown link with a PyPI-readable target."""
    target = _pypi_target(match.group("target"), image=False)
    return f"{match.group('prefix')}{target}{match.group('suffix')}"


def _pypi_target(target: str, *, image: bool) -> str:
    """Return a GitHub URL for one local repository target when needed."""
    if _target_is_portable(target):
        return target
    path, separator, anchor = target.partition("#")
    if not _target_is_repository_relative(path):
        return target
    base_url = GITHUB_RAW_URL if image else GITHUB_BLOB_URL
    rewritten = f"{base_url}/{path}"
    if separator:
        return f"{rewritten}#{anchor}"
    return rewritten


def _target_is_portable(target: str) -> bool:
    """Return whether a link already works outside the repository checkout."""
    return (
        target.startswith("#")
        or "://" in target
        or target.startswith("mailto:")
    )


def _target_is_repository_relative(path: str) -> bool:
    """Return whether a README target points at a tracked repository path."""
    if not path or path.startswith(("/", "../")):
        return False
    return (ROOT / path).exists()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the README build helper.

    :param argv: Optional argument vector used by tests.
    :return: Parsed command namespace.
    """
    parser = argparse.ArgumentParser(
        description="Generate the PyPI-safe README from README.md.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "README.md",
        help="GitHub-facing README path.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "README.pypi.md",
        help="PyPI-facing README path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PyPI README generation command.

    :param argv: Optional argument vector used by tests.
    :return: Process exit code.
    """
    args = parse_args(argv)
    build_pypi_readme(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
