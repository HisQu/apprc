"""Authenticated SDK archive composition and binding behavior."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import tarfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from apprc.distribution import native
from apprc.definition.installation import InstallationError, ProjectSnapshot
from apprc.distribution.frontends import (
    _sdk_archive,
    _validate_prepared_project,
)
from apprc.distribution.metadata import read_distribution_spec
from apprc.distribution.models import GitHubReleaseSource, decode_native_binding
from apprc.distribution.project import PreparedProject
from apprc.user_files.app_home.permissions import (
    _path_permissions_are_private,
    create_private_directory_if_missing,
)


@pytest.mark.parametrize(
    ("preview_default", "short_alias", "regular_collision"),
    [
        (None, None, False),
        (False, None, False),
        (True, None, False),
        (True, False, False),
        (True, None, True),
    ],
)
def test_sdk_archive_contains_exact_binding_snapshot_and_sdk_metadata(
    tmp_path: Path,
    preview_default: bool | None,
    short_alias: bool | None,
    regular_collision: bool,
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
    settings = (
        "[project]\nname = 'archive-fixture'\nversion = '1.2.3'\n"
        "[project.scripts]\narchive-fixture = 'fixture_app:main'\n"
    )
    if preview_default is not None:
        if regular_collision:
            settings += "archive-p = 'fixture_app:main'\n"
        settings += (
            "archive-preview = 'fixture_app:preview'\n"
            "[tool.apprc.distribution]\ncommand-name = 'archive-fixture'\n"
            "[tool.apprc.distribution.preview]\n"
            "app-id = 'archive-preview'\ncommand-name = 'archive-preview'\n"
            "apprc-reference = 'fixture_app:PREVIEW'\n"
            "bootstrap-env-prefix = 'ARCHIVE_PREVIEW'\n"
            f"default-for-beta-rc = {str(preview_default).lower()}\n"
        )
        if short_alias is not None:
            settings += f"short-alias = {str(short_alias).lower()}\n"
    (declaration / "pyproject.toml").write_text(settings, encoding="utf-8")
    spec = read_distribution_spec(declaration)
    source_setting = GitHubReleaseSource("fixture/project", False)
    sdk_bytes = _sdk_archive(spec, project, ("gui",), source_setting)

    with ZipFile(BytesIO(sdk_bytes)) as sdk:
        names = set(sdk.namelist())
        metadata_names = {
            name for name in names if name.endswith(".dist-info/METADATA")
        }
        assert "binding.json" in names
        assert ("preview-binding.json" in names) is (
            preview_default is not None
        )
        assert ("preview-default" in names) is (preview_default is True)
        assert ("preview-short-alias" in names) is (
            preview_default is not None
            and short_alias is not False
            and not regular_collision
        )
        if preview_default is not None:
            preview_binding = decode_native_binding(
                sdk.read("preview-binding.json")
            )
            assert preview_binding.identity.app_id == "archive-preview"
            assert preview_binding.identity.commands == ("archive-preview",)
            assert set(json.loads(sdk.read("preview-binding.json"))) == set(
                json.loads(sdk.read("binding.json"))
            )
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
        assert binding.release_source == source_setting
        legacy = json.loads(binding_bytes)
        del legacy["release_source"]
        del legacy["capabilities"]["update_alias"]
        older = decode_native_binding(json.dumps(legacy).encode())
        assert older.release_source is None
        assert older.capabilities.update_alias
        unknown = json.loads(binding_bytes)
        unknown["unrecognized"] = True
        with pytest.raises(ValueError):
            decode_native_binding(json.dumps(unknown).encode())
        requirements = (
            sdk.read("bootstrap-requirements.txt").decode().splitlines()
        )
        assert sum(line.startswith("uv>=") for line in requirements) == 1
        assert not any(name.endswith("fixture_app.py") for name in names)


@pytest.mark.parametrize("member", ["fixture", "other"])
def test_native_authoring_validates_snapshot_for_selected_workspace_member(
    tmp_path: Path,
    member: str,
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

    project_archive = tmp_path / "project.zip"
    with ZipFile(project_archive, "w") as archive:
        archive.writestr("uv.lock", lock)
        archive.writestr(f"apps/{member}/pyproject.toml", declaration)
    archive_bytes = project_archive.read_bytes()
    prepared = PreparedProject(
        project_archive,
        ProjectSnapshot(
            hashlib.sha256(archive_bytes).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "b" * 40,
            f"apps/{member}",
        ),
    )

    workspace = tmp_path / "build"
    create_private_directory_if_missing(workspace)
    if member == "fixture":
        _validate_prepared_project(spec, prepared, workspace)
    else:
        with pytest.raises(
            ValueError, match="different committed project path"
        ):
            _validate_prepared_project(spec, prepared, workspace)
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize(
    ("rust_on_path", "expected_error", "guidance"),
    [
        (False, FileNotFoundError, "Missing from PATH: cargo, rustc"),
        (
            True,
            ValueError,
            "cargo install --locked cargo-xwin --version 0.23.1",
        ),
    ],
)
def test_windows_build_explains_missing_toolchain_before_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rust_on_path: bool,
    expected_error: type[Exception],
    guidance: str,
) -> None:
    runtime_archive = tmp_path / "runtime.zip"
    with ZipFile(runtime_archive, "w") as archive:
        archive.writestr("bootstrap-requirements.txt", native.UV_REQUIREMENT)
    monkeypatch.setattr(
        native.shutil,
        "which",
        lambda name, **_kwargs: str(tmp_path / name) if rust_on_path else None,
    )
    builder = native.NativeFrontendBuilder(
        tmp_path / "compiler", environment={"RUSTUP_TOOLCHAIN": "fixture"}
    )

    def run_tool(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, int("xwin" in command), "", ""
        )

    monkeypatch.setattr(builder, "_run", run_tool)
    monkeypatch.setattr(
        builder,
        "_acquire_source",
        lambda: pytest.fail(
            "Build must check the toolchain before downloading."
        ),
    )
    with pytest.raises(expected_error) as error:
        builder.build(
            target="x86_64-pc-windows-msvc",
            destination=tmp_path / "compiled" / "setup.exe",
            runtime_archive=runtime_archive,
            entrypoint="apprc.distribution.runtime._manager",
        )
    assert guidance in str(error.value)
    assert "Development.md#native-setup-toolchain" in str(error.value)


def test_native_compiler_writes_into_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_asset = BytesIO()
    with tarfile.open(fileobj=source_asset, mode="w:gz") as archive:
        for name in (
            "pyapp/Cargo.toml",
            "pyapp/Cargo.lock",
            "pyapp/build.rs",
            "pyapp/src/main.rs",
        ):
            member = tarfile.TarInfo(name)
            archive.addfile(member)
    source_bytes = source_asset.getvalue()
    monkeypatch.setattr(
        native, "PYAPP_SOURCE_SHA256", hashlib.sha256(source_bytes).hexdigest()
    )
    monkeypatch.setattr(
        native.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: BytesIO(source_bytes),
    )

    runtime_archive = tmp_path / "runtime.zip"
    with ZipFile(runtime_archive, "w") as archive:
        archive.writestr("bootstrap-requirements.txt", native.UV_REQUIREMENT)

    target = "x86_64-unknown-linux-gnu"
    target_directory = tmp_path / "cargo-target"
    compiled = target_directory / target / "release" / "pyapp"
    compiled.parent.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", header, 16, 2, 62)
    compiled.write_bytes(header)
    monkeypatch.setattr(
        native.shutil, "which", lambda name, **_kwargs: str(tmp_path / name)
    )
    builder = native.NativeFrontendBuilder(
        tmp_path / "compiler",
        environment={
            "CARGO_TARGET_DIR": str(target_directory),
            "RUSTUP_TOOLCHAIN": "fixture",
        },
    )
    monkeypatch.setattr(
        builder,
        "_run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
    )

    artifact = builder.build(
        target=target,
        destination=tmp_path / "compiled" / "setup",
        runtime_archive=runtime_archive,
        entrypoint="apprc.distribution.runtime._manager",
    )

    assert artifact.path.read_bytes() == header + runtime_archive.read_bytes()
    source = builder.workspace / "source" / "pyapp"
    for path in (
        source / "src" / "main.rs",
        source / "apprc-inputs" / artifact.report.parent.name / "loader.py",
        artifact.report,
        artifact.path,
    ):
        assert path.is_file()
        assert _path_permissions_are_private(path.parent)


@pytest.mark.parametrize(
    ("use_stderr", "compiler_error", "guidance"),
    [
        (True, "error: link failed", "Check the Rust MSVC target"),
        (False, "error: link failed", "Check the Rust MSVC target"),
        (
            True,
            "unable to symlink from SDK include (os error 1314)",
            "Developer Mode (Entwicklermodus)",
        ),
        (
            True,
            "error: linker `lld-link` not found",
            "Add LLVM's bin directory to PATH",
        ),
    ],
)
def test_native_build_failure_includes_sanitized_compiler_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_stderr: bool,
    compiler_error: str,
    guidance: str,
) -> None:
    runtime_archive = tmp_path / "runtime.zip"
    with ZipFile(runtime_archive, "w") as archive:
        archive.writestr("bootstrap-requirements.txt", native.UV_REQUIREMENT)
    source = tmp_path / "pyapp"
    source.mkdir()
    builder = native.NativeFrontendBuilder(
        tmp_path / "compiler",
        environment={
            "RUSTUP_TOOLCHAIN": "fixture",
            "CARGO_REGISTRIES_FIXTURE_TOKEN": "fixture-secret",
        },
    )
    monkeypatch.setattr(builder, "_acquire_source", lambda: source)
    monkeypatch.setattr(
        native.shutil, "which", lambda name, **_kwargs: str(tmp_path / name)
    )

    def run_tool(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "build" not in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        detail = (
            "compile progress\n" * 1000 + f"{compiler_error} (fixture-secret)\n"
        )
        stdout, stderr = ("", detail) if use_stderr else (detail, "")
        return subprocess.CompletedProcess(command, 101, stdout, stderr)

    monkeypatch.setattr(native.subprocess, "run", run_tool)
    with pytest.raises(InstallationError) as error:
        builder.build(
            target="x86_64-pc-windows-msvc",
            destination=tmp_path / "compiled" / "setup.exe",
            runtime_archive=runtime_archive,
            entrypoint="apprc.distribution.runtime._manager",
        )

    message = str(error.value)
    assert "x86_64-pc-windows-msvc exited with code 101" in message
    assert guidance in message
    assert f"{compiler_error} ([redacted])" in message
    assert "fixture-secret" not in message
    assert len(message) < 5000
