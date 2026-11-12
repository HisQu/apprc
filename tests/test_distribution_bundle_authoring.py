"""Opt-in real-tool proof for locked selected-repository wheel authoring."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from tests.support_pyapp import pinned_uv

from apprc.definition.installation import (
    InstallationError,
    InstallationPlacement,
)
from apprc.definition.paths import Layout
from apprc.distribution.bundles import (
    _git_source,
    _repository,
    _validate_locked_origins,
    compile_wheel_bundle,
)
from apprc.distribution.metadata import read_project_metadata
from apprc.distribution.models import DistributionSpec
from apprc.distribution.runtime import installed_probe
from apprc.distribution.runtime.acquisition import SourceSelection
from apprc.distribution.runtime.backend import remove_uv_tool, select_uv_target
from apprc.distribution.runtime.bundles import prepare_wheel_bundle
from apprc.distribution.runtime.installation import install_application
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import plan_install

pytestmark = pytest.mark.skipif(
    os.environ.get("APPRC_TEST_PYAPP") != "1",
    reason="real locked bundle compilation requires APPRC_TEST_PYAPP=1",
)


def _run(args: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, f"{args!r}\n{result.stdout}\n{result.stderr}"
    return result.stdout.strip()


def _project(path: Path, name: str, module: str) -> None:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=80"]\n'
        'build-backend = "setuptools.build_meta"\n'
        f'[project]\nname = "{name}"\nversion = "1.0.0"\n'
        'requires-python = ">=3.12"\n'
        f'[tool.setuptools]\npy-modules = ["{module}"]\n',
        encoding="utf-8",
    )
    (path / f"{module}.py").write_text(f"VALUE = {name!r}\n", encoding="utf-8")


@pytest.mark.parametrize(
    "application_is_workspace_member",
    (False, True),
    ids=("workspace-root-app", "workspace-member-app"),
)
def test_locked_git_monorepo_bundle_builds_only_selected_extra_graph(
    tmp_path: Path, application_is_workspace_member: bool
) -> None:
    if sys.platform != "linux":
        pytest.skip("Managed recipient execution is limited to Linux.")
    workspace_root = tmp_path / "application"
    root = (
        workspace_root / "apps" / "application"
        if application_is_workspace_member
        else workspace_root
    )
    root.mkdir(parents=True)
    repo = tmp_path / "monorepo"
    _project(repo / "packages" / "one", "bundle-one", "bundle_one")
    _project(repo / "packages" / "two", "bundle-two", "bundle_two")
    _project(repo / "packages" / "dev", "bundle-dev", "bundle_dev")
    _project(repo / "packages" / "default", "bundle-default", "bundle_default")
    _project(repo / "packages" / "windows", "bundle-windows", "bundle_windows")
    _run(["git", "init", str(repo)], cwd=tmp_path, env=dict(os.environ))
    _run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "test@example.invalid",
        ],
        cwd=tmp_path,
        env=dict(os.environ),
    )
    _run(
        ["git", "-C", str(repo), "config", "user.name", "Bundle test"],
        cwd=tmp_path,
        env=dict(os.environ),
    )
    _run(
        ["git", "-C", str(repo), "add", "."], cwd=tmp_path, env=dict(os.environ)
    )
    _run(
        ["git", "-C", str(repo), "commit", "-m", "fixture"],
        cwd=tmp_path,
        env=dict(os.environ),
    )
    commit = _run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        cwd=tmp_path,
        env=dict(os.environ),
    )
    repository = "https://bundles.invalid/fixture/repo"
    uv = pinned_uv(tmp_path / "pinned-tool")
    flat_index = tmp_path / "flat-index"
    flat_index.mkdir()
    _run(
        [
            str(uv.parent / "python"),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "download",
            "--no-deps",
            "--only-binary=:all:",
            "--dest",
            str(flat_index),
            "idna==3.10",
        ],
        cwd=tmp_path,
        env=dict(os.environ),
    )
    _project(
        workspace_root / "workspace" / "required",
        "workspace-required",
        "workspace_required",
    )
    _project(
        workspace_root / "workspace" / "unrelated",
        "workspace-unrelated",
        "workspace_unrelated",
    )
    workspace_config = (
        ""
        if application_is_workspace_member
        else '[tool.uv.workspace]\nmembers = ["workspace/*"]\n'
    )
    if application_is_workspace_member:
        (workspace_root / "pyproject.toml").write_text(
            "[tool.uv.workspace]\n"
            'members = ["apps/application", "workspace/*"]\n',
            encoding="utf-8",
        )
    dependencies = [
        "workspace-required",
        f"bundle-one @ git+{repository}@{commit}#subdirectory=packages/one",
        f"bundle-windows @ git+{repository}@{commit}#subdirectory=packages/windows ; sys_platform == 'win32'",
    ]
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=80"]\n'
        'build-backend = "setuptools.build_meta"\n'
        '[project]\nname = "bundle-root"\nversion = "1.0.0"\n'
        'requires-python = ">=3.12"\n'
        f"dependencies = {json.dumps(dependencies)}\n"
        "[project.optional-dependencies]\n"
        f'feature = ["bundle-two @ git+{repository}@{commit}#subdirectory=packages/two", "idna==3.10"]\n'
        '[project.scripts]\nbundle-root = "bundle_root:main"\n'
        '[dependency-groups]\ndev = ["bundle-dev @ git+'
        f'{repository}@{commit}#subdirectory=packages/dev"]\n'
        'lint = ["bundle-default @ git+'
        f'{repository}@{commit}#subdirectory=packages/default"]\n'
        '[tool.uv]\ndefault-groups = ["lint"]\n'
        f"{workspace_config}"
        "[tool.uv.sources]\nworkspace-required = { workspace = true }\n"
        '[tool.setuptools]\npy-modules = ["bundle_root"]\n'
        '[tool.apprc.distribution]\nbundle-repositories = ["https://bundles.invalid/fixture/repo.git"]\n',
        encoding="utf-8",
    )
    (root / "bundle_root.py").write_text(
        "import bundle_one, bundle_two, idna, workspace_required\n"
        "def main():\n"
        "    print('|'.join((bundle_one.VALUE, bundle_two.VALUE, idna.__version__, workspace_required.VALUE)))\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    for name in (
        "UV_CONFIG_FILE",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_FIND_LINKS",
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_OFFLINE",
    ):
        environment.pop(name, None)
    environment["GIT_CONFIG_COUNT"] = "1"
    environment["GIT_CONFIG_KEY_0"] = f"url.file://{repo.as_posix()}.insteadOf"
    environment["GIT_CONFIG_VALUE_0"] = repository
    _run(
        [str(uv), "lock", "--python", sys.executable],
        cwd=root,
        env=environment,
    )

    metadata = read_project_metadata(root)
    rejected_specs = (
        (
            "runtime-requirements",
            replace(
                DistributionSpec(metadata),
                runtime_requirements=("manual-runtime==1.0",),
            ),
        ),
        (
            "runtime-overrides",
            replace(
                DistributionSpec(metadata),
                runtime_overrides=("manual-override==1.0",),
            ),
        ),
    )
    for label, rejected_spec in rejected_specs:
        rejected_destination = tmp_path / f"manual-graph-{label}"
        with pytest.raises(InstallationError):
            compile_wheel_bundle(
                rejected_spec,
                rejected_destination,
                uv=uv,
                application_source=root,
                extras=("feature",),
                environment=environment,
            )
        assert not rejected_destination.exists()
    bad_metadata = replace(
        metadata, bundle_repositories=("https://unknown.invalid/repo",)
    )
    invalid_destination = tmp_path / "invalid bundle"
    with pytest.raises(InstallationError):
        compile_wheel_bundle(
            DistributionSpec(bad_metadata),
            invalid_destination,
            uv=uv,
            application_source=root,
            extras=("feature",),
            environment=environment,
        )
    assert not invalid_destination.exists()
    unbundled_metadata = replace(metadata, bundle_repositories=())
    unbundled_destination = tmp_path / "unbundled bundle"
    with pytest.raises(InstallationError):
        compile_wheel_bundle(
            DistributionSpec(unbundled_metadata),
            unbundled_destination,
            uv=uv,
            application_source=root,
            extras=("feature",),
            environment=environment,
        )
    assert not unbundled_destination.exists()
    result = compile_wheel_bundle(
        DistributionSpec(metadata),
        tmp_path / "compiled bundle",
        uv=uv,
        application_source=root,
        extras=("feature",),
        environment=environment,
    )
    inventory = {canonicalize_name(entry.name) for entry in result.wheels}
    assert inventory >= {
        "bundle-root",
        "bundle-one",
        "bundle-two",
        "bundle-windows",
        "workspace-required",
    }
    assert len({entry.commit for entry in result.wheels if entry.commit}) == 1
    assert len([entry for entry in result.wheels if entry.commit]) == 3
    assert all(
        str(repo) not in entry.original_requirement
        and "file://" not in entry.original_requirement
        for entry in result.wheels
        if entry.original_requirement
    )
    assert not result.remaining_git_sources
    assert any(
        canonicalize_name(Requirement(line).name) == "bundle-two"
        for line in result.source.runtime_requirements
    )
    root_requirement = next(
        Requirement(line)
        for line in result.source.runtime_requirements
        if canonicalize_name(Requirement(line).name) == "bundle-root"
    )
    assert "feature" in root_requirement.extras
    assert "bundle-dev" not in inventory
    assert "bundle-default" not in inventory
    assert "workspace-unrelated" not in inventory
    assert "idna" not in inventory
    assert any(
        canonicalize_name(Requirement(line).name) == "idna"
        for line in result.source.runtime_requirements
    )
    assert any(
        canonicalize_name(Requirement(line).name) == "workspace-required"
        and str(Requirement(line).specifier) == "==1.0.0"
        for line in result.source.runtime_requirements
    )
    assert all(
        canonicalize_name(Requirement(line).name)
        not in {"bundle-dev", "bundle-default", "workspace-unrelated"}
        for line in result.source.runtime_requirements
    )
    windows = next(
        Requirement(line)
        for line in result.source.runtime_requirements
        if canonicalize_name(Requirement(line).name) == "bundle-windows"
    )
    assert windows.marker is not None
    assert windows.marker.evaluate({"sys_platform": "win32"})
    assert not windows.marker.evaluate({"sys_platform": "linux"})
    prepared = prepare_wheel_bundle(
        result.directory,
        tmp_path / "managed staging",
        source=result.source,
        distribution="bundle-root",
    )
    root_wheel = next(
        entry for entry in prepared.wheels if entry.name == "bundle-root"
    )
    assert result.source.requirement == root_wheel.filename
    prepared_source = SourceSelection(
        result.source,
        package_path=result.directory / result.source.requirement,
    ).prepare(tmp_path / "managed staging")
    prepared_source = replace(prepared_source, bundle=prepared)
    recipient_root = tmp_path / "recipient"
    recipient = dict(environment)
    for key, relative in {
        "HOME": "home",
        "USERPROFILE": "home",
        "XDG_CONFIG_HOME": "config",
        "XDG_DATA_HOME": "data",
        "XDG_CACHE_HOME": "cache",
        "XDG_STATE_HOME": "state",
        "UV_TOOL_DIR": "tools",
        "UV_TOOL_BIN_DIR": "commands",
        "UV_CACHE_DIR": "uv-cache",
        "UV_PYTHON_INSTALL_DIR": "python",
    }.items():
        recipient[key] = str(recipient_root / relative)
    recipient["UV_FIND_LINKS"] = str(flat_index)
    empty_path = recipient_root / "empty-path"
    empty_path.mkdir(parents=True)
    recipient["PATH"] = str(empty_path)
    for key in tuple(recipient):
        if key.startswith(("GIT_CONFIG_", "PYTHON", "PIP_")) or key in {
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
        }:
            recipient.pop(key)
    for command in ("git", "gh", "uv"):
        assert shutil.which(command, path=recipient["PATH"]) is None
    target = select_uv_target(
        uv, environment=recipient, invocation_cwd=tmp_path
    )
    placement = InstallationPlacement(Layout.native())
    install_directory = tmp_path / "managed installation"
    inspection = inspect_installation(
        install_directory, app_id=metadata.identity.app_id
    )
    plan = plan_install(
        metadata.identity,
        result.source,
        placement,
        target,
        inspection=inspection,
    )
    try:
        installed = install_application(
            plan,
            environment={**recipient, "UV_OFFLINE": "1"},
            probe_path=Path(installed_probe.__file__).absolute(),
            support_files={},
            python_requirement=sys.executable,
            prepared_source=prepared_source,
        )
        assert (
            installed.record is not None
            and installed.record.current is not None
        )
        command_result = _run(
            [str(installed.record.current.commands[0])],
            cwd=tmp_path,
            env=recipient,
        )
        assert command_result == "bundle-one|bundle-two|3.10|workspace-required"
        _run(
            [
                str(installed.record.current.prefix / "bin" / "python"),
                "-I",
                "-c",
                "import importlib.util; "
                "assert importlib.util.find_spec('bundle_windows') is None",
            ],
            cwd=tmp_path,
            env=recipient,
        )
    finally:
        remove_uv_tool(target, metadata.identity.app_id, environment=recipient)


def test_locked_source_rejects_mutable_and_unsafe_git_authority() -> None:
    with pytest.raises(InstallationError):
        _repository("https://author:secret@example.invalid/repo")
    with pytest.raises(InstallationError):
        _repository("https://example.invalid/packages/../repo")
    _validate_locked_origins([{"index": "https://pypi.org/simple/"}])
    with pytest.raises(InstallationError):
        _validate_locked_origins([{"index": "https://packages.example/simple"}])
    package: dict[str, object] = {
        "name": "fixture-package",
        "version": "1.0.0",
        "vcs": {
            "type": "git",
            "url": "https://example.invalid/repo",
            "commit-id": "a" * 40,
            "requested-revision": "main",
        },
    }
    with pytest.raises(InstallationError):
        _git_source(package)
    vcs = package["vcs"]
    assert isinstance(vcs, dict)
    vcs["requested-revision"] = "a" * 40
    vcs["subdirectory"] = "../../outside"
    with pytest.raises(InstallationError):
        _git_source(package)
