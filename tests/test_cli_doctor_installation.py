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
    EditableCheckout,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RuntimeSelection,
)
from apprc.definition.paths import Layout, Paths
from apprc.definition.resolution import (
    CliRuntimeOptions,
    _BridgeRuntimeOptions,
)
from apprc.distribution.models import AppCapabilities, NativeBinding
from apprc.interfaces.cli.context import (
    _cli_runtime_options_payload,
    resolve_cli_options,
)
from apprc.interfaces.cli.maintenance_command import (
    application_diagnostics_scope,
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

    assert resolved.build(ConfigOnlyExampleEnv).profile == "from-captured-cwd"


def test_root_doctor_omits_verbose_details_without_verbose_option() -> None:
    environment = native_environment()
    declaration = rc.AppRC(app_id="doctor-no-details", paths=Paths())
    arguments = ["app", "doctor", "--json"]
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        args_provider=lambda: arguments,
        host_diagnostics=lambda: {"host": "available"},
    )

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert set(report) == {"status", "checks", "installation"}


@pytest.mark.parametrize("provider_fails", [False, True])
def test_application_doctor_preserves_warnings_and_provider_failures(
    provider_fails: bool,
) -> None:
    declaration = build_config_only_example_app()
    arguments = ["app", "doctor", "--json", "--verbose"]

    def host_diagnostics() -> dict[str, object]:
        if provider_fails:
            raise ValueError("application diagnostic unavailable")
        return {"application": "config-only"}

    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        args_provider=lambda: arguments,
        host_diagnostics=host_diagnostics,
    )

    with application_diagnostics_scope():
        result = CliRunner().invoke(app, arguments, env=native_environment())

    assert result.exit_code == (1 if provider_fails else 0), result.output
    report = json.loads(result.stdout)
    assert report["status"] == ("error" if provider_fails else "warning")
    assert any(
        check["name"] == "user_dotenv" and check["status"] == "warning"
        for check in report["checks"]
    )
    if provider_fails:
        assert any(
            check["name"] == "host_provider"
            and check["status"] == "error"
            and check["message"] == "application diagnostic unavailable"
            for check in report["checks"]
        )
    else:
        assert report["details"]["host"] == {"application": "config-only"}
    assert result.stderr == ""


@pytest.mark.parametrize("verbose", [False, True])
def test_native_doctor_keeps_paths_when_active_interpreter_is_missing(
    tmp_path: Path,
    verbose: bool,
) -> None:
    environment = native_environment()
    app_id = "native-doctor-missing-interpreter"
    declaration = rc.AppRC(
        app_id=app_id, paths=Paths(appdata=True), command_name=app_id
    )
    manager = declaration.installation(environment=environment)
    identity = InstallationIdentity(
        app_id, app_id, "doctor_fixture", "doctor_fixture:APP_RC", (app_id,)
    )
    project = tmp_path / "checkout"
    runtime = EditableCheckout(project, project / ".venv")
    resource_root = tmp_path / "appdata"
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=app_id,
        generation_id=uuid4(),
        support_version="0.34.0",
        placement=InstallationPlacement(
            Layout.native(),
            appdata_dir=resource_root,
            capabilities=frozenset({"appdata"}),
        ),
        status="ready",
        active_runtime=runtime,
    )
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)
    binding = NativeBinding(
        identity=identity,
        command_name=app_id,
        display_name="Native doctor fixture",
        version="1.0",
        source=ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        selection=RuntimeSelection("3.14"),
        capabilities=AppCapabilities(paths=Paths(appdata=True)),
        layout=Layout.native(),
        bootstrap_env_prefix="APPRC",
    )
    arguments = ["app", "doctor", "--json", *(["--verbose"] if verbose else [])]
    app = typer.Typer()
    rc.cli.mount_app_cli(
        app,
        declaration,
        native_binding=binding,
        args_provider=lambda: arguments,
    )
    authority = (manager.directory / "installation.json").read_bytes()

    result = CliRunner().invoke(app, arguments, env=environment)

    assert result.exit_code == 1, result.output
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    assert report["installation"]["status"] == "ready"
    assert any(
        check["name"] == "runtime_health" and check["status"] == "error"
        for check in report["checks"]
    )
    assert any(
        check["name"] == "application_runtime" and check["status"] == "warning"
        for check in report["checks"]
    )
    if verbose:
        assert set(report["details"]) == {
            "paths",
            "configuration",
            "resources",
            "host",
        }
        assert report["details"]["paths"]["paths"]["appdata"] == str(
            resource_root
        )
    else:
        assert "details" not in report
    assert not resource_root.exists()
    assert not project.exists()
    assert (manager.directory / "installation.json").read_bytes() == authority


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
