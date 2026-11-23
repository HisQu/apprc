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
    toc_entry: bool | None = None,
) -> str:
    """Return a small changelog matching the repository layout.

    :param version: Released version heading and link value.
    :param unreleased_entry: Optional content left under ``[Unreleased]``.
    :param release_entry: Content placed in the released section.
    :param toc_entry: Whether to include the released version in the TOC; defaults
        to whether the version is a major/minor release.
    :return: Changelog fixture text.
    """
    anchor = f"#{version.replace('.', '')}---2026-07-13"
    if toc_entry is None:
        toc_entry = version.endswith(".0")
    version_toc = (
        f"3. [\\[{version}\\] - 2026-07-13]({anchor})\n" if toc_entry else ""
    )
    return (
        "# Changelog\n\n"
        "## Table Of Content\n\n"
        "1. [Changelog](#changelog)\n"
        "2. [[Unreleased]](#unreleased)\n"
        f"{version_toc}\n"
        "## [Unreleased]\n\n"
        "<br>\n\n"
        "### ✨ Added\n\n"
        f"{unreleased_entry}\n\n"
        "<br>\n\n"
        "### 🛠️ Changed\n\n"
        "<br>\n\n"
        "### 🗑️ Deprecated\n\n"
        "<br>\n\n"
        "### 🔥 Removed\n\n"
        "<br>\n\n"
        "### 🐛 Fixed\n\n"
        "<br>\n\n"
        "### 🔒 Security\n\n"
        "<br>\n\n"
        "---\n\n"
        "<!-- ======================================================== -->\n\n"
        f"## [{version}] - 2026-07-13\n\n"
        "<br>\n\n"
        "### ✨ Added\n\n"
        f"{release_entry}\n\n"
        "<br>\n\n"
        "---\n\n"
        "<!-- ======================================================== -->\n\n"
        "## [1.2.2] - 2026-07-12\n"
    )


def test_build_release_notes_extracts_and_cleans_version_section() -> None:
    module = load_release_notes_module()

    assert module.build_release_notes(sample_changelog(), "1.2.3") == (
        "## ✨ Added\n\n  - Added a tested release workflow.\n"
    )


def test_repository_changelog_has_compact_toc_and_nearby_references() -> None:
    module = load_release_notes_module()
    markdown = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    toc = markdown.index("## Table Of Content")
    references = markdown.index("[Unreleased]:")
    unreleased = markdown.index("## [Unreleased]")

    assert toc < references < unreleased
    for match in module.RELEASE_HEADING_RE.finditer(markdown):
        module._validate_toc_entry(markdown, match)


def test_build_release_notes_accepts_yanked_heading_and_excludes_link_definitions() -> (
    None
):
    module = load_release_notes_module()
    markdown = sample_changelog(version="1.2.0")
    markdown = markdown.replace(
        "## [1.2.0] - 2026-07-13",
        "## [1.2.0] - 2026-07-13 [YANKED]",
    )
    markdown = markdown.replace(
        "3. [\\[1.2.0\\] - 2026-07-13](#120---2026-07-13)",
        "3. [\\[1.2.0\\] - 2026-07-13 [YANKED]](#120---2026-07-13-yanked)",
    )
    markdown = markdown.replace(
        "## [1.2.2] - 2026-07-12", "## [1.1.0] - 2026-07-12"
    )
    markdown = markdown.replace(
        "## [Unreleased]\n",
        "[Unreleased]: https://example.invalid/compare\n"
        "[1.2.0]: https://example.invalid/release\n\n"
        "## [Unreleased]\n",
        1,
    )

    assert module.build_release_notes(markdown, "1.2.0") == (
        "## ✨ Added\n\n  - Added a tested release workflow.\n"
    )


def test_write_release_notes_creates_parent_directory(tmp_path: Path) -> None:
    module = load_release_notes_module()
    output = tmp_path / "release" / "notes.md"

    module.write_release_notes(sample_changelog(), "1.2.3", output)

    assert output.read_text(encoding="utf-8").startswith("## ✨ Added")


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
        "## [1.2.2] - 2026-07-12",
        "## [1.2.3] - 2026-07-13",
    )

    with pytest.raises(ValueError, match="found 2"):
        module.build_release_notes(duplicate, "1.2.3")


def test_build_release_notes_rejects_empty_release() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="has no changelog entries"):
        module.build_release_notes(sample_changelog(release_entry=""), "1.2.3")


def test_patch_release_may_be_omitted_from_toc() -> None:
    module = load_release_notes_module()

    assert module.build_release_notes(
        sample_changelog(version="1.2.3", toc_entry=False), "1.2.3"
    ).startswith("## ✨ Added")


def test_major_minor_release_requires_toc_entry() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="table of contents"):
        module.build_release_notes(
            sample_changelog(version="1.2.0", toc_entry=False), "1.2.0"
        )


def test_patch_release_must_not_be_listed_in_toc() -> None:
    module = load_release_notes_module()

    with pytest.raises(ValueError, match="Patch or preview release"):
        module.build_release_notes(
            sample_changelog(version="1.2.3", toc_entry=True), "1.2.3"
        )


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


def test_cumulative_release_notes_follow_the_prepared_stage() -> None:
    notes = load_release_notes_module()
    heading = "## [1.2.3] - 2026-07-13"
    original = sample_changelog(release_entry="- Introduce Preview installs.")
    beta = original.replace(heading, f"{heading} (b1)")
    beta2 = beta.replace("(b1)", "(b2)").replace(
        "- Introduce Preview installs.",
        "- Introduce Preview installs.\n- Fix a preview update issue.",
    )
    candidate = beta2.replace("(b2)", "(rc1)")
    stable = candidate.replace(" (rc1)", "")
    assert notes.build_release_notes(beta, "1.2.3b1") == (
        "## ✨ Added\n\n- Introduce Preview installs.\n"
    )
    cumulative = notes.build_release_notes(beta2, "1.2.3b2")
    assert cumulative == (
        "## ✨ Added\n\n- Introduce Preview installs.\n"
        "- Fix a preview update issue.\n"
    )
    assert notes.build_release_notes(candidate, "1.2.3rc1") == cumulative
    assert notes.build_release_notes(stable, "1.2.3") == cumulative

    with pytest.raises(ValueError, match="exactly one release heading"):
        notes.build_release_notes(beta2, "1.2.3b1")
    duplicate = beta2.replace("## [1.2.2] - 2026-07-12", f"{heading} (b1)")
    with pytest.raises(ValueError, match="one cumulative heading"):
        notes.build_release_notes(duplicate, "1.2.3b2")


@pytest.mark.parametrize("version", ("1.2.0b1", "1.2.0rc1"))
def test_extract_preview_release_and_prevent_toc_clutter(version: str) -> None:
    module = load_release_notes_module()
    markdown = sample_changelog(version=version)
    assert "- Added a tested release workflow." in module.build_release_notes(
        markdown, version
    )
    module.validate_tag_version(f"v{version}", version)
    with pytest.raises(ValueError, match="table of contents"):
        module.build_release_notes(
            sample_changelog(version=version, toc_entry=True), version
        )


def test_release_preparation_advances_beta_rc_and_stable_versions() -> None:
    module = load_release_notes_module()
    module.validate_next_version("1.2.0b2", "1.2.0b10")
    module.validate_next_version("1.2.0b10", "1.2.0rc1")
    module.validate_next_version("1.2.0rc1", "1.2.0")
    with pytest.raises(ValueError, match="must advance"):
        module.validate_next_version("1.2.0", "1.2.0rc2")
