"""Native selector declarations and placement capture preserve CLI contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

import apprc as rc
from apprc.definition.installation import InstallationPlacement
from apprc.interfaces.cli.options import native_runtime_parser


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
    from types import SimpleNamespace

    from apprc.distribution.runtime import _manager
    from apprc.distribution.runtime._install_progress import report

    def fail(*args):
        assert "1. Preparing Runtime" in capsys.readouterr().out
        report("result", "Installed runtime", "VALIDATED")
        error = OSError("Command is in use")
        error.add_note("AppRC installation changes were rolled back.")
        raise error

    monkeypatch.setattr(_manager, "_install_managed", fail)
    binding = SimpleNamespace(display_name="Example")
    assert _manager._install(binding, None, tmp_path / "manager", ()) == 1
    captured = capsys.readouterr()
    assert "VALIDATED" in captured.out
    assert "installation complete" not in captured.out
    assert "Installation failed: Command is in use" in captured.err
    assert "installation changes were rolled back" in captured.err
