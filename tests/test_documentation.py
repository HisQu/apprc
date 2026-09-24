"""Check documentation links and execute the independent guide programs."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FENCE = re.compile(r"^```[^\n]*\n.*?^```\s*$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"!?\[([^\]\n]*)\]\(([^\s)]+)\)")
EXAMPLE_FILE = re.compile(
    r"<!-- example-file: ([^\n]+) -->\s*```[^\n]*\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)
HEADING = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)
TOC_ENTRY = re.compile(r"^( *)- \[([^\]]+)\]\(#([^)]+)\)$", re.MULTILINE)


def _heading_slug(heading: str) -> str:
    """Return GitHub's anchor stem for one Markdown heading.

    :param heading: Heading text, including any inline link or HTML markup.
    :return: Anchor stem before duplicate-heading suffixes.
    """
    heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
    heading = re.sub(r"<[^>]+>", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")


def _anchors(text: str) -> set[str]:
    """Collect GitHub heading anchors and explicit compatibility anchors.

    :param text: Markdown source.
    :return: Local section identifiers.
    """
    text = FENCE.sub("", text)
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    counts: dict[str, int] = {}
    for _, heading in HEADING.findall(text):
        slug = _heading_slug(heading)
        count = counts.get(slug, 0)
        result.add(f"{slug}-{count}" if count else slug)
        counts[slug] = count + 1
    return result


def test_documentation_outline() -> None:
    """Require grouped TOCs and spacing on the six main documentation pages."""
    for path in sorted(DOCS.glob("*.md")):
        text = FENCE.sub("", path.read_text())
        headings = list(HEADING.finditer(text))
        assert headings and headings[0].group(1) == "#", path
        groups = [match for match in headings[1:] if match.group(1) == "#"]
        assert groups, path
        toc = TOC_ENTRY.findall(text[: groups[0].start()])

        expected: list[tuple[str, str, str]] = []
        counts: dict[str, int] = {}
        active_group = False
        group_has_section = False
        for index, match in enumerate(headings):
            level, title = match.groups()
            stem = _heading_slug(title)
            count = counts.get(stem, 0)
            anchor = f"{stem}-{count}" if count else stem
            counts[stem] = count + 1
            if index == 0:
                continue
            if level == "#":
                if active_group:
                    assert group_has_section, (path, title)
                assert (
                    text[: match.start()].rstrip().splitlines()[-1] == "<br>"
                ), (
                    path,
                    title,
                )
                expected.append(("", title, anchor))
                active_group = True
                group_has_section = False
            elif level == "##":
                assert active_group, (path, title)
                expected.append(("  ", title, anchor))
                group_has_section = True
        assert group_has_section, path
        assert toc == expected, (path, toc, expected)


def test_documentation_links() -> None:
    """Keep local documents, source links, and chapter links reachable."""
    paths = [ROOT / "README.md", *DOCS.glob("*.md")]
    paths.extend((ROOT / "examples").rglob("README.md"))
    errors: list[str] = []
    for path in paths:
        text = FENCE.sub("", path.read_text())
        for _, href in LINK.findall(text):
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                continue
            target = (
                (path.parent / unquote(parsed.path)).resolve()
                if parsed.path
                else path
            )
            if not target.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing {href}")
            elif parsed.fragment and target.suffix == ".md":
                if unquote(parsed.fragment) not in _anchors(target.read_text()):
                    errors.append(
                        f"{path.relative_to(ROOT)}: missing anchor {href}"
                    )
    assert not errors, "\n".join(errors)


def test_documentation_page_names() -> None:
    """Reject navigation aliases while allowing descriptive section links."""
    labels = {
        "Explanations.md": "Explanations",
        "How-To-User-Guides.md": "How-to user guides",
        "References.md": "References",
        "EXAMPLES.md": "Examples",
        "Development.md": "Development",
    }
    for path in [ROOT / "README.md", *DOCS.glob("*.md")]:
        for label, href in LINK.findall(FENCE.sub("", path.read_text())):
            target = urlsplit(href)
            if (
                not target.scheme
                and not target.fragment
                and Path(target.path).name in labels
            ):
                assert label == labels[Path(target.path).name], (
                    path,
                    label,
                    href,
                )


def _guide_examples() -> list[tuple[str, list[tuple[str, str]]]]:
    """Read complete example files from the guides and Examples document."""
    result: list[tuple[str, list[tuple[str, str]]]] = []
    for path in (DOCS / "How-To-User-Guides.md", DOCS / "EXAMPLES.md"):
        for section in re.split(r"^## ", path.read_text(), flags=re.MULTILINE)[
            1:
        ]:
            title = section.splitlines()[0]
            files = EXAMPLE_FILE.findall(section)
            if files:
                result.append((title, files))
    return result


def _run_example(directory: Path, *arguments: str) -> str:
    """Run a guide command with no inherited demonstration settings.

    :param directory: Isolated directory containing the example files.
    :param arguments: Arguments passed to the current Python interpreter.
    :return: Standard output from a successful command.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DEMO_")
    }
    env["DEMO_APPRC_DIR"] = str(directory / "demo-config")
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize(
    "title,files",
    _guide_examples(),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_independent_documentation_example(
    title: str,
    files: list[tuple[str, str]],
    tmp_path: Path,
) -> None:
    """Execute exactly the example files printed in the documentation."""
    for name, content in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    if title == "Add configuration commands to Typer":
        assert "config" in _run_example(tmp_path, "demo.py", "--help")
        assert _run_example(tmp_path, "demo.py", "run").strip() == "30"
        _run_example(tmp_path, "demo.py", "config", "setup", "--yes")
        _run_example(
            tmp_path,
            "demo.py",
            "config",
            "set",
            "client.timeout",
            "20",
            "--scope",
            "user",
        )
        assert _run_example(tmp_path, "demo.py", "run").strip() == "20"
        _run_example(tmp_path, "demo.py", "config", "doctor", "--json")
    else:
        _run_example(tmp_path, "demo.py")


def test_section_bundle_example(tmp_path: Path) -> None:
    """Keep the documented multi-section output tied to executable source."""
    output = _run_example(
        tmp_path, str(ROOT / "examples" / "section_bundle.py")
    )
    assert output.splitlines() == [
        "json: timeout=10",
        "one request: timeout=5",
        "json: timeout=20",
    ]


def test_documented_config_scaffold(tmp_path: Path) -> None:
    """Verify the package-generation guide with the real scaffold command."""
    _run_example(
        tmp_path,
        "-m",
        "apprc",
        "scaffold",
        "config",
        "--package",
        "myapp",
        "--app-id",
        "myapp",
        "--target",
        "src",
        "--user-dotenv",
    )
    (tmp_path / "src" / "demo.py").write_text(
        "from myapp.config.app import MyRC\n"
        "from myapp.config.bundle import MyappConfig\n"
        "print(type(MyRC.resolve(environment={}).build(MyappConfig)).__name__)\n"
    )
    assert _run_example(tmp_path, "src/demo.py").strip() == "MyappConfig"
