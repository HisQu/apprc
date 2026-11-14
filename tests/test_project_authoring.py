"""Committed workspace snapshots preserve source and reject unsafe preparation."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest

from apprc.definition.installation import InstallationHooks
from apprc.definition.paths import Paths
from apprc.distribution.metadata import (
    read_distribution_spec,
    read_project_metadata,
)
from apprc.distribution.models import AppCapabilities, DistributionSpec
from apprc.distribution.project import build_project_snapshot
from apprc.distribution.runtime.acquisition import materialize_project_snapshot


def _committed_workspace(
    root: Path,
    *,
    local_source: str = "../../libs/fixture-lib",
    workspace_excludes: str = "",
) -> None:
    app = root / "apps" / "fixture"
    library = root / "libs" / "fixture-lib"
    (app / "src" / "fixture_app" / "dist").mkdir(parents=True)
    (app / "src" / "fixture_app" / "target").mkdir(parents=True)
    if workspace_excludes:
        (root / "apps" / "assets").mkdir(parents=True)
    (library / "src" / "fixture_lib").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[tool.uv.workspace]\nmembers = ['apps/*', 'libs/*']\n"
        "exclude = [" + workspace_excludes + "]\n",
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
        app / "src/fixture_app/target/schema.json": '{"version": 1}\n',
        library / "src/fixture_lib/__init__.py": "VALUE = 2\n",
        app / "package.json": '{"scripts": {"build": "vite build"}}\n',
        app / "vite.config.js": "export default {}\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    if workspace_excludes:
        (root / "apps/assets/README.txt").write_text(
            "excluded data directory\n", encoding="utf-8"
        )
    executable = app / "src/fixture_app/build-helper"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AppRC snapshot fixture",
        "GIT_AUTHOR_EMAIL": "snapshot@example.invalid",
        "GIT_COMMITTER_NAME": "AppRC snapshot fixture",
        "GIT_COMMITTER_EMAIL": "snapshot@example.invalid",
    }
    subprocess.run(
        ["git", "init", "-q", str(root)], env=environment, check=True
    )
    subprocess.run(
        ["git", "-C", str(root), "add", "."], env=environment, check=True
    )
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
        helper = archive.getinfo("apps/fixture/src/fixture_app/build-helper")
        assert helper.external_attr >> 16 & 0o777 == 0o755
        assert archive.read(
            "apps/fixture/src/fixture_app/target/schema.json"
        ) == (b'{"version": 1}\n')
    materialized = tmp_path / "materialized"
    materialize_project_snapshot(
        prepared.archive, materialized, prepared.source
    )
    extracted_helper = (
        materialized / "apps/fixture/src/fixture_app/build-helper"
    )
    assert extracted_helper.stat().st_mode & 0o111


def test_builder_preserves_project_with_trailing_wheel_resource(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    # > Git orders this resource last, leaving its ZIP footer near the TAR end.
    resource = repository / "zz-resource.whl"
    with ZipFile(resource, "w") as wheel:
        wheel.writestr("opaque.bin", b"\x00opaque wheel resource\xff\n")
    _committed_workspace(repository)
    expected = {
        name: (repository / name).read_bytes()
        for name in (
            "pyproject.toml",
            "uv.lock",
            "apps/fixture/pyproject.toml",
            "apps/fixture/src/fixture_app/main.py",
            "libs/fixture-lib/src/fixture_lib/__init__.py",
            resource.name,
        )
    }
    prepared = build_project_snapshot(
        read_distribution_spec(repository / "apps" / "fixture"),
        revision="HEAD",
        destination=tmp_path / "project.zip",
    )

    with ZipFile(prepared.archive) as archive:
        for name, content in expected.items():
            assert archive.read(name) == content
    materialized = tmp_path / "materialized"
    materialize_project_snapshot(
        prepared.archive, materialized, prepared.source
    )
    for name, content in expected.items():
        assert (materialized / name).read_bytes() == content


def test_workspace_exclusion_precedes_member_metadata_validation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository, workspace_excludes="'apps/assets'")
    spec = read_distribution_spec(repository / "apps" / "fixture")
    prepared = build_project_snapshot(
        spec, revision="HEAD", destination=tmp_path / "project.zip"
    )

    with ZipFile(prepared.archive) as archive:
        assert "apps/assets/README.txt" in archive.namelist()
        assert "apps/assets/pyproject.toml" not in archive.namelist()


def test_preparation_removes_generated_target_but_preserves_committed_resource(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    spec = read_distribution_spec(repository / "apps" / "fixture")

    def prepare(tree: Path) -> None:
        frontend_dist = tree / "apps/fixture/dist"
        frontend_dist.mkdir(parents=True)
        (frontend_dist / "bundle.js").write_bytes(b"duplicate bundle")
        dependencies = tree / "apps/fixture/node_modules"
        dependencies.mkdir()
        (dependencies / "marker").write_text("generated\n", encoding="utf-8")
        cache = tree / "apps/fixture/.cache"
        cache.mkdir()
        (cache / "marker").write_text("generated\n", encoding="utf-8")
        packaged_assets = tree / "apps/fixture/src/fixture_app/_web"
        packaged_assets.mkdir()
        (packaged_assets / "bundle.js").write_bytes(
            (frontend_dist / "bundle.js").read_bytes()
        )
        generated = tree / "apps/fixture/src/fixture_app/target/generated.py"
        generated.write_text("generated\n", encoding="utf-8")
        environment = tree / "apps/fixture/.venv"
        environment.mkdir()
        (environment / "marker").write_text("generated\n", encoding="utf-8")

    prepared = build_project_snapshot(
        spec,
        revision="HEAD",
        destination=tmp_path / "project.zip",
        prepare=prepare,
    )
    with ZipFile(prepared.archive) as archive:
        assert archive.read(
            "apps/fixture/src/fixture_app/target/schema.json"
        ) == (b'{"version": 1}\n')
        assert (
            "apps/fixture/src/fixture_app/target/generated.py"
            not in archive.namelist()
        )
        assert not any(
            name.startswith("apps/fixture/.venv") for name in archive.namelist()
        )
        assert archive.read("apps/fixture/src/fixture_app/_web/bundle.js") == (
            b"duplicate bundle"
        )
        assert "apps/fixture/dist/bundle.js" not in archive.namelist()
        assert not any(
            name.startswith(
                ("apps/fixture/node_modules", "apps/fixture/.cache")
            )
            for name in archive.namelist()
        )


@pytest.mark.parametrize("compose_product", [False, True])
def test_manually_composed_spec_preserves_committed_snapshot(
    tmp_path: Path,
    compose_product: bool,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    project = repository / "apps" / "fixture"
    spec = DistributionSpec(metadata=read_project_metadata(project))
    if compose_product:
        spec = replace(
            spec,
            display_name="Fixture Desktop",
            capabilities=AppCapabilities(
                paths=Paths(config=True, appdata=True, cache=True, state=True),
                user_dotenv=True,
                workspaces=True,
                workspace_registry=True,
            ),
            bootstrap_env_prefix="FIXTURE",
            maintenance_group_name="manage",
            launch_enabled=True,
        )

    prepared = build_project_snapshot(
        spec, revision="HEAD", destination=tmp_path / "project.zip"
    )
    materialized = tmp_path / "materialized"
    materialize_project_snapshot(
        prepared.archive, materialized, prepared.source
    )

    assert prepared.source.project_path == "apps/fixture"
    for relative in (
        "uv.lock",
        "apps/fixture/pyproject.toml",
        "apps/fixture/src/fixture_app/main.py",
        "apps/fixture/src/fixture_app/dist/resource.txt",
        "apps/fixture/src/fixture_app/target/schema.json",
        "libs/fixture-lib/src/fixture_lib/__init__.py",
    ):
        assert (materialized / relative).read_bytes() == (
            repository / relative
        ).read_bytes()


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("version = '1.0.0'", "version = '2.0.0'"),
        ("requires-python = '>=3.12'", "requires-python = '>=3.13'"),
        ("app-id = 'fixture-app'", "app-id = 'other-app'"),
        ("import-package = 'fixture_app'", "import-package = 'other_app'"),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\ndistribution-path = 'src/other_distr'",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\nruntime-python = '3.13'",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\ndisplay-name = 'Dirty Product'",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\nconfig = true",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\nbootstrap-env-prefix = 'DIRTY'",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\nmaintenance-group-name = 'manage'",
        ),
        (
            "command-name = 'fixture-app'",
            "command-name = 'fixture-app'\nlaunch-enabled = true",
        ),
    ],
)
def test_dirty_declaration_rejected_with_previously_read_metadata(
    tmp_path: Path,
    original: str,
    changed: str,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    project = repository / "apps" / "fixture"
    spec = DistributionSpec(metadata=read_project_metadata(project))
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(original, changed),
        encoding="utf-8",
    )
    destination = tmp_path / "project.zip"

    with pytest.raises(ValueError, match="Committed project metadata"):
        build_project_snapshot(spec, revision="HEAD", destination=destination)
    assert not destination.exists()


def test_dirty_hook_declaration_rejected_and_explicit_composition_allowed(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "workspace"
    repository.mkdir()
    _committed_workspace(repository)
    project = repository / "apps" / "fixture"
    pyproject = project / "pyproject.toml"
    original = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        original
        + '\n[tool.apprc.distribution.hooks]\ninitialize = "fixture:dirty"\n',
        encoding="utf-8",
    )
    dirty_spec = read_distribution_spec(project)
    destination = tmp_path / "dirty.zip"
    with pytest.raises(ValueError, match="hook declarations"):
        build_project_snapshot(
            dirty_spec, revision="HEAD", destination=destination
        )
    assert not destination.exists()

    pyproject.write_text(original, encoding="utf-8")
    spec = replace(
        read_distribution_spec(project),
        hooks=InstallationHooks(initialize="apprc.shared:initialize"),
    )
    prepared = build_project_snapshot(
        spec, revision="HEAD", destination=tmp_path / "composed.zip"
    )
    assert prepared.archive.is_file()


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
        target.write_text(
            target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8"
        )

    with pytest.raises(ValueError):
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
