"""Distribution metadata and generated-version coordination."""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from apprc_dev.packaging.terminal_metadata import ROOT, generated_files


def test_terminal_wrapper_owns_no_packages_and_pins_matching_core() -> None:
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())
    wrapper = tomllib.loads(
        (ROOT / "src/apprc_dev/packaging/terminal/pyproject.toml").read_text()
    )
    assert core["project"]["name"] == "apprc-core"
    assert wrapper["project"]["version"] == core["project"]["version"]
    assert (
        f"apprc-core=={core['project']['version']}"
        in wrapper["project"]["dependencies"]
    )
    assert wrapper["tool"]["setuptools"] == {"packages": [], "py-modules": []}
    assert "scripts" not in core["project"]
    assert wrapper["project"]["scripts"] == {"apprc": "apprc.__main__:main"}


def test_gui_distribution_owns_only_its_view_and_pins_matching_core() -> None:
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())
    gui = tomllib.loads(
        (ROOT / "src/apprc_dev/packaging/gui/pyproject.toml").read_text()
    )
    assert gui["project"]["name"] == "apprc-gui"
    assert gui["project"]["version"] == core["project"]["version"]
    assert (
        f"apprc-core=={core['project']['version']}"
        in gui["project"]["dependencies"]
    )
    assert gui["tool"]["setuptools"]["package-dir"] == {"": "src"}


def test_gui_metadata_sync_handles_current_and_simulated_versions(
    tmp_path: Path,
) -> None:
    from apprc_dev.packaging.gui_metadata import sync_gui_metadata

    gui_path = ROOT / "src/apprc_dev/packaging/gui/pyproject.toml"
    gui_source = gui_path.read_text(encoding="utf-8")
    core_version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    sync_gui_metadata(core_version, path=gui_path, check=True)

    simulated_path = tmp_path / "gui-pyproject.toml"
    simulated_path.write_text(gui_source, encoding="utf-8")
    sync_gui_metadata("0.27.1", path=simulated_path)
    sync_gui_metadata("0.27.1", path=simulated_path, check=True)

    simulated_project = tomllib.loads(
        simulated_path.read_text(encoding="utf-8")
    )["project"]
    assert simulated_project["version"] == "0.27.1"
    assert "apprc-core==0.27.1" in simulated_project["dependencies"]
    assert "gradio>=6.26,<7" in simulated_project["dependencies"]


@pytest.mark.parametrize(
    ("old_version", "release_version", "upper_bound"),
    [
        ("0.33.0", "0.34.0", "0.35"),
        ("0.34.0", "0.34.1", "0.35"),
        ("0.34.0", "1.0.0", "1.1"),
    ],
)
def test_example_requirements_track_release_transaction(
    tmp_path: Path,
    old_version: str,
    release_version: str,
    upper_bound: str,
) -> None:
    from packaging.requirements import Requirement

    from apprc_dev.packaging.example_metadata import sync_example_metadata

    initial = (ROOT / "examples/example_apps/pyproject.toml").read_text(
        encoding="utf-8"
    )
    metadata = tmp_path / "examples-pyproject.toml"
    metadata.write_text(initial, encoding="utf-8")
    sync_example_metadata(old_version, path=metadata)

    sync_example_metadata(release_version, path=metadata)
    sync_example_metadata(release_version, path=metadata, check=True)
    project = tomllib.loads(metadata.read_text(encoding="utf-8"))["project"]
    for name, dependencies in (
        ("apprc", project["dependencies"]),
        ("apprc-gui", project["optional-dependencies"]["desktop"]),
    ):
        requirement = next(
            Requirement(item)
            for item in dependencies
            if Requirement(item).name == name
        )
        expected = Requirement(
            f"{name}>={release_version},<{upper_bound}"
        ).specifier
        assert requirement.specifier == expected
        assert release_version in requirement.specifier

    before_stale_check = metadata.read_bytes()
    with pytest.raises(SystemExit, match="Example metadata is stale"):
        sync_example_metadata(old_version, path=metadata, check=True)
    assert metadata.read_bytes() == before_stale_check


def test_example_metadata_is_current_and_preserves_unmanaged_content(
    tmp_path: Path,
) -> None:
    from packaging.requirements import Requirement

    from apprc_dev.packaging.example_metadata import sync_example_metadata

    version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    metadata = ROOT / "examples/example_apps/pyproject.toml"
    sync_example_metadata(version, path=metadata, check=True)
    source = metadata.read_text(encoding="utf-8")
    isolated = tmp_path / "pyproject.toml"
    isolated.write_text(source, encoding="utf-8")
    original_project = tomllib.loads(source)["project"]
    sync_example_metadata("99.0.0", path=isolated)
    updated_project = tomllib.loads(isolated.read_text(encoding="utf-8"))[
        "project"
    ]
    assert updated_project["version"] == original_project["version"]
    assert updated_project["scripts"] == original_project["scripts"]
    for name, dependencies in (
        ("apprc", updated_project["dependencies"]),
        ("apprc-gui", updated_project["optional-dependencies"]["desktop"]),
    ):
        requirement = next(
            Requirement(item)
            for item in dependencies
            if Requirement(item).name == name
        )
        assert (
            requirement.specifier
            == Requirement(f"{name}>=99.0.0,<99.1").specifier
        )


def test_release_prepare_restores_metadata_after_uv_lock_failure(
    tmp_path: Path,
) -> None:
    from apprc_dev.packaging.release_notes import UNRELEASED_SECTIONS

    just = shutil.which("just")
    if (
        just is None
        or shutil.which("uv") is None
        or shutil.which("git") is None
    ):
        pytest.skip("release rollback integration requires just, uv, and git")

    workspace = tmp_path / "release-fixture"
    fixture_files = (
        "justfile",
        "pyproject.toml",
        "uv.lock",
        "pylock.toml",
        "README.pypi.md",
        "LICENSE",
        "src/apprc_dev/packaging/terminal_metadata.py",
        "src/apprc_dev/packaging/gui_metadata.py",
        "src/apprc_dev/packaging/example_metadata.py",
        "src/apprc_dev/packaging/release_notes.py",
        "src/apprc_dev/packaging/terminal/pyproject.toml",
        "src/apprc_dev/packaging/terminal/README.md",
        "src/apprc_dev/packaging/terminal/LICENSE",
        "src/apprc_dev/packaging/gui/pyproject.toml",
        "examples/example_apps/pyproject.toml",
    )
    for relative_path in fixture_files:
        source_path = ROOT / relative_path
        target_path = workspace / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)

    pyproject = workspace / "pyproject.toml"
    source = pyproject.read_text(encoding="utf-8")
    version = tomllib.loads(source)["project"]["version"]
    major, minor, _ = map(int, version.split("."))
    release_version = f"{major}.{minor + 1}.0"
    expected_tag = f"v{release_version}"
    source, count = re.subn(
        r"(?m)^dependencies = \[$",
        'dependencies = [\n    "apprc-release-failure-fixture>=1,<1",',
        source,
        count=1,
    )
    assert count == 1
    pyproject.write_text(source, encoding="utf-8")
    release_date = "2026-11-13"
    changelog_lines = [
        "# Changelog",
        "",
        "## Table Of Content",
        "",
        "1. [Changelog](#changelog)",
        "2. [[Unreleased]](#unreleased)",
        f"3. [{release_version} - {release_date}]"
        f"(#{release_version.replace('.', '')}---{release_date})",
        "",
        "# [Unreleased]",
        "",
    ]
    for heading in UNRELEASED_SECTIONS:
        changelog_lines.extend((heading, ""))
    changelog_lines.extend(
        (
            "---",
            "",
            f"# {release_version} - {release_date}",
            "",
            "### ➕ Added",
            "",
            "- Prepared fixture release.",
            "",
        )
    )
    (workspace / "CHANGELOG.md").write_text(
        "\n".join(changelog_lines), encoding="utf-8"
    )

    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    for name in tuple(environment):
        if name.startswith("UV_") or name.startswith("GIT_CONFIG_"):
            environment.pop(name)
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
            "UV_OFFLINE": "1",
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TEMPLATE_DIR": str(tmp_path / "empty-git-template"),
            "GIT_AUTHOR_NAME": "AppRC release fixture",
            "GIT_AUTHOR_EMAIL": "release-fixture@example.invalid",
            "GIT_COMMITTER_NAME": "AppRC release fixture",
            "GIT_COMMITTER_EMAIL": "release-fixture@example.invalid",
        }
    )
    Path(environment["GIT_CONFIG_GLOBAL"]).write_text("", encoding="utf-8")
    Path(environment["GIT_TEMPLATE_DIR"]).mkdir()

    def run_git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return completed.stdout.strip()

    run_git("init", "--quiet")
    run_git("add", "--", *fixture_files, "CHANGELOG.md")
    run_git("commit", "--quiet", "-m", "Fixture baseline")
    initial_head = run_git("rev-parse", "HEAD")

    restore_paths = (
        "pyproject.toml",
        "uv.lock",
        "pylock.toml",
        "src/apprc_dev/packaging/terminal/pyproject.toml",
        "src/apprc_dev/packaging/terminal/README.md",
        "src/apprc_dev/packaging/terminal/LICENSE",
        "src/apprc_dev/packaging/gui/pyproject.toml",
        "examples/example_apps/pyproject.toml",
    )
    before = {path: (workspace / path).read_bytes() for path in restore_paths}

    result = subprocess.run(
        [just, "release-prepare", "minor"],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert {
        path: (workspace / path).read_bytes() for path in restore_paths
    } == before
    assert run_git("rev-parse", "HEAD") == initial_head
    assert run_git("tag", "--list", expected_tag) == ""


def test_distribution_generation_follows_root_version(
    tmp_path: Path, monkeypatch
) -> None:
    from apprc_dev.packaging import terminal_metadata

    source = re.sub(
        r'^version\s*=\s*"[^"]+"',
        'version = "99.0.0"',
        (ROOT / "pyproject.toml").read_text(),
        count=1,
        flags=re.MULTILINE,
    )
    (tmp_path / "pyproject.toml").write_text(source)
    (tmp_path / "README.pypi.md").write_text("Description\n")
    (tmp_path / "LICENSE").write_text("License\n")
    monkeypatch.setattr(terminal_metadata, "ROOT", tmp_path)
    files = generated_files()
    manifest = next(
        content
        for path, content in files.items()
        if path.name == "pyproject.toml"
    )
    parsed = tomllib.loads(manifest)
    assert parsed["project"]["version"] == "99.0.0"
    assert "apprc-core==99.0.0" in parsed["project"]["dependencies"]
