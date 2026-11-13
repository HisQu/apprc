"""Opt-in native feasibility construction; never imported by production code."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import venv
from collections.abc import Sequence
from pathlib import Path

from apprc.distribution.native import NativeFrontendBuilder, UV_VERSION

# > Pytest sandboxes HOME per test; native authoring must keep the host Rustup,
# > Cargo and cargo-xwin caches captured during collection.
_AUTHORING_ENVIRONMENT = dict(os.environ)

_LOG = logging.getLogger(__name__)


def require_opt_in() -> None:
    """Reject accidental direct construction without the explicit native opt-in."""
    if os.environ.get("APPRC_TEST_PYAPP") != "1":
        raise RuntimeError("Native feasibility requires APPRC_TEST_PYAPP=1.")


def run(
    argv: Sequence[str],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Capture bounded fixture commands and retain useful failure diagnostics."""
    _LOG.info("Running %s", argv)
    result = subprocess.run(
        argv,
        env=environment,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=1800,
    )
    if check and result.returncode:
        raise AssertionError(f"{argv!r}\n{result.stdout}\n{result.stderr}")
    return result


def pinned_uv(root: Path) -> Path:
    """Create or reuse only this fixture's environment containing exact uv 0.13.6.

    :param root: Fixture-owned storage, separate from the PyApp runtime.
    :return: Absolute uv executable, with both package and binary version checked.
    """
    require_opt_in()
    root = root.absolute()
    if root.is_symlink():
        raise FileExistsError(f"Fixture uv root must not be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)
    environment_root = root / f"uv-{UV_VERSION}"
    marker = root / "pinned-uv.json"
    expected = {"version": UV_VERSION, "environment": environment_root.name}
    if environment_root.is_symlink() or marker.is_symlink():
        raise FileExistsError("Fixture uv state must not contain symlinks.")
    if environment_root.exists():
        if (
            not environment_root.is_dir()
            or not marker.is_file()
            or json.loads(marker.read_text()) != expected
        ):
            raise FileExistsError(
                f"Unexpected fixture uv environment: {environment_root}"
            )
    else:
        if marker.exists():
            raise FileExistsError(f"Unexpected fixture uv marker: {marker}")
        venv.EnvBuilder(with_pip=True).create(environment_root)
        python = environment_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                f"uv=={UV_VERSION}",
            ]
        )
        marker.write_text(json.dumps(expected), encoding="utf-8")
    python = environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    executable = environment_root / (
        "Scripts/uv.exe" if os.name == "nt" else "bin/uv"
    )
    version = run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('uv'))",
        ]
    )
    assert version.stdout.strip() == UV_VERSION
    assert run([str(executable), "--version"]).stdout.split()[:2] == [
        "uv",
        UV_VERSION,
    ]
    return executable.absolute()


def authoring_environment() -> dict[str, str]:
    """Return captured Rust/Cargo settings without pytest's sandbox HOME."""
    return dict(_AUTHORING_ENVIRONMENT)


def authoring_git_environment(
    repository: Path, canonical_url: str
) -> dict[str, str]:
    """Add a fixture-only Git URL rewrite while preserving inherited config.

    :param repository: Local committed checkout supplying immutable Git objects.
    :param canonical_url: Public dependency URL recorded in project metadata.
    :return: Authoring environment with an additional local rewrite entry.
    """
    environment = authoring_environment()
    count = int(environment.get("GIT_CONFIG_COUNT", "0"))
    environment.update(
        {
            f"GIT_CONFIG_KEY_{count}": f"url.file://{repository.resolve()}.insteadOf",
            f"GIT_CONFIG_VALUE_{count}": canonical_url,
            "GIT_CONFIG_COUNT": str(count + 1),
        }
    )
    return environment


def native_builder(
    workspace: Path,
    *,
    pip_extra_args: str = "",
    bootstrap_name: str = "fixture-app-bootstrap",
) -> NativeFrontendBuilder:
    """Create the fixture's production builder with the host authoring environment.

    :param workspace: New operation-owned build directory.
    :param pip_extra_args: Static local recovery-download settings, if needed.
    :param bootstrap_name: Bootstrap namespace shared by related native frontends.
    :return: Builder using the captured authoring environment.
    """
    return NativeFrontendBuilder(
        workspace,
        bootstrap_name=bootstrap_name,
        pip_extra_args=pip_extra_args,
        environment=authoring_environment(),
    )


def isolated_environment(
    root: Path,
    *,
    bootstrap_name: str = "fixture-app-bootstrap",
) -> dict[str, str]:
    """Isolate native state and remove ambient Python, uv, pip and PyApp selectors.

    :param root: Private fixture-owned runtime state root.
    :param bootstrap_name: Exact PyApp bootstrap namespace used by the frontend.
    :return: Environment with isolated locations and no inherited selectors.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            (
                "UV_",
                "PYTHON",
                "PYAPP",
                "PIP_",
                "CONDA",
                "VIRTUAL_ENV",
                "APPRC_FIXTURE_",
            )
        )
    }
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    locations = {
        "HOME": "home",
        "USERPROFILE": "home",
        "LOCALAPPDATA": "local",
        "APPDATA": "roaming",
        "XDG_DATA_HOME": "data",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_STATE_HOME": "state",
        "UV_TOOL_DIR": "tools",
        "UV_TOOL_BIN_DIR": "commands",
        "UV_CACHE_DIR": "uv-cache",
        "UV_PYTHON_INSTALL_DIR": "python",
        "UV_PYTHON_BIN_DIR": "python-bin",
        "UV_CONFIG_DIR": "uv-config",
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
        f"PYAPP_INSTALL_DIR_{bootstrap_name.upper()}": "bootstrap",
        "PATH": "empty-path",
    }
    for key, relative in locations.items():
        path = root / relative
        if relative != "bootstrap":
            path.mkdir(exist_ok=True, mode=0o700)
        environment[key] = str(path)
    environment.update(
        UV_NO_CONFIG="1", PYTHONNOUSERSITE="1", APPRC_FIXTURE_ROOT=str(root)
    )
    return environment


def disk_bytes(root: Path) -> int:
    """Count regular on-disk fixture bytes without following directory links."""
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
