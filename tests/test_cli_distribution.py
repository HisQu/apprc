"""Exercise the distribution group from a real editable metadata declaration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
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
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
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
import importlib.abc
import sys
from pathlib import Path

class NoAuthoringDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "packaging" or fullname.startswith("packaging."):
            raise ModuleNotFoundError("authoring-only dependency is unavailable")

sys.meta_path.insert(0, NoAuthoringDependencies())
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


def test_missing_authoring_backend_reports_checkout_setup(
    checkout: Path,
) -> None:
    args = ["dist", "check"]
    result = CliRunner().invoke(_app(args), args)
    assert result.exit_code != 0
    assert "Cannot load distribution backend" in result.output
    assert "uv sync --locked --all-groups" in result.output


def test_distribution_name_collision_preserves_the_host_cli(
    checkout: Path,
) -> None:
    app = typer.Typer()

    @app.command("dist")
    def host_dist() -> None:
        typer.echo("host distribution command")

    original_commands = tuple(app.registered_commands)
    with pytest.raises(RuntimeError, match="dist"):
        mount_app_cli(
            app,
            AppRC(app_id=_COMMAND, command_name=_COMMAND),
        )
    assert tuple(app.registered_commands) == original_commands
    assert app.registered_groups == []
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "host distribution command"


def test_explicit_installer_delegate_takes_precedence(checkout: Path) -> None:
    calls: list[tuple[str, ...]] = []
    args = ["app", "install", "--yes", "--skip-setup"]
    app = typer.Typer()

    def install(arguments: Sequence[str]) -> int:
        calls.append(tuple(arguments))
        return 9

    mount_app_cli(
        app,
        AppRC(app_id=_COMMAND, command_name=_COMMAND),
        installation_management=True,
        installer_entrypoint=install,
        args_provider=lambda: args,
    )
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 9, result.output
    assert calls == [("--yes", "--skip-setup")]


def test_unattended_missing_setup_does_not_build_without_yes(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.distribution import MissingNativeArtifact
    from apprc.interfaces.cli import _distribution_command as command

    backend = ModuleType("authoring_fixture")
    builds: list[Path] = []

    def build(root: Path, *, revision: str, targets: tuple[str, ...]) -> None:
        builds.append(root)

    def check(
        root: Path, *, revision: str, targets: tuple[str, ...]
    ) -> tuple[Path, ...]:
        raise MissingNativeArtifact("Missing setup")

    monkeypatch.setattr(backend, "build", build, raising=False)
    monkeypatch.setattr(backend, "check", check, raising=False)
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(command, "_revision", lambda root: _REVISION)
    args = ["app", "install"]
    result = CliRunner().invoke(_app(args, installation_management=True), args)
    assert result.exit_code != 0
    assert "app install --yes" in result.output
    assert builds == []
