"""Authenticated SDK archive composition and binding behavior."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from apprc.definition.installation import ProjectSnapshot
from apprc.distribution.frontends import (
    _sdk_archive,
    _validate_prepared_project,
)
from apprc.distribution.metadata import read_distribution_spec
from apprc.distribution.models import decode_native_binding
from apprc.distribution.project import PreparedProject


def test_sdk_archive_contains_exact_binding_snapshot_and_sdk_metadata(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "project.zip"
    project_entries = {
        "pyproject.toml": (
            b"[project]\nname = 'archive-fixture'\nversion = '1.2.3'\n"
        ),
        "uv.lock": b"version = 1\n",
        "fixture_app.py": b"VALUE = 'project source'\n",
    }
    with ZipFile(project_path, "w") as project_archive:
        for name, content in project_entries.items():
            project_archive.writestr(name, content)
    project_bytes = project_path.read_bytes()
    lock_digest = hashlib.sha256(project_entries["uv.lock"]).hexdigest()
    source = ProjectSnapshot(
        hashlib.sha256(project_bytes).hexdigest(),
        lock_digest,
        "a" * 40,
    )
    project = PreparedProject(project_path, source)

    declaration = tmp_path / "author"
    declaration.mkdir()
    (declaration / "pyproject.toml").write_text(
        "[project]\nname = 'archive-fixture'\nversion = '1.2.3'\n"
        "[project.scripts]\narchive-fixture = 'fixture_app:main'\n",
        encoding="utf-8",
    )
    spec = read_distribution_spec(declaration)
    sdk_bytes = _sdk_archive(spec, project, ("gui",))

    with ZipFile(BytesIO(sdk_bytes)) as sdk:
        names = set(sdk.namelist())
        metadata_names = {
            name for name in names if name.endswith(".dist-info/METADATA")
        }
        assert "binding.json" in names
        assert "project.zip" in names
        assert "bootstrap-requirements.txt" in names
        assert "apprc/distribution/runtime/_manager.py" in names
        assert len(metadata_names) == 2
        assert sdk.read("project.zip") == project_bytes
        binding_bytes = sdk.read("binding.json")
        binding = decode_native_binding(binding_bytes)
        assert binding.identity == spec.metadata.identity
        assert binding.source == source
        assert binding.selection.extras == ("gui",)
        unknown = json.loads(binding_bytes)
        unknown["unrecognized"] = True
        with pytest.raises(ValueError):
            decode_native_binding(json.dumps(unknown).encode())
        requirements = (
            sdk.read("bootstrap-requirements.txt").decode().splitlines()
        )
        assert sum(line.startswith("uv==") for line in requirements) == 1
        assert not any(name.endswith("fixture_app.py") for name in names)


def test_native_authoring_rejects_snapshot_bound_to_another_workspace_member(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    selected = repository / "apps" / "fixture"
    selected.mkdir(parents=True)
    lock = b"version = 1\n"
    (repository / "uv.lock").write_bytes(lock)
    declaration = (
        "[project]\n"
        "name = 'path-fixture'\n"
        "version = '1.0.0'\n"
        "[project.scripts]\n"
        "path-fixture = 'fixture_app:main'\n"
        "[tool.apprc.distribution]\n"
        "app-id = 'path-fixture'\n"
        "import-package = 'fixture_app'\n"
    )
    (selected / "pyproject.toml").write_text(declaration, encoding="utf-8")
    (selected / "fixture_app.py").write_text("VALUE = 1\n", encoding="utf-8")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AppRC test",
        "GIT_AUTHOR_EMAIL": "tests@example.invalid",
        "GIT_COMMITTER_NAME": "AppRC test",
        "GIT_COMMITTER_EMAIL": "tests@example.invalid",
    }
    subprocess.run(
        ["git", "init", "-q", str(repository)],
        env=environment,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "add", "."],
        env=environment,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-q", "-m", "fixture"],
        env=environment,
        check=True,
    )
    spec = read_distribution_spec(selected)

    project_archive = tmp_path / "wrong-member.zip"
    with ZipFile(project_archive, "w") as archive:
        archive.writestr("uv.lock", lock)
        archive.writestr("apps/other/pyproject.toml", declaration)
    archive_bytes = project_archive.read_bytes()
    prepared = PreparedProject(
        project_archive,
        ProjectSnapshot(
            hashlib.sha256(archive_bytes).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "b" * 40,
            "apps/other",
        ),
    )

    with pytest.raises(ValueError, match="different committed project path"):
        _validate_prepared_project(spec, prepared, tmp_path)
