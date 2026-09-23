"""Validate both distributions with ordinary pip, including wrapper removal."""

from __future__ import annotations

import argparse
from email.parser import Parser
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
import zipfile

SMOKE = Path(__file__).with_name("install_smoke.py").resolve()


def run(*args: str, cwd: Path | None = None) -> None:
    """Run a packaging check and stop at its first failure.

    :param args: Command and separate arguments.
    :param cwd: Working directory outside the source checkout.
    """
    subprocess.run(args, cwd=cwd, check=True)


def verify_artifacts(
    directory: Path, *, previous_wheel: Path | None = None
) -> None:
    """Install wheels and source archives in fresh environments.

    :param directory: Directory with exactly two wheels and two source archives.
    :param previous_wheel: Optional pre-refactor wheel for ownership migration.
    """
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 2 or len(sdists) != 2:
        raise ValueError("Expected two wheels and two source archives.")
    core = next(path for path in wheels if path.name.startswith("apprc_core-"))
    terminal = next(path for path in wheels if path.name.startswith("apprc-"))
    with zipfile.ZipFile(core) as archive:
        core_files = set(archive.namelist())
        core_metadata = Parser().parsestr(
            archive.read(
                next(
                    name
                    for name in core_files
                    if name.endswith(".dist-info/METADATA")
                )
            ).decode()
        )
    with zipfile.ZipFile(terminal) as archive:
        terminal_files = set(archive.namelist())
        terminal_metadata = Parser().parsestr(
            archive.read(
                next(
                    name
                    for name in terminal_files
                    if name.endswith(".dist-info/METADATA")
                )
            ).decode()
        )
    version = core_metadata["Version"]
    assert terminal_metadata["Version"] == version
    assert core_metadata["Name"] == "apprc-core"
    assert terminal_metadata["Name"] == "apprc"
    assert f"apprc-core=={version}" in terminal_metadata.get_all(
        "Requires-Dist", []
    )
    assert {path.name for path in sdists} == {
        f"apprc-{version}.tar.gz",
        f"apprc_core-{version}.tar.gz",
    }
    assert not core_files.intersection(terminal_files)
    assert all(".dist-info/" in name for name in terminal_files)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for label, artifacts in (
            ("wheel", [core, terminal]),
            ("sdist", sdists),
        ):
            environment = root / label
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / (
                "Scripts/python.exe"
                if sys.platform == "win32"
                else "bin/python"
            )
            selected_core = next(
                path
                for path in artifacts
                if path.name.startswith("apprc_core-")
            )
            selected_terminal = next(
                path for path in artifacts if path.name.startswith("apprc-")
            )
            if previous_wheel is not None and label == "wheel":
                run(
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    str(previous_wheel),
                    cwd=root,
                )
                run(
                    str(python),
                    "-m",
                    "pip",
                    "uninstall",
                    "-y",
                    "apprc",
                    cwd=root,
                )
            run(
                str(python),
                "-m",
                "pip",
                "install",
                str(selected_core),
                cwd=root,
            )
            if previous_wheel is None or label != "wheel":
                run(str(python), str(SMOKE), "--core-only", cwd=root)
            run(
                str(python),
                "-m",
                "pip",
                "install",
                str(selected_terminal),
                cwd=root,
            )
            run(str(python), str(SMOKE), cwd=root)
            run(str(python), "-m", "pip", "uninstall", "-y", "apprc", cwd=root)
            run(
                str(python),
                "-c",
                "import apprc; from importlib.metadata import version; assert version('apprc-core'); assert apprc.AppRC",
                cwd=root,
            )


def main() -> None:
    """Read artifact paths and run isolated pip checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--previous-wheel", type=Path)
    args = parser.parse_args()
    verify_artifacts(
        args.directory.resolve(), previous_wheel=args.previous_wheel
    )


if __name__ == "__main__":
    main()
