"""Root doctor reports installation failures without initializing resources."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.installation import (
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
)
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import (
    CliRuntimeOptions,
    _BridgeRuntimeOptions,
)
from apprc.interfaces.cli.context import (
    _cli_runtime_options_payload,
    resolve_cli_options,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.codec import _decode, encode_record
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from tests.support_config import (
    ConfigOnlyExampleEnv,
    build_config_only_example_app,
    native_environment,
)


def _removed_record(app_id: str, command_name: str) -> InstallationRecord:
    identity = InstallationIdentity(
        app_id=app_id,
        distribution=app_id,
        import_package="doctor_fixture",
        apprc_reference=None,
        commands=(command_name,),
    )
    return InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=command_name,
        generation_id=uuid4(),
        support_version="0.34.0",
        status="removed-retained",
        placement=InstallationPlacement(Layout.native()),
    )


def test_bridge_preserves_relative_env_file_across_working_directory_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    destination = tmp_path / "destination"
    origin.mkdir()
    destination.mkdir()
    (origin / "captured.env").write_text(
        "CONFIG_ONLY_APP_PROFILE=from-captured-cwd\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(origin)
    options = CliRuntimeOptions.from_typer(
        env_files=(Path("captured.env"),),
        env_file_overrides_os_environ=True,
    )
    payload = _cli_runtime_options_payload(options)
    captured = _decode(payload, _BridgeRuntimeOptions, "runtime_options")
    assert isinstance(captured, _BridgeRuntimeOptions)

    monkeypatch.chdir(destination)
    app = build_config_only_example_app()
    environment = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
    }
    resolved = resolve_cli_options(
        app,
        captured.runtime,
        environment=environment,
    )

    assert (
        resolved.build(ConfigOnlyExampleEnv).profile
        == "from-captured-cwd"
    )



@pytest.mark.parametrize(
    "override", [True, False], ids=["native-override", "fallback"]
)
def test_root_doctor_rejects_malformed_authority_without_initializing(
    override: bool,
) -> None:
    environment = native_environment()
    declaration = rc.AppRC(app_id="doctor-malformed-authority", paths=Paths())
    directory = declaration.installation(environment=environment).directory
    create_private_directory_if_missing(directory)
    authority = directory / "installation.json"
    content = b"{not valid installation JSON\n"
    authority.write_bytes(content)
    host_calls: list[str] = []
    arguments = [
        *(["--layout", "native"] if override else []),
        "app",
        "doctor",
        "--verbose",
        "--json",
    ]
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        args_provider=lambda: arguments,
        host_diagnostics=lambda: (
            host_calls.append("called") or {"host": "available"}
        ),
    )

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code != 0, result.output
    report = json.loads(result.stdout)
    assert report["details"]["host"] == {"host": "available"}
    assert host_calls == ["called"]
    assert report["status"] == "invalid"
    if override:
        assert report["installation"]["status"] == "invalid"
        assert any(
            check["name"] == "installation"
            and check["status"] == "error"
            and "json" in check["message"].lower()
            for check in report["checks"]
        )
    else:
        assert report["status"] == "invalid"
        installation = report["installation"]
        assert installation["status"] == "invalid"
        assert any(
            diagnostic["code"]
            and "json" in diagnostic["message"].lower()
            and diagnostic["recovery"]
            for diagnostic in installation["diagnostics"]
        )
    assert authority.read_bytes() == content
    assert set(directory.iterdir()) == {authority}
    assert set(directory.parent.iterdir()) == {directory}


@pytest.mark.parametrize("schema_version", [1, 2, 99])
def test_root_doctor_diagnoses_unsupported_authority_without_mutation(
    schema_version: int,
) -> None:
    environment = native_environment()
    app_id = f"doctor-schema-{schema_version}"
    command_name = f"{app_id}-command"
    declaration = rc.AppRC(
        app_id=app_id, command_name=command_name, paths=Paths()
    )
    directory = declaration.installation(environment=environment).directory
    create_private_directory_if_missing(directory)
    authority = directory / "installation.json"
    record = _removed_record(app_id, command_name)
    value = json.loads(encode_record(record))
    value["schema_version"] = schema_version
    content = json.dumps(value).encode("utf-8")
    authority.write_bytes(content)
    arguments = ["app", "doctor", "--json"]
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration, args_provider=lambda: arguments)

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code != 0, result.output
    report = json.loads(result.stdout)
    installation = report["installation"]
    assert installation["status"] == "invalid"
    assert authority.read_bytes() == content
    assert set(directory.iterdir()) == {authority}


def test_root_doctor_reports_missing_saved_capability_without_initializing() -> (
    None
):
    environment = native_environment()
    app_id = "doctor-capability-reconciliation"
    command_name = "doctor-capability-reconciliation-command"
    declaration = rc.AppRC(
        app_id=app_id, command_name=command_name, paths=Paths(cache=True)
    )
    directory = declaration.installation(environment=environment).directory
    cache = declaration.paths(
        rc.ResolveOptions(layout=Layout.native()), environment=environment
    ).require("cache")
    record = _removed_record(app_id, command_name)
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    authority = directory / "installation.json"
    content = authority.read_bytes()
    existing_entries = set(directory.rglob("*"))
    arguments = ["app", "doctor", "--json"]
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration, args_provider=lambda: arguments)

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code != 0, result.output
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    installation = report["installation"]
    assert installation["status"] == "removed-retained"
    assert any(
        diagnostic["code"]
        and "capabilit" in diagnostic["message"].lower()
        and "reconcil" in diagnostic["message"].lower()
        and diagnostic["recovery"]
        for diagnostic in installation["diagnostics"]
    )
    assert authority.read_bytes() == content
    assert set(directory.rglob("*")) == existing_entries
    assert set(directory.parent.iterdir()) == {directory}
    assert not cache.exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Legacy native parent appdata migration is Linux-specific.",
)
def test_root_doctor_reports_legacy_migration_without_creating_new_store() -> (
    None
):
    environment = native_environment()
    declaration = rc.AppRC(
        app_id="doctor-legacy-appdata", paths=Paths(appdata=True)
    )
    directory = declaration.installation(environment=environment).directory
    legacy_root = directory.parent
    create_private_directory_if_missing(legacy_root)
    marker = legacy_root / ".apprc-owner.json"
    marker_content = (
        json.dumps(
            {
                "schema_version": 1,
                "app_id": declaration.schema.app_id,
                "category": "appdata",
            }
        )
        + "\n"
    ).encode("utf-8")
    marker.write_bytes(marker_content)
    payload = legacy_root / "database.sqlite"
    payload_content = b"retained legacy application data"
    payload.write_bytes(payload_content)
    arguments = ["app", "doctor", "--json"]
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration, args_provider=lambda: arguments)

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code != 0, result.output
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    installation = report["installation"]
    assert installation["status"] == "missing"
    assert any(
        diagnostic["code"]
        and "legacy" in diagnostic["message"].lower()
        and "migrat" in diagnostic["message"].lower()
        and diagnostic["recovery"]
        for diagnostic in installation["diagnostics"]
    )
    assert marker.read_bytes() == marker_content
    assert payload.read_bytes() == payload_content
    assert not directory.exists()
    assert not (legacy_root / "appdata").exists()
    assert set(legacy_root.iterdir()) == {marker, payload}
