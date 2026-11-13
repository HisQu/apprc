"""Committed workspace snapshots preserve source and reject unsafe preparation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from apprc.distribution.project import build_project_snapshot
from apprc.distribution.metadata import read_distribution_spec


def _committed_workspace(root: Path, *, local_source: str = "../../libs/fixture-lib") -> None:
    app = root / "apps" / "fixture"
    library = root / "libs" / "fixture-lib"
    (app / "src" / "fixture_app" / "dist").mkdir(parents=True)
    (app / "src" / "fixture_app" / "build").mkdir(parents=True)
    (library / "src" / "fixture_lib").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[tool.uv.workspace]\nmembers = ['apps/*', 'libs/*']\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (app / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-app'\nversion = '1.0.0'\n"
        "requires-python = '>=3.12'\ndependencies = ['fixture-lib']\n"
        "[project.scripts]\nfixture-app = 'fixture_app:main'\n"
        "[tool.apprc.distribution]\napp-id = 'fixture-app'\n"
        "import-package = 'fixture_app'\ncommand-name = 'fixture-app'\n"
        "[tool.uv.sources]\nfixture-lib = { path = '" + local_source + "' }\n",
        encoding="utf-8",
    )
    (library / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-lib'\nversion = '1.0.0'\n",
        encoding="utf-8",
    )
    files = {
        app / "src/fixture_app/main.py": "VALUE = 1\n",
        app / "src/fixture_app/dist/resource.txt": "committed-dist-data\n",
        app / "src/fixture_app/build/resource.txt": "committed-build-data\n",
        library / "src/fixture_lib/__init__.py": "VALUE = 2\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AppRC snapshot fixture",
        "GIT_AUTHOR_EMAIL": "snapshot@example.invalid",
        "GIT_COMMITTER_NAME": "AppRC snapshot fixture",
        "GIT_COMMITTER_EMAIL": "snapshot@example.invalid",
    }
    subprocess.run(["git", "init", "-q", str(root)], env=environment, check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], env=environment, check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "workspace fixture"],
        env=environment,
        check=True,
    )


def test_builder_exports_virtual_root_and_nested_member_with_shared_lock(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    spec = read_distribution_spec(repository / "apps" / "fixture")
    prepared = build_project_snapshot(
        spec,
        revision="HEAD",
        destination=tmp_path / "project.zip",
    )

    assert prepared.source.project_path == "apps/fixture"
    assert prepared.source.commit
    with ZipFile(prepared.archive) as archive:
        files = set(archive.namelist())
        assert "pyproject.toml" in files
        assert "uv.lock" in files
        assert "apps/fixture/pyproject.toml" in files
        assert "libs/fixture-lib/pyproject.toml" in files
        assert archive.read("apps/fixture/src/fixture_app/dist/resource.txt") == (
            b"committed-dist-data\n"
        )
        assert archive.read("apps/fixture/src/fixture_app/build/resource.txt") == (
            b"committed-build-data\n"
        )


def test_builder_rejects_local_source_that_escapes_exported_workspace(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository, local_source="../../../../outside")
    spec = read_distribution_spec(repository / "apps" / "fixture")
    destination = tmp_path / "project.zip"

    with pytest.raises(ValueError, match="escapes or is missing"):
        build_project_snapshot(spec, revision="HEAD", destination=destination)
    assert not destination.exists()


@pytest.mark.parametrize("mutation", ["metadata", "lock"])
def test_prepare_cannot_change_committed_project_configuration_or_lock(
    tmp_path: Path,
    mutation: str,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    spec = read_distribution_spec(repository / "apps" / "fixture")
    destination = tmp_path / "project.zip"

    def prepare(tree: Path) -> None:
        if mutation == "metadata":
            target = tree / "apps/fixture/pyproject.toml"
        else:
            target = tree / "uv.lock"
        target.write_text(target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="modified committed project/workspace configuration|modified the committed uv.lock"):
        build_project_snapshot(
            spec,
            revision="HEAD",
            destination=destination,
            prepare=prepare,
        )
    assert not destination.exists()


def test_destination_collision_preserves_unknown_bytes(tmp_path: Path) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    spec = read_distribution_spec(repository / "apps" / "fixture")
    destination = tmp_path / "project.zip"
    collision = b"user-owned output"
    destination.write_bytes(collision)

    with pytest.raises(FileExistsError):
        build_project_snapshot(spec, revision="HEAD", destination=destination)
    assert destination.read_bytes() == collision
