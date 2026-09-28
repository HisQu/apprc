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


def test_gui_metadata_sync_handles_current_and_simulated_versions(
    tmp_path: Path,
) -> None:
    from apprc_dev.packaging.gui_metadata import (
        render_gui_pyproject,
        sync_gui_metadata,
    )

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
    assert simulated_path.read_text(encoding="utf-8") == render_gui_pyproject(
        gui_source,
        "0.27.1",
    )


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
