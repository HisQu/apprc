"""Installation authority decoding, read-only discovery and revision protection."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from apprc import AppRC, Paths, ResolveOptions
from apprc.definition.installation import (
    InstallationError,
    InstallationPlacement,
    InstallationRecord,
)
from apprc.definition.paths import Layout
from apprc.user_files.installation.codec import decode_record, encode_record
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import (
    inspect_installation,
    installation_directory,
)


@pytest.fixture
def record(tmp_path: Path) -> InstallationRecord:
    """Use a valid retained cache-only installation, independent of appdata."""
    return InstallationRecord(
        schema_version=1,
        app_id="fixture-app",
        generation_id=uuid4(),
        support_version="0.31.0",
        status="removed-retained",
        placement=InstallationPlacement(
            layout=Layout.single_root(tmp_path / "resources"),
            cache_dir=tmp_path / "resources" / "cache",
            capabilities=frozenset({"cache"}),
        ),
    )


def test_authority_round_trip_preserves_independent_resources(
    record: InstallationRecord,
) -> None:
    content = encode_record(record)
    restored = decode_record(content, app_id=record.app_id)
    assert restored == record
    assert encode_record(restored) == content
    assert restored.placement.appdata_dir is None
    assert restored.placement.cache_dir == record.placement.cache_dir


@pytest.mark.parametrize(
    "corruption",
    ["unknown", "missing", "bool-version", "relative", "identity", "duplicate"],
)
def test_invalid_authority_is_diagnostic_not_fallback(
    tmp_path: Path, record: InstallationRecord, corruption: str
) -> None:
    value = json.loads(encode_record(record))
    if corruption == "unknown":
        value["future"] = 1
    elif corruption == "missing":
        del value["generation_id"]
    elif corruption == "bool-version":
        value["schema_version"] = True
    elif corruption == "relative":
        value["placement"]["cache_dir"] = "relative/cache"
    elif corruption == "identity":
        value["app_id"] = "foreign-app"
    content = json.dumps(value)
    if corruption == "duplicate":
        content = content[:-1] + ', "schema_version": 1}'
    directory = tmp_path / "installation"
    directory.mkdir()
    (directory / "installation.json").write_text(content, encoding="utf-8")
    inspection = inspect_installation(directory, app_id=record.app_id)
    assert inspection.status == "invalid"
    assert inspection.record is None
    assert inspection.diagnostics
    with pytest.raises(InstallationError):
        inspection.require_usable()


def test_discovery_does_not_create_a_missing_installation(
    tmp_path: Path,
) -> None:
    directory = installation_directory(
        "fixture-app", environment={"HOME": str(tmp_path)}
    )
    assert (
        inspect_installation(directory, app_id="fixture-app").status
        == "missing"
    )
    assert not directory.exists()


def test_expected_revision_rejects_stale_authority(
    tmp_path: Path, record: InstallationRecord
) -> None:
    directory = tmp_path / "installation"
    with installation_lock(directory):
        first = write_record(directory, record, expected_revision=None)
        updated = replace(record, support_version="0.31.1")
        second = write_record(directory, updated, expected_revision=first)
        with pytest.raises(InstallationError, match="changed after planning"):
            write_record(directory, record, expected_revision=first)
    inspection = inspect_installation(directory, app_id=record.app_id)
    assert inspection.record == updated
    assert inspection.revision == second
    assert first != second


def test_pending_authority_cannot_supply_ordinary_paths(
    record: InstallationRecord,
) -> None:
    pending = replace(record, status="provisional")
    assert (
        decode_record(encode_record(pending), app_id=record.app_id) == pending
    )
    with pytest.raises(InstallationError, match="requires current"):
        replace(record, status="ready")


def test_saved_native_paths_remain_sticky_with_changed_xdg(
    tmp_path: Path,
) -> None:
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache-before"),
    }
    app = AppRC(
        app_id="fixture-app",
        paths=Paths(cache=True),
        layout=Layout.single_root(tmp_path / "declared"),
    )
    directory = app.installation(environment=environment).directory
    saved = InstallationRecord(
        schema_version=1,
        app_id="fixture-app",
        generation_id=uuid4(),
        support_version="0.31.0",
        status="removed-retained",
        placement=InstallationPlacement(
            layout=Layout.native(),
            cache_dir=tmp_path / "cache-before" / "fixture-app",
            capabilities=frozenset({"cache"}),
        ),
    )
    with installation_lock(directory):
        revision = write_record(directory, saved, expected_revision=None)
    changed = {**environment, "XDG_CACHE_HOME": str(tmp_path / "cache-after")}
    paths = app.paths(environment=changed)
    assert paths.source == "installation"
    assert paths.cache_dir == saved.placement.cache_dir
    assert paths.appdata_dir is None
    overridden = app.paths(
        ResolveOptions(layout=Layout.single_root(tmp_path / "invocation")),
        environment=changed,
    )
    assert overridden.cache_dir == tmp_path / "invocation" / "cache"
    assert app.installation(environment=changed).inspect().revision == revision


def test_invalid_authority_allows_explicit_paths_but_not_mutation(
    tmp_path: Path,
) -> None:
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    app = AppRC(app_id="fixture-app", paths=Paths(cache=True))
    directory = app.installation(environment=environment).directory
    directory.mkdir(parents=True)
    (directory / "installation.json").write_text("not json", encoding="utf-8")
    with pytest.raises(InstallationError):
        app.paths(environment=environment)
    options = ResolveOptions(layout=Layout.single_root(tmp_path / "chosen"))
    paths = app.paths(options, environment=environment)
    assert paths.installation.diagnostics
    with pytest.raises(InstallationError):
        app.ensure_path("cache", options, environment=environment)
    assert not (tmp_path / "chosen" / "cache").exists()


def test_new_capability_requires_explicit_reconciliation(
    tmp_path: Path, record: InstallationRecord
) -> None:
    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    app = AppRC(app_id=record.app_id, paths=Paths(config=True, cache=True))
    directory = app.installation(environment=environment).directory
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    with pytest.raises(InstallationError, match="reconciliation"):
        app.paths(environment=environment)


def test_captured_resource_writer_rejects_retired_generation(
    tmp_path: Path, record: InstallationRecord
) -> None:
    from apprc.user_files.app_home.ownership import ensure_owned_path

    environment = {
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    app = AppRC(app_id=record.app_id, paths=Paths(cache=True))
    directory = app.installation(environment=environment).directory
    with installation_lock(directory):
        revision = write_record(directory, record, expected_revision=None)
    paths = app.paths(environment=environment)
    with installation_lock(directory):
        write_record(
            directory,
            replace(record, generation_id=uuid4()),
            expected_revision=revision,
        )
    with pytest.raises(InstallationError, match="generation changed"):
        ensure_owned_path(app.schema, paths, "cache")
    assert not paths.require("cache").exists()
    assert not paths.require("cache").parent.exists()
