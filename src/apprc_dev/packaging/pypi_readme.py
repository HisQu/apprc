"""Build PyPI-safe project documentation from the GitHub README."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CALLOUT_RE = re.compile(r"^> \[!(?P<label>[A-Z]+)\]\s*$")


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


def build_pypi_readme(source: Path, destination: Path) -> None:
    """Convert one README file and write the PyPI metadata variant.

    :param source: GitHub-facing README file.
    :param destination: Generated PyPI-facing README file.
    """
    markdown = source.read_text(encoding="utf-8")
    destination.write_text(convert_github_callouts(markdown), encoding="utf-8")


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
