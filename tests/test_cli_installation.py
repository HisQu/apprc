from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.user_files.installation.discovery import installation_directory


def _app(
    apprc: rc.AppRC | None = None,
    *,
    args: Sequence[str],
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
) -> typer.Typer:
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        apprc or rc.AppRC(app_id="installation-cli", paths=rc.Paths()),
        installation_management=True,
        installer_entrypoint=installer_entrypoint,
        args_provider=lambda: args,
    )
    return app


def test_explicit_installer_forwards_arguments_and_status() -> None:
    calls: list[tuple[str, ...]] = []

    def installer(arguments: Sequence[str]) -> int:
        calls.append(tuple(arguments))
        return 23

    args = ["app", "install", "--help"]
    app = _app(args=args, installer_entrypoint=installer)
    runner = CliRunner()

    help_result = runner.invoke(app, args)
    assert help_result.exit_code == 0, help_result.output
    assert calls == []

    args[:] = ["app", "install", "--feature", "value", "--", "package.whl"]
    result = runner.invoke(app, args)
    assert result.exit_code == 23
    assert calls == [("--feature", "value", "package.whl")]


def test_root_doctor_reports_invalid_authority_without_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    directory = installation_directory(
        "installation-cli",
        environment={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        },
    )
    directory.mkdir(parents=True)
    (directory / "installation.json").write_text("{not json", encoding="utf-8")
    args = ["app", "doctor", "--json"]
    app = _app(args=args)
    runner = CliRunner()

    root_doctor = runner.invoke(app, args)

    assert root_doctor.exit_code == 1, root_doctor.output
    report = json.loads(root_doctor.stdout)
    assert report["status"] == "invalid"
    assert report["installation"]["status"] == "invalid"
    args[:] = ["app", "paths", "--json"]
    strict_paths = runner.invoke(app, args)
    assert strict_paths.exit_code != 0
    assert tuple(directory.iterdir()) == (directory / "installation.json",)


def test_root_doctor_reports_missing_installation_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    args = ["app", "doctor", "--json"]
    result = CliRunner().invoke(_app(args=args), args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["installation"]["status"] == "missing"
    assert not (tmp_path / "xdg-data").exists()


def test_initial_migration_without_bound_identity_is_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app_id = "installation-cli-migrate"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    source = tmp_path / "data" / app_id
    source.mkdir(parents=True)
    marker = source / ".apprc-owner.json"
    marker.write_text(
        '{"schema_version":1,"app_id":"installation-cli-migrate",'
        '"category":"appdata"}\n',
        encoding="utf-8",
    )
    args = ["app", "migrate", "--dry-run", "--json"]
    app = _app(rc.AppRC(app_id=app_id, paths=rc.Paths(appdata=True)), args=args)

    preview = CliRunner().invoke(app, args)

    assert preview.exit_code != 0
    assert marker.is_file()
    assert not (source / "appdata").exists()
    assert not installation_directory(
        app_id,
        environment={
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
        },
    ).exists()
