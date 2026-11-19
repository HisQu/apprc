"""Native selector declarations and placement capture preserve CLI contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import apprc as rc
from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    ProjectSnapshot,
    RuntimeSelection,
)
from apprc.distribution.models import AppCapabilities, NativeBinding
from apprc.interfaces.cli.options import native_runtime_parser
from apprc.services.installation import InstallationManager


def _native_install_case(
    tmp_path: Path,
) -> tuple[NativeBinding, InstallationManager]:
    """Provide real domain objects while tests replace the install operation."""
    binding = NativeBinding(
        identity=InstallationIdentity(
            "example", "example", "example", None, ("example",)
        ),
        command_name="example",
        display_name="Example",
        version="1.0",
        source=ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        selection=RuntimeSelection("3.14"),
        capabilities=AppCapabilities(),
        layout=rc.Layout.native(),
        bootstrap_env_prefix="EXAMPLE",
    )
    manager = InstallationManager(
        rc.AppRC(app_id="example", paths=rc.Paths()).schema,
        directory=tmp_path / "installation",
        environment={},
    )
    return binding, manager


def test_native_selectors_share_declarations_without_consuming_install_arguments() -> (
    None
):
    """Root capture preserves repeated selectors while installer validation is strict."""
    runtime = native_runtime_parser()
    install = argparse.ArgumentParser(add_help=False, parents=[runtime])
    install.add_argument("--yes", "-y", action="store_true")
    args = [
        "--env-file",
        "first.env",
        "app",
        "install",
        "--env-file",
        "last.env",
        "-o",
        "--yes",
    ]
    selected, remaining = runtime.parse_known_args(args)
    assert selected.env_file == [Path("first.env"), Path("last.env")]
    assert selected.env_file_overrides_os_environ
    assert remaining == ["app", "install", "--yes"]
    installed, unknown = install.parse_known_args(args[4:])
    assert installed.env_file == [Path("last.env")]
    assert installed.yes
    assert unknown == []


def test_placement_capture_masks_disabled_paths_and_subordinate_logs(
    tmp_path: Path,
) -> None:
    """Resolved roots never enable capabilities absent from the declaration."""
    app = rc.AppRC(
        app_id="placement-capture",
        paths=rc.Paths(config=True, appdata=True, cache=True, state=True),
        layout=rc.Layout.single_root(tmp_path),
    )
    paths = app.paths(environment={})
    placement = InstallationPlacement.from_paths(paths, rc.Paths(cache=True))
    assert placement.layout == paths.layout
    assert placement.cache_dir == paths.cache_dir
    assert placement.capabilities == frozenset({"cache"})
    assert placement.config_dir is None
    assert placement.appdata_dir is None
    assert placement.state_dir is None
    assert placement.logs_dir is None


def test_native_install_reports_rollback_after_live_progress(
    tmp_path, monkeypatch, capsys
):
    from apprc.distribution.runtime import _manager
    from apprc.distribution.runtime._install_progress import report

    def fail(*args, **kwargs):
        assert "1. Preparing Runtime" in capsys.readouterr().out
        report("result", "Installed runtime", "VALIDATED")
        error = OSError("Command is in use")
        error.add_note("AppRC installation changes were rolled back.")
        raise error

    monkeypatch.setattr(_manager, "_install_managed", fail)
    binding, manager = _native_install_case(tmp_path)
    assert _manager._install(binding, manager, tmp_path / "manager", ()) == 1
    captured = capsys.readouterr()
    assert "VALIDATED" in captured.out
    assert "installation complete" not in captured.out
    assert "Installation failed: Command is in use" in captured.err
    assert "installation changes were rolled back" in captured.err


@pytest.mark.parametrize(
    "color,no_color,expected",
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_managed_install_delegate_honors_click_color(
    tmp_path, monkeypatch, color, no_color, expected
):
    import typer
    from typer.testing import CliRunner

    from apprc.distribution.runtime import _manager
    from apprc.distribution.runtime._install_progress import report
    from apprc.interfaces.cli.installation_command import (
        mount_installation_group,
    )

    binding, manager = _native_install_case(tmp_path)

    def install(*args, **kwargs):
        report("result", "Environment", "CREATED", tmp_path / "environment")
        return None, manager.inspect()

    monkeypatch.setattr(_manager, "_install_managed", install)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    app = typer.Typer(context_settings={"color": color})
    mount_installation_group(
        app,
        installer_entrypoint=lambda args: _manager._install(
            binding, manager, tmp_path / "manager", tuple(args)
        ),
    )
    result = CliRunner().invoke(app, ["install"], color=color)
    assert result.exit_code == 0, result.output
    assert f"{binding.display_name} · Installing or updating" in result.output
    for code in (32, 35, 36):
        assert (f"\x1b[{code}m" in result.output) is expected
    assert "managed installation complete" in result.output
