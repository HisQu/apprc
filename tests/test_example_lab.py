"""Tests for disposable example sessions and CLI smoke coverage."""

from __future__ import annotations

# == Standard Library ===========================================
from pathlib import Path

# == 3rd Party ==================================================
import pytest

# == Internal ===================================================
from _example_apps_utils import example_app, lab
from _example_apps_utils.run_all import run_all

ROOT = Path(__file__).parents[1]
EXAMPLE_SOURCE = ROOT / "examples" / "example_apps" / "src"


def test_lab_starts_empty_sanitizes_env_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful child shell cannot inherit or retain AppRC lab state."""
    monkeypatch.setenv("APPRC_EXAMPLE_USER_PROFILE", "inherited")
    monkeypatch.setenv("APPRC_EXAMPLE_WORKSPACE_WORKSPACE", "inherited")
    external = tmp_path / "outside-lab"
    external.mkdir()
    observed_root: Path | None = None

    def open_shell(command: tuple[str, ...], *, env: dict[str, str]) -> int:
        nonlocal observed_root
        assert command
        observed_root = Path(env["APPRC_EXAMPLE_LAB_ROOT"])
        assert not (observed_root / "apprc").exists()
        assert "APPRC_EXAMPLE_USER_PROFILE" not in env
        assert "APPRC_EXAMPLE_WORKSPACE_WORKSPACE" not in env
        root_env_key = example_app("user-dotenv").root_env_key
        layout_root = Path(env[root_env_key])
        assert layout_root == observed_root / "apprc"
        config_dir = layout_root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "apprc.user.env").write_text(
            "PROFILE=lab\n", encoding="utf-8"
        )
        (external / "keep.txt").write_text("keep", encoding="utf-8")
        return 7

    monkeypatch.setattr(lab, "_open_shell", open_shell)

    assert lab.run_lab("user-dotenv") == 7
    assert observed_root is not None
    assert not observed_root.exists()
    assert (external / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_lab_cleans_up_when_shell_launch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary AppRC state is removed when the shell runner raises."""
    observed_root: Path | None = None

    def fail_shell(command: tuple[str, ...], *, env: dict[str, str]) -> int:
        nonlocal observed_root
        assert command
        observed_root = Path(env["APPRC_EXAMPLE_LAB_ROOT"])
        (observed_root / "apprc").mkdir()
        raise RuntimeError("shell failed")

    monkeypatch.setattr(lab, "_open_shell", fail_shell)

    with pytest.raises(RuntimeError, match="shell failed"):
        lab.run_lab("workspace")
    assert observed_root is not None
    assert not observed_root.exists()


def test_example_apps_do_not_depend_on_runner_support() -> None:
    """Each user-facing CLI remains copyable without the test harness."""
    cli_paths = sorted(EXAMPLE_SOURCE.glob("*/cli.py"))

    assert len(cli_paths) == 8
    assert {path.parent.name for path in cli_paths} == {
        "cache_only",
        "cli_runtime",
        "explicit_env_precedence",
        "library_client",
        "process_env",
        "user_dotenv",
        "user_dotenv_with_workspace",
        "workspace",
    }
    for path in cli_paths:
        assert "_example_apps_utils" not in path.read_text(encoding="utf-8")


def test_run_all_uses_real_installed_clis() -> None:
    """The aggregate smoke run covers every integration scenario."""
    results = run_all()

    assert [result["example"] for result in results] == [
        "cache-only",
        "process-env",
        "user-dotenv",
        "workspace",
        "user-dotenv-with-workspace",
        "explicit-env-precedence",
        "cli-runtime",
        "library-client",
    ]
    precedence = results[5]
    assert precedence["shell_wins"] != precedence["explicit_file_wins"]
    assert all(result["cleaned"] is True for result in results)
