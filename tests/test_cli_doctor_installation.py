"""Root doctor reports installation failures without initializing resources."""

from __future__ import annotations

import json
import sys
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.definition.installation import (
    InstallationPlacement,
    InstallationRecord,
)
from apprc.definition.paths import Layout, Paths
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from tests.support_config import native_environment


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
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration)
    arguments = ["--layout", "native"] if override else []

    result = CliRunner().invoke(
        app, [*arguments, "doctor", "--json"], env=environment
    )

    assert result.exit_code != 0, result.output
    report = json.loads(result.stdout)
    if override:
        assert report["status"] == "error"
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


def test_root_doctor_reports_missing_saved_capability_without_initializing() -> (
    None
):
    environment = native_environment()
    declaration = rc.AppRC(
        app_id="doctor-capability-reconciliation", paths=Paths(cache=True)
    )
    directory = declaration.installation(environment=environment).directory
    cache = declaration.paths(
        rc.ResolveOptions(layout=Layout.native()), environment=environment
    ).require("cache")
    record = InstallationRecord(
        schema_version=1,
        app_id=declaration.schema.app_id,
        generation_id=uuid4(),
        support_version="0.31.0",
        status="removed-retained",
        placement=InstallationPlacement(Layout.native()),
    )
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    authority = directory / "installation.json"
    content = authority.read_bytes()
    existing_entries = set(directory.rglob("*"))
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration)

    result = CliRunner().invoke(app, ["doctor", "--json"], env=environment)

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
    app = typer.Typer()
    rc.cli.mount_app_cli(app, declaration)

    result = CliRunner().invoke(app, ["doctor", "--json"], env=environment)

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
