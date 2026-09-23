"""Distribution metadata and generated-version coordination."""

from pathlib import Path
import re
import tomllib

from apprc_dev.packaging.terminal_metadata import ROOT, generated_files


def test_terminal_metadata_is_current() -> None:
    for path, expected in generated_files().items():
        assert path.read_text() == expected, path.name


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
