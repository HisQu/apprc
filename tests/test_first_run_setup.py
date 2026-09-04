from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.core import TyperCommand

import apprc.interfaces.cli.runtime as runtime_module
from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.storage import Storage
from apprc.interfaces.cli.context import CliRuntimeOptions
from apprc.interfaces.cli.runtime import CliRuntime, DefaultConfigCliState


class _TTYProxy:
    """Delegate stream operations while reporting an interactive terminal."""

    def __init__(self, stream: Any) -> None:
        """Store the captured stream used by pytest."""
        self._stream = stream

    def isatty(self) -> bool:
        """Report that first-run prompting is safe."""
        return True

    def __getattr__(self, name: str) -> Any:
        """Delegate stream methods needed by Click and Rich."""
        return getattr(self._stream, name)


def _runtime(
    tmp_path: Path,
) -> CliRuntime[CliRuntimeOptions, DefaultConfigCliState]:
    """Return a storage runtime with the first-run prompt enabled."""
    kit = AppConfigKit(
        app_id="first_run_demo",
        display_name="First Run Demo",
        config_package="config_with_storage.config",
        storage=Storage(selector_env_key="FIRST_RUN_DEMO_STORAGE"),
        apprc_dir=tmp_path / "apprc",
    )
    return CliRuntime(
        kit,
        args_provider=lambda: ["run"],
    )


def _context() -> typer.Context:
    """Return a root context that represents a runtime command."""
    context = typer.Context(TyperCommand(name="first-run-demo"))
    context.invoked_subcommand = "run"
    return context


def _enable_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the runtime see pytest's captured streams as interactive."""
    monkeypatch.setattr(runtime_module.sys, "stdin", _TTYProxy(sys.stdin))
    monkeypatch.setattr(runtime_module.sys, "stdout", _TTYProxy(sys.stdout))


def test_first_runtime_use_accepts_suggested_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An accepted TTY prompt prepares storage, persists it, and retries."""
    monkeypatch.delenv("FIRST_RUN_DEMO_STORAGE", raising=False)
    _enable_tty(monkeypatch)
    monkeypatch.setattr(typer, "confirm", lambda _: True)
    runtime = _runtime(tmp_path)

    session = runtime.prepare(_context(), CliRuntimeOptions())

    suggested = tmp_path / "data-home" / "first_run_demo" / "storage"
    assert session.state is not None
    assert session.apprc_context.env_bootstrap is not None
    assert session.apprc_context.env_bootstrap.storage_root == suggested
    assert (suggested / "apprc.storage.env").is_file()
    assert runtime.kit.spec.user_dotenv_path().is_file()
    assert runtime.kit.spec.preferred_apprc_toml_path().is_file()


def test_first_runtime_use_decline_leaves_no_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A declined TTY prompt reports the custom-path command without writes."""
    monkeypatch.delenv("FIRST_RUN_DEMO_STORAGE", raising=False)
    _enable_tty(monkeypatch)
    monkeypatch.setattr(typer, "confirm", lambda _: False)
    runtime = _runtime(tmp_path)

    with pytest.raises(typer.Exit):
        runtime.prepare(_context(), CliRuntimeOptions())

    captured = capsys.readouterr()
    assert "No files were changed." in captured.err
    assert "setup --storage-root PATH" in captured.err
    assert not (tmp_path / "data-home" / "first_run_demo").exists()
    assert not runtime.kit.spec.user_dotenv_path().exists()
