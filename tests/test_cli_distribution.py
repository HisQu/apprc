"""Exercise the distribution group from a real editable metadata declaration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import typer
from typer.testing import CliRunner

from apprc import AppRC
from apprc.cli import mount_app_cli

_COMMAND = "dist-fixture"
_REVISION = "1" * 40


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Supply installed console metadata for an independently located checkout."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
name = "dist-fixture"
version = "0.1.0"
[project.scripts]
dist-fixture = "authoring_fixture:main"
[tool.apprc.distribution]
app-id = "dist-fixture"
[tool.apprc.distribution.authoring]
backend = "authoring_fixture"
""",
        encoding="utf-8",
    )
    prefix = root / ".venv"
    prefix.mkdir()
    metadata = tmp_path / "dist_fixture-0.1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: dist-fixture\nVersion: 0.1.0\n")
    (metadata / "entry_points.txt").write_text(
        "[console_scripts]\ndist-fixture = authoring_fixture:main\n"
    )
    (metadata / "direct_url.json").write_text(
        json.dumps({"url": root.as_uri(), "dir_info": {"editable": True}})
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.chdir(tmp_path)
    return root


def _app(
    args: list[str], *, installation_management: bool = False
) -> typer.Typer:
    app = typer.Typer()
    mount_app_cli(
        app,
        AppRC(app_id=_COMMAND, command_name=_COMMAND),
        args_provider=lambda: args,
        installation_management=installation_management,
    )
    return app


def test_distribution_help_is_lazy_in_a_fresh_process(checkout: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
sys.prefix = str(Path(sys.argv[1]) / "checkout" / ".venv")
sys.argv = ["dist-fixture", "dist", "build", "--help"]
import typer
from apprc import AppRC
from apprc.cli import mount_app_cli

def forbidden(*args, **kwargs):
    raise AssertionError("help resolved application paths or installation authority")

AppRC.paths = AppRC.installation = forbidden
app = typer.Typer()
mount_app_cli(app, AppRC(app_id="dist-fixture", command_name="dist-fixture"))
try:
    app()
except SystemExit as exc:
    assert exc.code == 0
assert "authoring_fixture" not in sys.modules
assert "apprc.distribution.native" not in sys.modules
assert "textual" not in sys.modules
""",
            str(checkout.parent),
        ],
        cwd=checkout.parent,
        env={**os.environ, "NO_COLOR": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--target-current" in result.stdout


def test_distribution_check_runs_without_resolving_app_state(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.interfaces.cli import _distribution_command as command

    backend = ModuleType("authoring_fixture")
    calls: list[tuple[Path, str, tuple[str, ...]]] = []

    def check(
        root: Path, *, revision: str, targets: tuple[str, ...]
    ) -> tuple[Path, ...]:
        calls.append((root, revision, targets))
        return (root / "dist" / "setup",)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Check resolved host state or ran a build.")

    monkeypatch.setattr(backend, "check", check, raising=False)
    monkeypatch.setattr(backend, "build", forbidden, raising=False)
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(command, "_revision", lambda root: _REVISION)
    monkeypatch.setattr(AppRC, "paths", forbidden)
    monkeypatch.setattr(AppRC, "installation", forbidden)

    args = ["dist", "check"]
    result = CliRunner().invoke(_app(args), args)
    assert result.exit_code == 0, result.output
    assert calls == [(checkout, _REVISION, command._targets(current=False))]


def test_noneditable_interpreter_does_not_enable_distribution(
    checkout: Path,
) -> None:
    # > A wheel or managed runtime can sit next to source without being editable.
    url = checkout.parent / "dist_fixture-0.1.0.dist-info" / "direct_url.json"
    url.write_text(
        json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": False}})
    )
    args = ["--help"]
    result = CliRunner().invoke(_app(args), args)
    assert result.exit_code == 0, result.output
    assert "AppRC: Development" not in result.output


@pytest.mark.parametrize("existing", ["verified", "missing", "corrupt"])
def test_checkout_install_only_delegates_verified_native_setup(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, existing: str
) -> None:
    from apprc.distribution import MissingNativeArtifact
    from apprc.interfaces.cli import _distribution_command as command

    backend = ModuleType("authoring_fixture")
    calls: list[str] = []
    setup = checkout / "dist" / "setup"

    def build(root: Path, *, revision: str, targets: tuple[str, ...]) -> None:
        calls.append("build")

    def check(
        root: Path, *, revision: str, targets: tuple[str, ...]
    ) -> tuple[Path, ...]:
        if existing == "corrupt":
            raise ValueError("Invalid checksum")
        if existing == "missing" and not calls:
            raise MissingNativeArtifact("Missing setup")
        return (setup,)

    def execute(
        args: list[str], *, env: dict[str, str], check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert args == [
            str(setup),
            "--layout",
            "single-root",
            "--app-root",
            str(checkout / "resources"),
            "--yes",
            "--skip-setup",
        ]
        calls.append("install")
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(backend, "build", build, raising=False)
    monkeypatch.setattr(backend, "check", check, raising=False)
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(command, "_revision", lambda root: _REVISION)
    monkeypatch.setattr(
        command, "_targets", lambda *, current: ("test-target",)
    )
    monkeypatch.setattr("apprc.distribution.project._git", lambda *args: b"")
    monkeypatch.setattr(command.subprocess, "run", execute)
    args = [
        "--layout",
        "single-root",
        "--app-root",
        str(checkout / "resources"),
        "app",
        "install",
        "--yes",
        "--skip-setup",
    ]
    result = CliRunner().invoke(_app(args, installation_management=True), args)
    if existing == "corrupt":
        assert result.exit_code != 0
        assert "Invalid checksum" in result.output
        assert calls == []
    else:
        assert result.exit_code == 7, result.output
        assert calls == (
            ["build", "install"] if existing == "missing" else ["install"]
        )
