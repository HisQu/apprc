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
    result = CliRunner().invoke(app, ["app", "paths", "--json"])

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
    paths_result = runner.invoke(app, ["app", "paths", "--json"])
    removed_init = runner.invoke(app, ["app", "cache", "init"])
    cache_paths = runner.invoke(app, ["app", "paths", "cache"])
    disabled = runner.invoke(app, ["app", "paths", "config"])

    assert help_result.exit_code == 0, help_result.output
    assert "AppRC: Commands" in help_result.output
    assert runner.invoke(app, ["app", "cache", "--help"]).exit_code == 2
    for name in ("config", "appdata", "state", "workspace"):
        assert runner.invoke(app, ["app", name, "--help"]).exit_code == 2
    assert paths_result.exit_code == 0, paths_result.output
    assert removed_init.exit_code == 2
    assert cache_paths.exit_code == 0, cache_paths.output
    assert cache_paths.stdout.strip() == str(tmp_path / "cache")
    assert disabled.exit_code == 2
    assert not (tmp_path / "cache").exists()
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
            "app",
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


def test_removed_maintenance_aliases_are_not_exposed(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, cache_only=True)
    runner = CliRunner()

    for command in (
        ["purge", "--all", "--dry-run"],
        ["paths"],
        ["doctor"],
        ["app", "purge"],
        ["app", "appdata", "info"],
        ["app", "cache", "info"],
        ["app", "cache", "init"],
    ):
        assert runner.invoke(app, command).exit_code == 2


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
    result = CliRunner().invoke(
        app, ["app", "cache", "prune", "--dry-run", "--json"]
    )

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

    @app.command("app")
    def existing_app() -> None:
        """Existing command that must remain intact."""
        return None

    declaration = rc.AppRC(app_id="cache-collision", paths=Paths(cache=True))
    existing_commands = tuple(app.registered_commands)
    with pytest.raises(RuntimeError, match="already in use"):
        rc.cli.mount_app_cli(app, declaration)
    assert app.registered_callback is None
    assert tuple(app.registered_commands) == existing_commands
    assert app.registered_groups == []


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

    result = CliRunner().invoke(app, ["app", "doctor", "--json"])

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

    result = CliRunner().invoke(app, ["app", "doctor", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    cache_check = next(
        check for check in payload["checks"] if check["name"] == "cache"
    )
    assert cache_check["status"] == "error"
    assert "links" in cache_check["message"]
    assert target.is_dir()


def test_verbose_doctor_calls_only_explicit_safe_provider(
    tmp_path: Path,
) -> None:
    declaration = rc.AppRC(
        app_id="doctor-provider",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    cache_root = declaration.ensure_path("cache")
    calls: list[Path] = []

    def provider(root: Path) -> dict[str, object]:
        calls.append(root)
        raise ValueError("local provider is unavailable")

    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        handlers=MaintenanceHandlers(
            cache=CacheOperations(info=lambda _root: pytest.fail("info called"))
        ),
        resource_diagnostics={"cache": provider},
    )
    runner = CliRunner()

    ordinary = runner.invoke(app, ["app", "doctor", "--json"])
    assert ordinary.exit_code == 0, ordinary.output
    assert calls == []

    verbose = runner.invoke(app, ["app", "doctor", "--verbose", "--json"])
    assert verbose.exit_code == 1, verbose.output
    payload = json.loads(verbose.stdout)
    assert any(
        check["name"] == "resource_cache_provider"
        and check["status"] == "error"
        for check in payload["checks"]
    )
    assert calls == [cache_root]


def test_verbose_doctor_reports_live_resource_command_names(
    tmp_path: Path,
) -> None:
    declaration = rc.AppRC(
        app_id="doctor-resource-commands",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    app = typer.Typer()

    def register_existing(group: typer.Typer) -> None:
        @group.command("existing")
        def existing() -> None:
            typer.echo("existing")

    groups = rc.cli.mount_app_cli(
        app,
        declaration,
        resource_group_extensions={"cache": register_existing},
    )

    @groups["app.cache"].command("extension-prune")
    def extension_prune() -> None:
        return None

    result = CliRunner().invoke(app, ["app", "doctor", "--verbose", "--json"])

    assert result.exit_code == 0, result.output
    cache = json.loads(result.stdout)["details"]["resources"]["cache"]
    assert cache["operations"] == ["existing", "extension-prune"]


@pytest.mark.parametrize(
    "unsafe_root", ["unowned", "mismatched", "link", "boundary"]
)
def test_verbose_doctor_skips_provider_for_unsafe_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_root: str,
) -> None:
    declaration = rc.AppRC(
        app_id=f"doctor-unsafe-{unsafe_root}",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    cache_root = tmp_path / "cache"
    if unsafe_root == "unowned":
        cache_root.mkdir()
    elif unsafe_root == "mismatched":
        declaration.ensure_path("cache")
        (cache_root / ".apprc-owner.json").write_text(
            json.dumps(
                {"schema_version": 1, "app_id": "other", "category": "cache"}
            ),
            encoding="utf-8",
        )
    elif unsafe_root == "link":
        target = tmp_path / "outside"
        target.mkdir()
        try:
            cache_root.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"Directory symlinks are unavailable: {exc}")
    else:
        declaration.ensure_path("cache")

        def fail_boundary(*_args: object) -> None:
            raise ValueError("overlapping roots")

        monkeypatch.setattr(
            "apprc.interfaces.cli.maintenance_command.validate_category_root_boundaries",
            fail_boundary,
        )

    provider_calls: list[Path] = []
    info_calls: list[Path] = []
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        handlers=MaintenanceHandlers(
            cache=CacheOperations(
                info=lambda root: info_calls.append(root) or {},
            )
        ),
        resource_diagnostics={
            "cache": lambda root: provider_calls.append(root) or {}
        },
    )

    result = CliRunner().invoke(app, ["app", "doctor", "--verbose", "--json"])

    assert provider_calls == []
    assert info_calls == []
    if unsafe_root == "boundary":
        assert result.exit_code == 1, result.output
        assert any(
            check["name"] == "path_boundaries" and check["status"] == "error"
            for check in json.loads(result.stdout)["checks"]
        )


def test_doctor_does_not_catch_provider_programming_errors(
    tmp_path: Path,
) -> None:
    declaration = rc.AppRC(
        app_id="doctor-provider-programming-error",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path),
    )
    declaration.ensure_path("cache")

    def provider(_root: Path) -> dict[str, object]:
        raise RuntimeError("programming error")

    app = typer.Typer()
    rc.cli.mount_app_cli(
        app, declaration, resource_diagnostics={"cache": provider}
    )
    result = CliRunner().invoke(app, ["app", "doctor", "--verbose", "--json"])

    assert isinstance(result.exception, RuntimeError)
