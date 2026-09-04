"""Build GitHub Release notes from AppRC's curated changelog."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
RELEASE_HEADING_RE = re.compile(
    r"^# (?P<version>\d+\.\d+\.\d+) - (?P<date>\d{4}-\d{2}-\d{2})$",
    re.MULTILINE,
)
UNRELEASED_HEADING = "# [Unreleased]"
UNRELEASED_SECTIONS = (
    "### 💥 Breaking changes",
    "### ➕ Added",
    "### 💔 Changed",
    "### ⚠️ Deprecated",
    "### 🗑️ Removed",
    "### 🔨 Fixed",
    "### 🔒 Security",
)


def build_release_notes(markdown: str, version: str) -> str:
    """Return one released changelog section as GitHub-ready Markdown.

    The changelog remains the release-note source of truth. This removes only
    repository layout markup and promotes category headings so the extracted
    section has a useful hierarchy below the GitHub Release title.

    :param markdown: Complete changelog text.
    :param version: Released semantic version without a leading ``v``.
    :return: Cleaned Markdown for a GitHub Release body.
    """
    validate_version(version)
    validate_unreleased_section(markdown)
    match = _release_heading(markdown, version)
    _validate_toc_entry(markdown, match)

    next_heading = re.search(r"^# ", markdown[match.end() :], re.MULTILINE)
    section_end = (
        match.end() + next_heading.start()
        if next_heading is not None
        else len(markdown)
    )
    notes = _clean_release_markdown(markdown[match.end() : section_end])
    if not any(line.lstrip().startswith("- ") for line in notes.splitlines()):
        raise ValueError(f"Release {version} has no changelog entries.")
    return f"{notes}\n"


def validate_version(version: str) -> None:
    """Reject release identifiers outside AppRC's three-part version scheme.

    :param version: Candidate version without a leading ``v``.
    """
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(
            f"Invalid release version {version!r}; expected MAJOR.MINOR.PATCH."
        )


def validate_tag_version(tag: str, project_version: str) -> None:
    """Ensure a pushed release tag names the checked-out project version.

    :param tag: Git tag expected to use the ``vMAJOR.MINOR.PATCH`` form.
    :param project_version: Version read from project metadata.
    """
    validate_version(project_version)
    expected_tag = f"v{project_version}"
    if tag != expected_tag:
        raise ValueError(
            f"Release tag {tag!r} does not match project version "
            f"{project_version!r}; expected {expected_tag!r}."
        )


def validate_unreleased_section(markdown: str) -> None:
    """Ensure the release commit contains the empty changelog template.

    :param markdown: Complete changelog text.
    """
    if markdown.count(UNRELEASED_HEADING) != 1:
        raise ValueError(
            "Changelog must contain exactly one [Unreleased] heading."
        )

    start = markdown.index(UNRELEASED_HEADING) + len(UNRELEASED_HEADING)
    next_release = RELEASE_HEADING_RE.search(markdown, start)
    if next_release is None:
        raise ValueError(
            "Changelog has no released section after [Unreleased]."
        )

    section = markdown[start : next_release.start()]
    for heading in UNRELEASED_SECTIONS:
        if section.count(heading) != 1:
            raise ValueError(
                "The [Unreleased] section must contain each release category "
                f"exactly once; invalid heading: {heading!r}."
            )

    content_lines = [
        line for line in _content_lines(section) if not line.startswith("### ")
    ]
    if content_lines:
        raise ValueError(
            "The [Unreleased] section still contains release entries; move "
            "them into the prepared version before tagging."
        )


def write_release_notes(markdown: str, version: str, output: Path) -> None:
    """Write extracted notes to a workflow artifact path.

    :param markdown: Complete changelog text.
    :param version: Released semantic version without a leading ``v``.
    :param output: Destination Markdown file.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_release_notes(markdown, version), encoding="utf-8")


def _release_heading(markdown: str, version: str) -> re.Match[str]:
    """Return the unique released-version heading match."""
    matches = [
        match
        for match in RELEASE_HEADING_RE.finditer(markdown)
        if match.group("version") == version
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Changelog must contain exactly one release heading for {version}; "
            f"found {len(matches)}."
        )
    return matches[0]


def _validate_toc_entry(markdown: str, match: re.Match[str]) -> None:
    """Ensure the release heading is linked from the changelog table of contents."""
    version = match.group("version")
    date = match.group("date")
    anchor = f"#{version.replace('.', '')}---{date}"
    entry = f"[{version} - {date}]({anchor})"
    if markdown.count(entry) != 1:
        raise ValueError(
            f"Changelog table of contents must contain exactly one {entry!r} entry."
        )


def _clean_release_markdown(section: str) -> str:
    """Remove changelog layout markers and compact blank lines."""
    cleaned: list[str] = []
    previous_blank = True
    for line in section.splitlines():
        stripped = line.strip()
        if _is_layout_line(stripped):
            continue
        if line.startswith("### "):
            line = line[1:]
        if not stripped:
            if not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


def _content_lines(section: str) -> list[str]:
    """Return non-empty lines that are not changelog layout markers."""
    return [
        line.strip()
        for line in section.splitlines()
        if line.strip() and not _is_layout_line(line.strip())
    ]


def _is_layout_line(line: str) -> bool:
    """Return whether one line exists only for changelog page layout."""
    return (
        line == "<br>"
        or line == "---"
        or (line.startswith("<!--") and line.endswith("-->"))
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse release-note command arguments.

    :param argv: Optional argument vector used by tests.
    :return: Parsed command namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract one GitHub Release body from CHANGELOG.md.",
    )
    parser.add_argument("version", help="Release version without a leading v.")
    parser.add_argument(
        "--changelog",
        type=Path,
        default=ROOT / "CHANGELOG.md",
        help="Changelog source path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the extracted release notes.",
    )
    parser.add_argument(
        "--tag",
        help="Optional pushed tag to compare with --project-version.",
    )
    parser.add_argument(
        "--project-version",
        help="Optional checked-out project version to compare with --tag.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate release state and write GitHub Release notes.

    :param argv: Optional argument vector used by tests.
    :return: Process exit code.
    """
    args = parse_args(argv)
    if (args.tag is None) != (args.project_version is None):
        raise ValueError(
            "--tag and --project-version must be provided together."
        )
    if args.tag is not None:
        validate_tag_version(args.tag, args.project_version)
        if args.version != args.project_version:
            raise ValueError(
                f"Requested release version {args.version!r} does not match "
                f"project version {args.project_version!r}."
            )
    markdown = args.changelog.read_text(encoding="utf-8")
    write_release_notes(markdown, args.version, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
