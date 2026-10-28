from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.maintenance import (
    CacheOperations,
    MaintenanceHandlers,
    RemovalOperation,
    RemovalPlan,
    RemovalResult,
)
from apprc.definition.paths import Layout, Paths


def _app(
    root: Path,
    *,
    cache_only: bool = False,
    handlers: MaintenanceHandlers = MaintenanceHandlers(),
) -> tuple[typer.Typer, rc.AppRC]:
    paths = (
        Paths(cache=True)
        if cache_only
        else Paths(config=True, appdata=True, cache=True, state=True)
    )
    declaration = rc.AppRC(
        app_id="maintenance-demo",
        paths=paths,
        layout=Layout.single_root(root),
        user_dotenv=rc.UserDotenv() if paths.config else None,
    )
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration, handlers=handlers)
    return app, declaration


def test_paths_json_reports_declared_locations_without_creating_them(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path)
    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "layout": "single-root",
        "root": str(tmp_path),
        "source": "declaration",
        "paths": {
            "config": str(tmp_path / "config"),
            "appdata": str(tmp_path / "appdata"),
            "cache": str(tmp_path / "cache"),
            "state": str(tmp_path / "state"),
            "logs": str(tmp_path / "state" / "logs"),
        },
        "exists": {
            "config": False,
            "appdata": False,
            "cache": False,
            "state": False,
            "logs": False,
        },
    }
    assert tuple(tmp_path.iterdir()) == ()


def test_cache_only_maintenance_context_skips_business_state(
    tmp_path: Path,
) -> None:
    declaration = rc.AppRC(
        app_id="cache-cli",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        state_factory=lambda _context: pytest.fail(
            "maintenance must skip business state"
        ),
    )
    runner = CliRunner()

    help_result = runner.invoke(app, ["--help"])
    paths_result = runner.invoke(app, ["paths", "--json"])
    init_result = runner.invoke(app, ["cache", "init"])
    cache_paths = runner.invoke(app, ["paths", "cache"])
    disabled = runner.invoke(app, ["paths", "config"])

    assert help_result.exit_code == 0, help_result.output
    assert "Maintenance" in help_result.output
    assert "cache" in help_result.output
    for name in ("config", "appdata", "state", "workspace"):
        assert runner.invoke(app, [name, "--help"]).exit_code == 2
    assert paths_result.exit_code == 0, paths_result.output
    assert init_result.exit_code == 0, init_result.output
    assert cache_paths.exit_code == 0, cache_paths.output
    assert cache_paths.stdout.strip() == str(tmp_path / "cache")
    assert disabled.exit_code == 2
    assert (tmp_path / "cache" / ".apprc-owner.json").is_file()
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "appdata").exists()
    assert not (tmp_path / "state").exists()


def test_paths_cli_layout_override_wins_over_environment_pair(
    tmp_path: Path,
) -> None:
    declaration = rc.AppRC(app_id="layout-cli", paths=Paths(cache=True))
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration)
    result = CliRunner().invoke(
        app,
        [
            "--layout",
            "single-root",
            "--app-root",
            str(tmp_path),
            "paths",
            "cache",
        ],
        env={
            "LAYOUT_CLI_LAYOUT": "native",
            "LAYOUT_CLI_ROOT": str(tmp_path / "lower"),
        },
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(tmp_path / "cache")
    assert not (tmp_path / "cache").exists()


def test_purge_preview_emits_exact_cache_plan_without_applying(
    tmp_path: Path,
) -> None:
    def plan(root: Path) -> RemovalPlan:
        return RemovalPlan("cache", root, (root / "payload.bin",), "captured")

    handlers = MaintenanceHandlers(
        cache=CacheOperations(
            purge=RemovalOperation(
                plan, lambda _plan: pytest.fail("preview applied")
            ),
        )
    )
    app, declaration = _app(tmp_path, cache_only=True, handlers=handlers)
    declaration.ensure_path("cache")
    payload_file = tmp_path / "cache" / "payload.bin"
    payload_file.write_bytes(b"retain until explicit purge")

    result = CliRunner().invoke(
        app, ["purge", "--scope", "cache", "--dry-run", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plans"][0]["category"] == "cache"
    assert payload["plans"][0]["root"] == str(tmp_path / "cache")
    assert str(payload_file) in payload["plans"][0]["targets"]
    assert payload["results"] == []
    assert payload_file.read_bytes() == b"retain until explicit purge"
    assert set(payload["plans"][0]) == {
        "category",
        "root",
        "targets",
        "revision",
        "warnings",
    }


def test_purge_json_preserves_completed_results_when_later_apply_fails(
    tmp_path: Path,
) -> None:
    def cache_plan(root: Path) -> RemovalPlan:
        return RemovalPlan("cache", root, (), "cache-revision")

    def fail_apply(_plan: RemovalPlan) -> RemovalResult:
        raise OSError("provider failed")

    app, _ = _app(
        tmp_path,
        handlers=MaintenanceHandlers(
            cache=CacheOperations(
                purge=RemovalOperation(cache_plan, fail_apply),
            )
        ),
    )

    result = CliRunner().invoke(
        app,
        ["purge", "--scope", "config", "--scope", "cache", "--yes", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert len(payload["results"]) == 2
    assert payload["results"][0]["category"] == "config"
    assert payload["results"][1]["category"] == "cache"
    assert payload["results"][1]["warnings"] == [
        "Apply failed; provider may have partially changed this root."
    ]
    assert payload["failure"]["category"] == "cache"
    assert payload["failure"]["root"] == str(tmp_path / "cache")
    assert "provider failed" not in result.stdout
    assert "provider failed" not in result.output


def test_resource_operation_commands_are_provider_gated(tmp_path: Path) -> None:
    root = tmp_path / "cache"

    def plan(path: Path) -> RemovalPlan:
        return RemovalPlan("cache", path, (), "revision")

    def apply(_plan: RemovalPlan) -> RemovalResult:
        return RemovalResult(removed=())

    app = typer.Typer()
    declaration = rc.AppRC(
        app_id="cache-provider",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    rc.cli.mount_app_cli(
        app,
        declaration,
        handlers=MaintenanceHandlers(
            cache=CacheOperations(prune=RemovalOperation(plan, apply))
        ),
    )
    result = CliRunner().invoke(app, ["cache", "prune", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "plans": [
            {
                "category": "cache",
                "root": str(root),
                "targets": [],
                "revision": "revision",
                "warnings": [],
            }
        ],
        "results": [],
    }


def test_mount_rejects_group_collision_before_adding_callback() -> None:
    app = typer.Typer()

    @app.command()
    def cache() -> None:
        """Existing command that must remain intact."""
        return None

    declaration = rc.AppRC(app_id="cache-collision", paths=Paths(cache=True))
    with pytest.raises(RuntimeError, match="already in use"):
        rc.cli.mount_app_cli(app, declaration)
    assert app.registered_callback is None


def test_direct_workspace_group_initializes_and_inspects_without_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    declaration = rc.AppRC(
        app_id="direct-workspace",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path / "app"),
        workspaces=rc.Workspaces(registry=False),
    )
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration)
    runner = CliRunner()

    help_result = runner.invoke(app, ["workspace", "--help"])
    init_result = runner.invoke(app, ["workspace", "init", "./direct"])
    info_result = runner.invoke(app, ["workspace", "info", "direct"])

    assert help_result.exit_code == 0, help_result.output
    assert "init" in help_result.output
    assert "info" in help_result.output
    assert all(
        name not in help_result.output for name in ("add", "list", "select")
    )
    assert init_result.exit_code == 0, init_result.output
    assert init_result.stdout.strip() == str(tmp_path / "direct")
    assert (tmp_path / "direct" / "apprc.workspace.env").is_file()
    assert info_result.exit_code == 0, info_result.output
    assert json.loads(info_result.stdout) == {
        "root": str(tmp_path / "direct"),
        "exists": True,
    }
    assert not (tmp_path / "app" / "config").exists()
    assert not (tmp_path / "app" / "cache").exists()


def test_root_doctor_reports_mismatched_path_ownership_without_repair(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, cache_only=True)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    marker = cache_root / ".apprc-owner.json"
    original = b'{"schema_version":1,"app_id":"another-app","category":"cache"}'
    marker.write_bytes(original)

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    cache_check = next(
        check for check in payload["checks"] if check["name"] == "cache"
    )
    assert cache_check["status"] == "error"
    assert "ownership marker" in cache_check["message"]
    assert marker.read_bytes() == original


def test_root_doctor_reports_linked_category_root(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, cache_only=True)
    target = tmp_path / "outside"
    target.mkdir()
    cache_root = tmp_path / "cache"
    try:
        cache_root.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    cache_check = next(
        check for check in payload["checks"] if check["name"] == "cache"
    )
    assert cache_check["status"] == "error"
    assert "links" in cache_check["message"]
    assert target.is_dir()
