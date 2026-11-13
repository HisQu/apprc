"""Committed snapshot materialization and full-tree archive boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from apprc.definition.installation import InstallationError, ProjectSnapshot
from apprc.distribution.runtime.acquisition import materialize_project_snapshot


def _write_snapshot(
    path: Path,
    entries: dict[str, bytes],
    *,
    project_path: str,
) -> ProjectSnapshot:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    lock_name = (
        "uv.lock"
        if project_path == "."
        else f"{project_path.split('/', 1)[0]}/uv.lock"
    )
    lock = entries[lock_name]
    return ProjectSnapshot(
        hashlib.sha256(path.read_bytes()).hexdigest(),
        hashlib.sha256(lock).hexdigest(),
        "a" * 40,
        project_path,
    )


def test_materialization_preserves_one_root_and_uses_shared_workspace_lock(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "project.zip"
    entries = {
        "workspace/uv.lock": b"version = 1\n",
        "workspace/apps/fixture/pyproject.toml": (
            b"[project]\nname = 'fixture'\nversion = '1.0.0'\n"
        ),
        "workspace/apps/fixture/main.py": b"VALUE = 7\n",
        "workspace/libs/shared.py": b"VALUE = 8\n",
    }
    source = _write_snapshot(
        archive,
        entries,
        project_path="workspace/apps/fixture",
    )
    destination = tmp_path / "materialized"

    materialize_project_snapshot(archive, destination, source)

    assert (destination / "workspace/uv.lock").read_bytes() == entries[
        "workspace/uv.lock"
    ]
    assert (
        destination / "workspace/apps/fixture/main.py"
    ).read_bytes() == entries["workspace/apps/fixture/main.py"]
    assert (destination / "workspace/libs/shared.py").read_bytes() == entries[
        "workspace/libs/shared.py"
    ]


def test_unsafe_archive_member_is_rejected_before_materialization(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.zip"
    entries = {
        "workspace/uv.lock": b"version = 1\n",
        "workspace/app/pyproject.toml": b"[project]\nname='fixture'\n",
        "../outside.txt": b"must not escape",
    }
    source = _write_snapshot(archive, entries, project_path="workspace/app")
    destination = tmp_path / "materialized"

    with pytest.raises(
        InstallationError, match="Unsafe source archive member path"
    ):
        materialize_project_snapshot(archive, destination, source)

    assert not destination.exists()
    assert not (tmp_path / "outside.txt").exists()
