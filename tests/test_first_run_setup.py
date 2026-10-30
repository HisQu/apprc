from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.core import TyperCommand

import apprc as rc
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import ResolveOptions
from apprc.interfaces.cli.context import CliRuntimeContext, CliRuntimeOptions
from apprc.interfaces.cli.runtime import CliRuntime, DefaultConfigCliState
from apprc.user_files.app_home.application import AppFiles


def _runtime(
    tmp_path: Path,
) -> CliRuntime[CliRuntimeOptions, DefaultConfigCliState]:
    app_rc = rc.AppRC(
        app_id="runtime_first_use",
        paths=Paths(config=True),
        layout=Layout.single_root(tmp_path / "home"),
        workspaces=rc.Workspaces(registry=False),
    )
    return CliRuntime(
        app_rc,
        args_provider=lambda: ["run"],
        workspace_required=True,
    )


def _context(command: str = "run") -> typer.Context:
    context = typer.Context(TyperCommand(name="runtime-first-use"))
    context.invoked_subcommand = command
    return context


def test_missing_required_workspace_has_no_implicit_first_use_writes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    with pytest.raises(typer.BadParameter, match="workspace"):
        runtime.prepare(
            _context(),
            CliRuntimeOptions(layout=Layout.single_root(tmp_path / "home")),
        )

    config_dir = runtime.apprc.paths(environment={}).require("config")
    assert not config_dir.exists()
    assert not (tmp_path / "home" / "workspace").exists()


def test_initialized_direct_workspace_resolves_without_registry_or_config_writes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    workspace_root = tmp_path / "prepared"
    workspace_root.mkdir()
    marker = AppFiles(
        runtime.apprc.schema,
        runtime.apprc.paths(environment={}),
    ).workspace_dotenv_path(workspace_root)
    marker.write_text("", encoding="utf-8")
    command_context = _context()
    session = runtime.prepare(
        command_context,
        CliRuntimeOptions(
            workspace=str(workspace_root),
            layout=Layout.single_root(tmp_path / "home"),
        ),
    )
    assert isinstance(session.apprc_context, CliRuntimeContext)
    assert not session.apprc_context.runtime_setup_skipped
    assert session.apprc_context.resolved is not None
    assert session.apprc_context.resolved.workspace is not None
    assert session.apprc_context.resolved.workspace.root == workspace_root
    assert not runtime.apprc.paths(environment={}).require("config").exists()


def test_skipped_runtime_keeps_environment_layout_snapshot_for_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_rc = rc.AppRC(
        app_id="captured_bootstrap",
        paths=Paths(config=True),
        workspaces=rc.Workspaces(registry=False),
    )
    layout_key = app_rc.schema.layout_env_key
    root_key = app_rc.schema.root_env_key
    captured_root = tmp_path / "captured"
    monkeypatch.setenv(layout_key, "single-root")
    monkeypatch.setenv(root_key, str(captured_root))
    runtime = CliRuntime(app_rc, args_provider=lambda: ["paths"])
    command_context = _context("paths")
    session = runtime.prepare(
        command_context,
        CliRuntimeOptions(load_dotenv_layers=False),
    )
    assert isinstance(session.apprc_context, CliRuntimeContext)
    context = session.apprc_context
    monkeypatch.setenv(root_key, str(tmp_path / "later"))
    refreshed = app_rc.manage(
        ResolveOptions(
            layout=context.runtime_options.layout,
            load_dotenv_layers=context.runtime_options.load_dotenv_layers,
        ),
        environment=context.environment,
    )

    assert context.runtime_setup_skipped
    assert context.paths.require("config") == captured_root / "config"
    assert refreshed.paths.require("config") == captured_root / "config"
