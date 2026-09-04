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
from apprc.user_files.storage_roots.registry import (
    load_storage_registry_or_empty,
)


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
    runtime = _runtime(tmp_path)
    suggested = tmp_path / "apprc" / "storage"
    monkeypatch.setattr(
        runtime_module,
        "prompt_storage_setup_root",
        lambda *, suggested: suggested,
    )

    session = runtime.prepare(_context(), CliRuntimeOptions())

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
    monkeypatch.setattr(
        runtime_module,
        "prompt_storage_setup_root",
        lambda *, suggested: None,
    )
    runtime = _runtime(tmp_path)

    with pytest.raises(typer.Exit):
        runtime.prepare(_context(), CliRuntimeOptions())

    captured = capsys.readouterr()
    assert "No files were changed." in captured.err
    assert "setup --storage-root PATH" in captured.err
    assert not (tmp_path / "data-home" / "first_run_demo").exists()
    assert not runtime.kit.spec.user_dotenv_path().exists()


def test_first_runtime_use_accepts_custom_storage_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The first-run prompt may choose a completed filesystem path.

    :param monkeypatch: Process and prompt mutation fixture.
    :param tmp_path: Isolated AppRC and storage parent.
    """
    monkeypatch.delenv("FIRST_RUN_DEMO_STORAGE", raising=False)
    _enable_tty(monkeypatch)
    runtime = _runtime(tmp_path)
    custom_root = tmp_path / "custom-storage"
    monkeypatch.setattr(
        runtime_module,
        "prompt_storage_setup_root",
        lambda *, suggested: custom_root,
    )

    session = runtime.prepare(_context(), CliRuntimeOptions())

    assert session.apprc_context.env_bootstrap is not None
    assert session.apprc_context.env_bootstrap.storage_root == custom_root
    assert (custom_root / "apprc.storage.env").is_file()


def test_interactive_direct_path_can_be_registered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An initialized direct path becomes named only after consent.

    :param monkeypatch: Process and prompt mutation fixture.
    :param tmp_path: Isolated AppRC and storage parent.
    """
    monkeypatch.delenv("FIRST_RUN_DEMO_STORAGE", raising=False)
    _enable_tty(monkeypatch)
    runtime = _runtime(tmp_path)
    root = tmp_path / "direct"
    root.mkdir()
    (root / "apprc.storage.env").write_text("", encoding="utf-8")
    monkeypatch.setattr(typer, "confirm", lambda _: True)
    monkeypatch.setattr(
        runtime_module,
        "prompt_storage_registration_name",
        lambda *, suggested: "work",
    )

    session = runtime.prepare(
        _context(),
        CliRuntimeOptions(storage=str(root)),
    )

    assert session.apprc_context.env_bootstrap is not None
    assert session.apprc_context.env_bootstrap.storage_name == "work"
    registry = load_storage_registry_or_empty(
        runtime.kit.spec.preferred_apprc_toml_path()
    )
    assert registry.selected("work").root == root


def test_noninteractive_direct_path_is_used_without_registry_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A script may use an initialized path without persistent registration.

    :param monkeypatch: Process environment fixture.
    :param tmp_path: Isolated AppRC and storage parent.
    """
    monkeypatch.delenv("FIRST_RUN_DEMO_STORAGE", raising=False)
    runtime = _runtime(tmp_path)
    root = tmp_path / "direct"
    root.mkdir()
    (root / "apprc.storage.env").write_text("", encoding="utf-8")

    session = runtime.prepare(
        _context(),
        CliRuntimeOptions(storage=str(root)),
    )

    assert session.apprc_context.env_bootstrap is not None
    assert session.apprc_context.env_bootstrap.storage_name is None
    assert not runtime.kit.spec.preferred_apprc_toml_path().exists()
