"""Tests for curated GitHub Release note generation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/apprc_dev/packaging/release_notes.py"


def load_release_notes_module() -> ModuleType:
    """Load the dev helper directly from the source tree.

    :return: Imported release-note helper module.
    """
    spec = importlib.util.spec_from_file_location("release_notes", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load release-note helper.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_changelog(
    *,
    version: str = "1.2.3",
    unreleased_entry: str = "",
    release_entry: str = "  - Added a tested release workflow.",
    toc_entry: bool = True,
) -> str:
    """Return a small changelog matching the repository layout.

    :param version: Released version heading and link value.
    :param unreleased_entry: Optional content left under ``[Unreleased]``.
    :param release_entry: Content placed in the released section.
    :param toc_entry: Whether to include the released version in the TOC.
    :return: Changelog fixture text.
    """
    version_toc = (
        f"3. [{version} - 2026-07-13](#123---2026-07-13)\n" if toc_entry else ""
    )
    return (
        "# Changelog\n\n"
        "## Table Of Content\n\n"
        "1. [Changelog](#changelog)\n"
        "2. [[Unreleased]](#unreleased)\n"
        f"{version_toc}\n"
        "# [Unreleased]\n\n"
        "<br>\n\n"
        "### 💥 Breaking Change Summary\n\n"
        "<br>\n\n"
        "### ➕ Added\n\n"
        f"{unreleased_entry}\n\n"
        "<br>\n\n"
        "### 💔 Changed\n\n"
        "<br>\n\n"
        "### ⚠️ Deprecated\n\n"
        "<br>\n\n"
        "### 🗑️ Removed\n\n"
        "<br>\n\n"
        "### 🔨 Fixed\n\n"
        "<br>\n\n"
        "### 🔒 Security\n\n"
        "<br>\n\n"
        "---\n\n"
        "<!-- ======================================================== -->\n\n"
        f"# {version} - 2026-07-13\n\n"
        "<br>\n\n"
        "### ➕ Added\n\n"
        f"{release_entry}\n\n"
        "<br>\n\n"
        "---\n\n"
        "<!-- ======================================================== -->\n\n"
        "# 1.2.2 - 2026-07-12\n"
    )


def test_build_release_notes_extracts_and_cleans_version_section() -> None:
    module = load_release_notes_module()

    assert module.build_release_notes(sample_changelog(), "1.2.3") == (
        "## ➕ Added\n\n  - Added a tested release workflow.\n"
    )


def test_write_release_notes_creates_parent_directory(tmp_path: Path) -> None:
    module = load_release_notes_module()
    output = tmp_path / "release" / "notes.md"

    module.write_release_notes(sample_changelog(), "1.2.3", output)

    assert output.read_text(encoding="utf-8").startswith("## ➕ Added")


@pytest.mark.parametrize("version", ["v1.2.3", "1.2", "1.2.3.4", "01.2.3"])
def test_build_release_notes_rejects_malformed_versions(version: str) -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="Invalid release version"):
        module.build_release_notes(sample_changelog(), version)


def test_build_release_notes_rejects_missing_release() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="exactly one release heading"):
        module.build_release_notes(sample_changelog(), "1.2.4")


def test_build_release_notes_rejects_duplicate_release() -> None:
    module = load_release_notes_module()
    markdown = sample_changelog()
    duplicate = markdown.replace(
        "# 1.2.2 - 2026-07-12",
        "# 1.2.3 - 2026-07-13",
    )

    with pytest.raises(ValueError, match="found 2"):
        module.build_release_notes(duplicate, "1.2.3")


def test_build_release_notes_rejects_empty_release() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="has no changelog entries"):
        module.build_release_notes(sample_changelog(release_entry=""), "1.2.3")


def test_build_release_notes_rejects_missing_toc_entry() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="table of contents"):
        module.build_release_notes(sample_changelog(toc_entry=False), "1.2.3")


def test_build_release_notes_rejects_nonempty_unreleased_section() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="still contains release entries"):
        module.build_release_notes(
            sample_changelog(unreleased_entry="  - Not released yet."),
            "1.2.3",
        )


def test_validate_tag_version_requires_exact_project_tag() -> None:
    module = load_release_notes_module()

    module.validate_tag_version("v1.2.3", "1.2.3")
    with pytest.raises(ValueError, match="does not match project version"):
        module.validate_tag_version("v1.2.4", "1.2.3")


def test_main_rejects_partial_tag_validation_arguments(tmp_path: Path) -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="must be provided together"):
        module.main(
            [
                "1.2.3",
                "--changelog",
                str(tmp_path / "CHANGELOG.md"),
                "--output",
                str(tmp_path / "notes.md"),
                "--tag",
                "v1.2.3",
            ]
        )


def test_main_rejects_requested_version_different_from_project(
    tmp_path: Path,
) -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="does not match project version"):
        module.main(
            [
                "1.2.2",
                "--changelog",
                str(tmp_path / "CHANGELOG.md"),
                "--output",
                str(tmp_path / "notes.md"),
                "--tag",
                "v1.2.3",
                "--project-version",
                "1.2.3",
            ]
        )
