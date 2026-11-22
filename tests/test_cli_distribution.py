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
from rich.text import Text
from typer.testing import CliRunner

from apprc import AppRC
from apprc.cli import AppRCRootGroup, mount_app_cli

_COMMAND = "dist-fixture"
_REVISION = "1" * 40


def _plain_message(output: str) -> str:
    return " ".join(Text.from_ansi(output).plain.replace("│", "").split())


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


def _enable_preview(checkout: Path) -> None:
    metadata = checkout / "pyproject.toml"
    source = metadata.read_text().replace(
        "[project.scripts]",
        "[project.scripts]\ndist-preview = 'preview_fixture:main'",
    )
    metadata.write_text(
        source + "\n[tool.apprc.distribution.preview]\n"
        "app-id = 'dist-preview'\ncommand-name = 'dist-preview'\n"
        "apprc-reference = 'preview_fixture:APP_RC'\n"
        "bootstrap-env-prefix = 'DIST_PREVIEW'\n"
    )


def _app(
    args: list[str],
    *,
    installation_management: bool = False,
    color: bool | None = None,
) -> typer.Typer:
    app = typer.Typer(cls=AppRCRootGroup, context_settings={"color": color})
    mount_app_cli(
        app,
        AppRC(app_id=_COMMAND, command_name=_COMMAND),
        args_provider=lambda: args,
        installation_management=installation_management,
    )
    return app


@pytest.mark.parametrize(
    "help_args",
    [
        ("--help",),
        ("dist", "build", "--help"),
        ("app", "install", "--help"),
        ("app", "update", "--help"),
        ("update", "--help"),
    ],
)
def test_distribution_help_is_lazy_in_a_fresh_process(
    checkout: Path, help_args: tuple[str, ...]
) -> None:
    if help_args[:2] == ("app", "install"):
        _enable_preview(checkout)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
from pathlib import Path

class NoRuntimeDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for unavailable in (
            "authoring_fixture",
            "apprc.distribution.runtime.update",
            "packaging",
            "prompt_toolkit",
            "textual",
        ):
            if fullname == unavailable or fullname.startswith(f"{unavailable}."):
                raise ModuleNotFoundError(f"{fullname} is unavailable during help")

sys.meta_path.insert(0, NoRuntimeDependencies())
sys.path.insert(0, sys.argv[1])
sys.prefix = str(Path(sys.argv[1]) / "checkout" / ".venv")
sys.argv = ["dist-fixture", *sys.argv[2:]]
import typer
from apprc import AppRC
from apprc.cli import AppRCRootGroup, mount_app_cli

def forbidden(*args, **kwargs):
    raise AssertionError("help resolved application paths or installation authority")

AppRC.paths = AppRC.installation = forbidden
app = typer.Typer(cls=AppRCRootGroup)
mount_app_cli(
    app, AppRC(app_id="dist-fixture", command_name="dist-fixture"),
    installation_management=True,
)

@app.command()
def serve():
    pass

try:
    app()
except SystemExit as exc:
    assert exc.code == 0
assert "authoring_fixture" not in sys.modules
assert "apprc.distribution.native" not in sys.modules
assert "apprc.distribution.runtime.update" not in sys.modules
assert "textual" not in sys.modules
assert "prompt_toolkit" not in sys.modules
""",
            str(checkout.parent),
            *help_args,
        ],
        cwd=checkout.parent,
        env={**os.environ, "NO_COLOR": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = Text.from_ansi(result.stdout).plain
    if help_args == ("--help",):
        host_help, apprc_help = output.split("AppRC: Commands", 1)
        assert any(
            line.split()[:2] == ["│", "serve"]
            for line in host_help.splitlines()
        )
        assert all(
            line.split()[:2] != ["│", "dist"] for line in host_help.splitlines()
        )
        assert any(
            line.split()[:2] == ["│", "dist"]
            for line in apprc_help.splitlines()
        )
        assert any(
            line.split()[:2] == ["│", "update"]
            for line in apprc_help.splitlines()
        )
    elif help_args[:2] == ("dist", "build"):
        assert "--target-current" in output
        assert "--olis-repo" in output
    elif help_args[:2] == ("app", "install"):
        assert "Source Build (SB)" in output
        assert "--preview" in output
        assert "--smoke" in output
    else:
        assert "--yes" in output
        assert any(
            "--release" in line and "TAG" in line
            for line in output.splitlines()
        )
        assert any(
            "--version" in line and "-v" in line.split() and "VERSION" in line
            for line in output.splitlines()
        )
        assert "Update the registered release or editable checkout." in output


@pytest.mark.parametrize("flag", [None, "-o", "--olis-repo"])
def test_distribution_build_olis_override(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None
) -> None:
    from apprc.distribution import project
    from apprc.interfaces.cli import _distribution_command as command

    backend = ModuleType("authoring_fixture")
    calls: list[dict[str, str]] = []

    def build(
        root: Path, *, revision: str, targets: tuple[str, ...], **options: str
    ) -> None:
        calls.append(options)

    monkeypatch.setattr(backend, "build", build, raising=False)
    monkeypatch.setattr(
        backend,
        "check",
        lambda root, **kwargs: (root / "setup",),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(command, "_revision", lambda root: _REVISION)
    monkeypatch.setattr(project, "_git", lambda *args: "")
    monkeypatch.delenv("RELEASE_REPO_OLIS", raising=False)

    args = ["dist", "build"]
    if flag is not None:
        args.extend((flag, "owner/selected"))
        monkeypatch.setenv("RELEASE_REPO_OLIS", "owner/default")
    result = CliRunner().invoke(_app(args), args)
    assert result.exit_code == 0, result.output
    assert calls == (
        [{}] if flag is None else [{"olis_repo": "owner/selected"}]
    )
    assert ("OLIS generation skipped" in result.output) == (flag is None)


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
    assert all(
        line.split()[:2] != ["│", "dist"] for line in result.output.splitlines()
    )


@pytest.mark.parametrize(
    "existing", ["verified", "missing", "stale", "corrupt"]
)
def test_checkout_install_only_delegates_verified_native_setup(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, existing: str
) -> None:
    from apprc.distribution import MissingNativeArtifact, StaleNativeArtifact
    from apprc.interfaces.cli import _distribution_authoring as command

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
        if existing == "stale" and not calls:
            raise StaleNativeArtifact("Stale setup")
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
    assert "1. Checking Local Setup" in result.output
    assert ("2. Building Local Setup" in result.output) == (
        existing in {"missing", "stale"}
    )
    if existing == "corrupt":
        assert result.exit_code != 0
        assert "Invalid checksum" in result.output
        assert calls == []
    else:
        assert result.exit_code == 7, result.output
        assert "\x1b[" not in result.stdout
        assert calls == (
            ["build", "install"]
            if existing in {"missing", "stale"}
            else ["install"]
        )


def test_missing_authoring_backend_reports_checkout_setup(
    checkout: Path,
) -> None:
    args = ["dist", "check"]
    result = CliRunner().invoke(_app(args), args)
    assert result.exit_code != 0
    assert "Cannot load distribution backend" in result.output
    assert "uv sync --locked --all-groups" in _plain_message(result.output)


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
    from apprc.interfaces.cli import _distribution_authoring as command

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
    assert "app install --yes" in _plain_message(result.output)
    assert builds == []


def test_policy_setup_gets_explicit_regular_argument(tmp_path: Path) -> None:
    from zipfile import ZipFile

    from apprc.distribution._release_assets import regular_setup_arguments

    setup = tmp_path / "setup"
    with ZipFile(setup, "w") as archive:
        archive.writestr("preview-binding.json", "{}")
    assert regular_setup_arguments(setup) == ()
    with ZipFile(setup, "a") as archive:
        archive.writestr("preview-default", b"beta-rc\n")
    assert regular_setup_arguments(setup) == ("--regular",)


def test_dist_test_runs_guided_preflight(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apprc.interfaces.cli import _distribution_test as guide

    monkeypatch.setattr(guide, "_revision", lambda root: _REVISION)
    args = ["dist", "test", "--yes"]
    result = CliRunner().invoke(_app(args, installation_management=True), args)
    assert result.exit_code == 1, result.output
    assert (
        "The checkout console command and uv must be available" in result.output
    )
    (report,) = (checkout / ".cache" / "apprc" / "dist-test").glob("*.json")
    assert json.loads(report.read_text())["commit"] == _REVISION


@pytest.mark.parametrize(
    ("flags", "mode"),
    [(["--yes", "--preview"], "--preview"), (["-ys"], "--smoke")],
)
def test_checkout_install_selects_preview_before_other_native_options(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], mode: str
) -> None:
    from apprc.interfaces.cli import _distribution_authoring as authoring

    _enable_preview(checkout)
    backend = ModuleType("authoring_fixture")
    setup = checkout / "dist" / "setup"
    monkeypatch.setattr(
        backend, "check", lambda *args, **kwargs: (setup,), raising=False
    )
    monkeypatch.setattr(
        backend,
        "build",
        lambda *args, **kwargs: pytest.fail("rebuild"),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(authoring, "_revision", lambda root: _REVISION)
    monkeypatch.delenv("NO_COLOR")

    def execute(args: list[str], *, env: dict[str, str], check: bool):
        assert args == [str(setup), mode, "--log-level", "INFO", "--yes"]
        assert env["_APPRC_TERMINAL_COLOR"] == "1"
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(authoring.subprocess, "run", execute)
    args = ["--log-level", "INFO", "app", "install", *flags]
    app = _app(args, installation_management=True, color=True)
    result = CliRunner().invoke(app, args, color=True)
    assert result.exit_code == 0, result.output
    assert "\x1b[35m" in result.output
    assert "\x1b[36m" in result.output
    assert "\x1b[32m" in result.output


def test_checkout_install_help_omits_preview_without_opt_in(
    checkout: Path,
) -> None:
    args = ["app", "install", "--help"]
    result = CliRunner().invoke(_app(args, installation_management=True), args)
    assert result.exit_code == 0, result.output
    assert "--preview" not in result.output
    assert "--smoke" not in result.output


def test_checkout_does_not_register_regular_editable_for_preview(
    checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apprc.interfaces.cli import installation_command

    _enable_preview(checkout)
    monkeypatch.setattr(
        installation_command,
        "_register_editable",
        lambda *args, **kwargs: pytest.fail("registered regular editable"),
    )
    args = ["app", "install", "-ep"]
    result = CliRunner().invoke(_app(args, installation_management=True), args)
    assert result.exit_code == 2
    assert (
        "--editable cannot be combined with --preview or --smoke"
        in _plain_message(result.output)
    )
