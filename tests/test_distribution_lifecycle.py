"""Maintained source identity and artifact-composition scenarios."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

import pytest

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationSource,
    OperationStep,
)
from apprc.distribution.models import (
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import (
    generate_artifacts,
)
from apprc.distribution.runtime import controllers
from apprc.distribution.runtime.acquisition import (
    SourceSelection,
    _archive_inputs,
    installation_source,
    parse_source_arguments,
    prepare_source,
)
from apprc.distribution.runtime.controllers import prepare_uninstall
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.env_files.secrets import ensure_secret_file
from apprc.user_files.installation.discovery import inspect_installation
from tests.test_distribution_support_recovery import (
    _run as install_support_fixture,
)
from tests.test_distribution_support_recovery import (
    _scenario as installation_scenario,
)
from tests.test_distribution_support_recovery import (
    _stub_backend,
)


def test_dirty_checkout_python_entry_runs_from_outside_checkout(
    tmp_path: Path,
) -> None:
    from apprc.distribution.rendering import (
        render_python_installer,
        standalone_script,
    )

    project = tmp_path / "dirty checkout"
    project.mkdir()
    identity = InstallationIdentity(
        "checkout-app", "checkout-app", "checkout_app", None, ("checkout-app",)
    )
    spec = DistributionSpec(ProjectMetadata(project, identity, "1.2.3"))
    package = project / "app_lifecycle"
    package.mkdir()
    (package / "__init__.py").write_text(
        '"""Checkout fixture."""\n', encoding="utf-8"
    )
    (package / "install.py").write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "def main():\n"
        "    value = {'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'dirty': Path(os.environ['APPRC_CHECKOUT_ROOT'], 'dirty.txt').read_text()}\n"
        "    Path(os.environ['APPRC_NATIVE_MARKER']).write_text(json.dumps(value), encoding='utf-8')\n"
        "    if '--exit-37' in sys.argv: raise SystemExit(37)\n"
        "if __name__ == '__main__': main()\n",
        encoding="utf-8",
    )
    (package / "uninstall.py").write_text(
        "def main(): return 0\nif __name__ == '__main__': main()\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['setuptools>=80']\n"
        "build-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'checkout-app'\nversion = '1.2.3'\n"
        "[tool.setuptools.packages.find]\ninclude = ['app_lifecycle*']\n",
        encoding="utf-8",
    )
    dirty_content = "modified source retained from the checkout"
    (project / "dirty.txt").write_text(dirty_content, encoding="utf-8")
    payload = PayloadTree(
        project,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    artifact_directory = (
        project / spec.metadata.distribution_path / "artifacts" / "installer"
    )
    artifact_directory.mkdir(parents=True)
    (artifact_directory / "main-installer.py").write_bytes(
        standalone_script(spec, payload, entry=payload.entry_module)
    )
    app_install = project / "app-install.py"
    app_install.write_bytes(render_python_installer(spec).content)
    marker = tmp_path / "checkout result.json"
    caller_directory = tmp_path / "unrelated caller directory"
    caller_directory.mkdir()
    uv = shutil.which("uv")
    assert uv is not None
    arguments = ("literal%20", "snowman ☃")
    for uv_environment in ({"UV": uv}, {}):
        environment = dict(
            os.environ,
            APPRC_NATIVE_MARKER=str(marker),
            APPRC_CHECKOUT_ROOT=str(project),
        )
        environment.pop("UV", None)
        environment.update(uv_environment)
        result = subprocess.run(
            [sys.executable, str(app_install), "--", *arguments, "--exit-37"],
            env=environment,
            cwd=caller_directory,
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
        )
        assert result.returncode == 37, result.stdout + result.stderr
        observed = json.loads(marker.read_text(encoding="utf-8"))
        assert observed["dirty"] == dirty_content
        assert observed["cwd"] == str(caller_directory)
        assert observed["argv"][-4:] == ["--", *arguments, "--exit-37"]


def test_release_asset_digest_and_runtime_constraints_are_captured(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "sample-2.4.1.tar.gz"
    payloads = {
        "pyproject.toml": b"[project]\nname='sample'\nversion='2.4.1'\n",
        "PKG-INFO": b"Metadata-Version: 2.1\nName: sample\nVersion: 2.4.1\n",
        "sample.egg-info/PKG-INFO": (
            b"Metadata-Version: 2.1\nName: sample\nVersion: 2.4.1\n"
        ),
        "sample.egg-info/SOURCES.txt": b"pyproject.toml\n",
    }
    with tarfile.open(asset, "w:gz") as archive:
        for relative, content in payloads.items():
            member = tarfile.TarInfo(f"sample-2.4.1/{relative}")
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    payload = payloads["pyproject.toml"]
    source = InstallationSource(
        "release-sdist",
        str(asset),
        version="2.4.1",
        digest=hashlib.sha256(asset.read_bytes()).hexdigest(),
        runtime_requirements=("apprc-core==0.31.0", "click==8.2.1"),
        runtime_overrides=(
            "apprc-core @ git+https://example.invalid/apprc@0123456789abcdef",
        ),
    )

    prepared = prepare_source(source, tmp_path / "staging")

    assert prepared.archive == tmp_path / "staging" / "source.tar.gz"
    assert prepared.project_directory == Path(prepared.requirement)
    assert (
        Path(prepared.requirement) / "pyproject.toml"
    ).read_bytes() == payload
    assert prepared.digest == source.digest
    assert prepared.constraints is not None
    assert (
        prepared.constraints.read_text(encoding="utf-8")
        == "apprc-core==0.31.0\nclick==8.2.1\n"
    )
    assert prepared.source.runtime_overrides == source.runtime_overrides
    assert prepared.archive is not None
    assert prepared.source_root is not None
    (prepared.source_root / "PKG-INFO").write_text(
        "build-generated metadata", encoding="utf-8"
    )
    (prepared.source_root / "sample.egg-info" / "PKG-INFO").write_text(
        "build-generated metadata", encoding="utf-8"
    )
    (prepared.source_root / "sample.egg-info" / "SOURCES.txt").write_text(
        "generated source inventory", encoding="utf-8"
    )
    _archive_inputs(prepared.archive, prepared.source_root, extract=False)
    (prepared.source_root / "pyproject.toml").write_text(
        "authored configuration changed", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="verified archive"):
        _archive_inputs(prepared.archive, prepared.source_root, extract=False)


@pytest.mark.parametrize("archive_kind", ("tar", "zip"))
@pytest.mark.parametrize(
    "member", ("../outside", "/absolute", "folder\\escape")
)
def test_release_sdist_rejects_unsafe_archive_members(
    tmp_path: Path, archive_kind: str, member: str
) -> None:
    asset = tmp_path / f"unsafe.{archive_kind}"
    payload = b"[project]\nname='sample'\nversion='2.4.1'\n"
    if archive_kind == "tar":
        with tarfile.open(asset, "w:gz") as archive:
            project = tarfile.TarInfo("sample/pyproject.toml")
            project.size = len(payload)
            archive.addfile(project, BytesIO(payload))
            traversal = tarfile.TarInfo(member)
            traversal.size = 1
            archive.addfile(traversal, BytesIO(b"x"))
    else:
        with ZipFile(asset, "w") as archive:
            archive.writestr("sample/pyproject.toml", payload)
            archive.writestr(member, "x")
    source = InstallationSource(
        "release-sdist",
        str(asset),
        version="2.4.1",
        digest=hashlib.sha256(asset.read_bytes()).hexdigest(),
        runtime_requirements=("apprc-core==0.31.0",),
    )
    with pytest.raises(ValueError, match="Unsafe"):
        prepare_source(source, tmp_path / "staging")


@pytest.mark.parametrize("archive_kind", ("tar", "zip"))
def test_release_sdist_rejects_escaping_archive_links(
    tmp_path: Path, archive_kind: str
) -> None:
    asset = tmp_path / f"linked.{archive_kind}"
    payload = b"[project]\nname='sample'\nversion='2.4.1'\n"
    if archive_kind == "tar":
        with tarfile.open(asset, "w:gz") as archive:
            project = tarfile.TarInfo("sample/pyproject.toml")
            project.size = len(payload)
            archive.addfile(project, BytesIO(payload))
            link = tarfile.TarInfo("sample/escape")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../outside"
            archive.addfile(link)
    else:
        with ZipFile(asset, "w") as archive:
            archive.writestr("sample/pyproject.toml", payload)
            link = ZipInfo("sample/escape")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../outside")
    source = InstallationSource(
        "release-sdist",
        str(asset),
        version="2.4.1",
        digest=hashlib.sha256(asset.read_bytes()).hexdigest(),
        runtime_requirements=("apprc-core==0.31.0",),
    )
    with pytest.raises(ValueError, match="link or special member"):
        prepare_source(source, tmp_path / "staging")


@pytest.mark.parametrize("archive_kind", ("tar", "zip"))
def test_release_sdist_rejects_ambiguous_wrapper_layout(
    tmp_path: Path, archive_kind: str
) -> None:
    asset = tmp_path / f"ambiguous.{archive_kind}"
    payload = b"[project]\nname='sample'\nversion='2.4.1'\n"
    if archive_kind == "tar":
        with tarfile.open(asset, "w:gz") as archive:
            for name, content in (
                ("sample/pyproject.toml", payload),
                ("orphan/README.txt", b"unwrapped"),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, BytesIO(content))
    else:
        with ZipFile(asset, "w") as archive:
            archive.writestr("sample/pyproject.toml", payload)
            archive.writestr("orphan/README.txt", "unwrapped")
    source = InstallationSource(
        "release-sdist",
        str(asset),
        version="2.4.1",
        digest=hashlib.sha256(asset.read_bytes()).hexdigest(),
        runtime_requirements=("apprc-core==0.31.0",),
    )
    with pytest.raises(ValueError, match="Selected source project directory"):
        prepare_source(source, tmp_path / "staging")


@pytest.mark.parametrize("subdirectory", ("../escape", "missing"))
def test_immutable_main_rejects_unsafe_or_missing_project_selection(
    tmp_path: Path, subdirectory: str
) -> None:
    archive_path = tmp_path / "main.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("wrapper/pyproject.toml", "[project]\nname='sample'\n")
    requirement = (
        "git+https://github.com/example/sample.git@"
        + "a" * 40
        + f"#subdirectory={subdirectory}"
    )
    selection = SourceSelection(
        InstallationSource("index", requirement),
        package_path=archive_path,
        subdirectory=subdirectory,
    )
    with pytest.raises(ValueError, match="subdirectory|project directory"):
        selection.prepare(tmp_path / "staging")


def test_explicit_wheel_is_staged_by_digest_and_wrong_digest_is_refused(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "sample-2.4.1-py3-none-any.whl"
    with ZipFile(asset, "w") as wheel:
        wheel.writestr(
            "sample-2.4.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: sample\nVersion: 2.4.1\n",
        )
        wheel.writestr(
            "sample-2.4.1.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    source = InstallationSource(
        "wheel", str(asset), version="2.4.1", digest=digest
    )
    prepared = prepare_source(source, tmp_path / "staging")
    assert prepared.digest == digest
    assert prepared.source_root is not None
    assert Path(prepared.requirement).read_bytes() == asset.read_bytes()

    wrong_digest = replace(source, digest="0" * 64)
    with pytest.raises(ValueError, match="digest"):
        prepare_source(wrong_digest, tmp_path / "wrong staging")


def test_distribution_modes_preserve_exact_source_identity(
    tmp_path: Path,
) -> None:
    project = tmp_path / "checkout"
    (project / "workspace%20root").mkdir(parents=True)
    identity = InstallationIdentity(
        "fixture-app", "fixture-app", "fixture", None, ("fixture",)
    )
    metadata = ProjectMetadata(
        project,
        identity,
        "1.2.3",
        project_path=PurePosixPath("workspace%20root"),
    )
    checkout = installation_source(DistributionSpec(metadata))
    assert checkout.kind == "editable"
    assert checkout.requirement == str(project / "workspace%20root")

    main_spec = DistributionSpec(
        metadata,
        source_mode="main",
        repository_url="https://github.com/example/app.git",
        release_commit="a" * 40,
    )
    main = installation_source(main_spec)
    assert (
        main.requirement
        == f"git+https://github.com/example/app.git@{'a' * 40}#subdirectory=workspace%20root"
    )

    release = installation_source(
        DistributionSpec(
            metadata,
            source_mode="release",
            repository_url="https://example.invalid/app",
            release_version="1.2.3",
            release_commit="b" * 40,
            release_asset="dist/app-1.2.3.tar.gz",
            release_digest="c" * 64,
            runtime_requirements=("apprc-core==0.31.0",),
            runtime_overrides=("apprc-core==0.32.0",),
        )
    )
    assert release.kind == "release-sdist"
    assert release.requirement == str(project / "dist" / "app-1.2.3.tar.gz")
    assert release.runtime_requirements == ("apprc-core==0.31.0",)
    assert release.runtime_overrides == ("apprc-core==0.32.0",)

    indexed = installation_source(
        DistributionSpec(metadata, source_mode="index")
    )
    assert indexed.requirement == "fixture-app==1.2.3"
    prepared_index = prepare_source(indexed, tmp_path / "index-staging")
    assert prepared_index.requirement == indexed.requirement


def test_frontend_rejects_invalid_selectors_before_authored_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apprc.distribution import _frontend

    config = _frontend.FrontendConfig(
        app_id="bootstrap-app",
        distribution="bootstrap-app",
        repository_url=None,
        distribution_path="src/bootstrap_app",
        project_path=".",
        payload_format="script",
        source_mode="checkout",
        version="1.2.3",
        commit=None,
    )
    monkeypatch.setattr(
        _frontend,
        "_execute",
        lambda *args, **kwargs: pytest.fail("authored setup must not run"),
    )
    installer = tmp_path / "missing-main-installer.py"
    assert _frontend.run_installer(config, ("--version",)) == 2
    assert _frontend.run_installer(config, ("--main-ref", "main")) == 2
    assert _frontend.run_installer(config, ()) == 2
    assert (
        _frontend.run_installer(
            config, ("--github-client", "gh"), local_installer=installer
        )
        == 2
    )


def test_main_source_arguments_bind_the_resolved_commit_and_preserve_app_argv(
    tmp_path: Path,
) -> None:
    metadata = ProjectMetadata(
        tmp_path,
        InstallationIdentity(
            "remote-app", "remote-app", "remote_app", None, ("remote-app",)
        ),
        "1.2.3",
    )
    repository = "https://github.com/example/remote-app.git"
    transport_repository = "https://github.com/example/remote-app"
    spec = DistributionSpec(
        metadata,
        source_mode="main",
        repository_url=repository,
        release_commit="a" * 40,
    )
    selection, remaining = parse_source_arguments(
        spec,
        (
            "--source-mode",
            "main",
            "--source-repository",
            transport_repository,
            "--source-commit",
            "b" * 40,
            "--github-client",
            "gh",
            "--repair",
            "literal%20",
            "--",
            "--source-commit",
            "user argument",
        ),
    )

    assert selection.source.requirement == f"git+{repository}@{'b' * 40}"
    assert selection.github_client == "gh"
    assert remaining == (
        "--repair",
        "literal%20",
        "--",
        "--source-commit",
        "user argument",
    )
    checkout_spec = DistributionSpec(
        metadata,
        source_mode="checkout",
        repository_url=repository,
    )
    checkout_selection, _ = parse_source_arguments(
        checkout_spec,
        (
            "--source-mode",
            "main",
            "--source-repository",
            repository,
            "--source-commit",
            "b" * 40,
        ),
    )
    assert checkout_selection.source.kind == "index"
    assert checkout_selection.source.requirement.endswith("@" + "b" * 40)

    local_selection, local_arguments = parse_source_arguments(
        checkout_spec,
        ("--github-client", "gh", "--repair"),
    )
    assert local_selection.source.kind == "editable"
    assert local_selection.github_client == "gh"
    assert local_arguments == ("--repair",)
    with pytest.raises(ValueError, match="supplied together"):
        parse_source_arguments(
            spec,
            ("--source-mode", "main"),
        )
    with pytest.raises(ValueError, match="repository"):
        parse_source_arguments(
            spec,
            (
                "--source-mode",
                "main",
                "--source-repository",
                "https://github.com/other/remote-app.git",
                "--source-commit",
                "b" * 40,
            ),
        )
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        parse_source_arguments(
            spec,
            (
                "--source-mode",
                "main",
                "--source-repository",
                repository,
                "--source-commit",
                "b" * 39,
            ),
        )


def test_remote_main_frontend_resolves_one_commit_for_selected_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apprc.distribution import _frontend

    config = _frontend.FrontendConfig(
        app_id="main-app",
        distribution="main-app",
        repository_url="https://github.com/example/main-app.git",
        distribution_path="src/main café_distr",
        project_path=".",
        payload_format="script",
        source_mode="checkout",
        version="1.2.3",
        commit=None,
    )
    commit = "c" * 40
    reads: list[str] = []
    downloads: list[str] = []
    executions: list[tuple[Path, list[str], list[str]]] = []
    monkeypatch.setattr(
        _frontend,
        "_read_url",
        lambda address, *, client, limit=_frontend._METADATA_LIMIT: (
            reads.append(address) or json.dumps({"sha": commit}).encode()
        ),
    )

    def download(
        address: str, destination: Path, client: str, **kwargs: Any
    ) -> None:
        downloads.append(address)
        destination.write_bytes(b"selected source bytes")

    monkeypatch.setattr(_frontend, "_download", download)
    monkeypatch.setattr(
        _frontend,
        "_execute",
        lambda payload, payload_format, transport, forwarded, **kwargs: (
            executions.append((payload, list(transport), list(forwarded))) or 7
        ),
    )

    assert (
        _frontend.run_installer(config, ("--main", "--repair", "literal%20"))
        == 7
    )
    assert reads == [
        "https://api.github.com/repos/example/main-app/commits/main"
    ]
    assert len(downloads) == 2
    assert all(
        f"/{commit}/" in address or address.endswith(f"/{commit}")
        for address in downloads
    )
    assert (
        executions[0][1][executions[0][1].index("--source-commit") + 1]
        == commit
    )
    assert executions[0][2] == ["--repair", "literal%20"]

    gh_downloads: list[tuple[str, str]] = []

    def gh_download(
        address: str, destination: Path, client: str, **kwargs: Any
    ) -> None:
        gh_downloads.append((address, client))
        destination.write_bytes(b"selected source bytes")

    monkeypatch.setattr(_frontend, "_download", gh_download)
    assert (
        _frontend.run_installer(
            config, ("--main", "--github-client", "gh", "--repair")
        )
        == 7
    )
    assert len(gh_downloads) == 2
    assert {client for _, client in gh_downloads} == {"gh"}
    assert executions[-1][1][-1] == "gh"


def test_release_payload_requires_matching_manifest_before_authored_install(
    tmp_path: Path,
) -> None:
    from apprc.distribution.rendering import standalone_script

    project = tmp_path / "release author"
    payload_root = project / "payload"
    package = payload_root / "app_lifecycle"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '"""Release fixture."""\n', encoding="utf-8"
    )
    (package / "install.py").write_text(
        "import os\nfrom pathlib import Path\n"
        'def main():\n    Path(os.environ["APP_MARKER"]).write_text("ran", encoding="utf-8")\n'
        '\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (package / "uninstall.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    payload = PayloadTree(
        payload_root,
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    identity = InstallationIdentity(
        "release-app", "release-app", "release_app", None, ("release-app",)
    )
    metadata = ProjectMetadata(project, identity, "1.0.0")
    spec = DistributionSpec(
        metadata,
        source_mode="release",
        repository_url="https://github.com/example/release-app",
        release_version="1.0.0",
        release_commit="a" * 40,
        release_asset="https://github.com/example/release-app/releases/download/v1.0.0/release-app-1.0.0.tar.gz",
        release_digest="b" * 64,
        runtime_requirements=("apprc-core==0.31.0",),
    )
    script = standalone_script(spec, payload, entry=payload.entry_module)
    release_dir = tmp_path / "published release"
    release_dir.mkdir()
    script_path = release_dir / "main-installer.py"
    script_path.write_bytes(script)
    manifest = {
        "schema_version": 1,
        "app_id": identity.app_id,
        "distribution": identity.distribution,
        "version": "1.0.0",
        "commit": "a" * 40,
        "payload_format": "script",
        "assets": [
            {
                "filename": script_path.name,
                "size": len(script),
                "sha256": hashlib.sha256(script).hexdigest(),
            },
            {
                "filename": "release-app-1.0.0.tar.gz",
                "size": 64,
                "sha256": "b" * 64,
            },
        ],
    }
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    marker = tmp_path / "release action"
    environment = dict(os.environ, APP_MARKER=str(marker))
    subprocess.run(
        [sys.executable, str(script_path)], env=environment, check=True
    )
    assert marker.read_text(encoding="utf-8") == "ran"
    manifest["version"] = "2.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    marker.unlink()
    result = subprocess.run(
        [sys.executable, str(script_path)], env=environment, check=False
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_release_frontend_validates_identity_and_assets_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apprc.distribution import _frontend

    config = _frontend.FrontendConfig(
        app_id="release-app",
        distribution="release-app",
        repository_url="https://github.com/example/release-app",
        distribution_path="src/release_app",
        project_path=".",
        payload_format="script",
        source_mode="release",
        version="1.0.0",
        commit="a" * 40,
    )
    content = {
        "main-installer.py": b"installer",
        "release-app-1.0.0.tar.gz": b"source archive",
        "release-app-1.0.0.whl": b"wheel",
    }
    manifest = {
        "schema_version": 1,
        "app_id": "release-app",
        "distribution": "release-app",
        "version": "1.0.0",
        "commit": "a" * 40,
        "payload_format": "script",
        "assets": [
            {
                "filename": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in content.items()
        ],
    }
    manifest_bytes = json.dumps(manifest).encode()
    asset_bytes = {**content, "release-manifest.json": manifest_bytes}
    release = {
        "draft": False,
        "tag_name": "v1.0.0",
        "assets": [
            {
                "name": name,
                "size": len(data),
                "browser_download_url": (
                    "https://github.com/example/release-app/releases/download/"
                    f"v1.0.0/{name}"
                ),
            }
            for name, data in asset_bytes.items()
        ],
    }
    reads: list[str] = []
    monkeypatch.setattr(
        _frontend,
        "_read_url",
        lambda address, *, client, limit=_frontend._METADATA_LIMIT: (
            reads.append(address) or json.dumps(release).encode()
        ),
    )

    def download(
        address: str, destination: Path, client: str, **kwargs: Any
    ) -> None:
        destination.write_bytes(asset_bytes[destination.name])

    monkeypatch.setattr(_frontend, "_download", download)
    executions: list[tuple[Path, list[str], list[str]]] = []
    monkeypatch.setattr(
        _frontend,
        "_execute",
        lambda payload, payload_format, transport, forwarded, **kwargs: (
            executions.append((payload, list(transport), list(forwarded))) or 9
        ),
    )
    assert (
        _frontend.run_installer(
            config, ("--version", "1.0.0", "--repair", "value")
        )
        == 9
    )
    assert reads == [
        "https://api.github.com/repos/example/release-app/releases/tags/v1.0.0"
    ]
    assert executions[0][2] == ["--repair", "value"]

    release["tag_name"] = "v2.0.0"
    assert _frontend.run_installer(config, ("--version", "1.0.0")) == 2
    assert len(executions) == 1
    release["tag_name"] = "v1.0.0"
    asset_bytes["release-app-1.0.0.tar.gz"] = b"changed source"
    assert _frontend.run_installer(config, ("--version", "1.0.0")) == 2
    assert len(executions) == 1


def test_release_gh_client_acquires_the_selected_hashed_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from apprc.distribution import _frontend

    package_name = "release-app-1.0.0.tar.gz"
    content = b"selected source archive"
    commands: list[list[str]] = []

    def run(
        command: list[str], *, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        assert check
        commands.append(command)
        directory = Path(command[command.index("--dir") + 1])
        name = command[command.index("--pattern") + 1]
        (directory / name).write_bytes(content)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(_frontend.subprocess, "run", run)
    directory = tmp_path / "gh-download"
    directory.mkdir(mode=0o700)
    package = directory / package_name
    _frontend._download(
        f"https://github.com/example/release-app/releases/download/v1.0.0/{package_name}",
        package,
        "gh",
        release=("example/release-app", "v1.0.0"),
    )
    expected = {
        "filename": package_name,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    _frontend._verify(package, expected)
    assert package.read_bytes() == content
    assert commands[0][:7] == [
        "gh",
        "release",
        "download",
        "v1.0.0",
        "--repo",
        "example/release-app",
        "--dir",
    ]

    package.unlink()
    content = b"altered source archive"

    def bad_run(
        command: list[str], *, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        directory = Path(command[command.index("--dir") + 1])
        (directory / command[command.index("--pattern") + 1]).write_bytes(
            content
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(_frontend.subprocess, "run", bad_run)
    _frontend._download(
        f"https://github.com/example/release-app/releases/download/v1.0.0/{package_name}",
        package,
        "gh",
        release=("example/release-app", "v1.0.0"),
    )
    with pytest.raises(RuntimeError):
        _frontend._verify(package, expected)


def test_stdlib_final_worker_preserves_a_new_generation_record(
    tmp_path: Path,
) -> None:
    project = tmp_path / "finalizer-project"
    payload_root = project / "payload" / "finalizer_app"
    payload_root.mkdir(parents=True)
    for name in ("__init__.py", "install.py", "uninstall.py"):
        (payload_root / name).write_text(
            "def main():\n    return 0\n", encoding="utf-8"
        )
    payload = PayloadTree(
        project / "payload",
        tuple(
            PurePosixPath("finalizer_app") / name
            for name in (
                "__init__.py",
                "install.py",
                "uninstall.py",
            )
        ),
        entry_module="finalizer_app.install",
        uninstall_entry_module="finalizer_app.uninstall",
    )
    metadata = ProjectMetadata(
        project,
        InstallationIdentity(
            "finalizer-app",
            "finalizer-app",
            "finalizer_app",
            None,
            ("finalizer-app",),
        ),
        "1.0.0",
    )
    artifacts = generate_artifacts(DistributionSpec(metadata), payload)
    final_worker = tmp_path / "final-worker.py"
    final_worker.write_bytes(
        next(
            artifact.content
            for artifact in artifacts
            if artifact.destination.name == "final-worker.py"
        )
    )
    directory = tmp_path / "next-generation"
    directory.mkdir()
    authority = directory / "installation.json"
    authority.write_text("new generation authority\n", encoding="utf-8")
    recovery = tmp_path / "recovery"
    create_private_directory_if_missing(recovery)
    plan = recovery / "finalization.json"
    assert ensure_secret_file(plan).available
    plan.write_text(
        json.dumps({"directory": str(directory), "support": []}),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(final_worker),
            "--plan",
            str(plan),
            "--directory",
            str(directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert authority.read_text(encoding="utf-8") == "new generation authority\n"
    assert directory.is_dir()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Requires Linux process-bound uninstall handoff.",
)
def test_failed_provider_cleanup_retries_same_uninstall_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, install_plan, snapshot, environment = installation_scenario(
        tmp_path
    )
    backend = replace(snapshot.backend, executable=tmp_path / "fixture-uv")
    snapshot = replace(snapshot, backend=backend)
    install_plan = replace(
        install_plan, target=replace(install_plan.target, backend=backend)
    )
    _stub_backend(monkeypatch, snapshot)
    tool_marker = backend.tool_dir / ".fixture-installed"
    backend.tool_dir.mkdir(parents=True)
    tool_marker.write_text("installed\n", encoding="utf-8")
    backend.executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import sys\n"
        f"marker = Path({str(tool_marker)!r})\n"
        "if sys.argv[1:3] == ['tool', 'list']:\n"
        f"    print({snapshot.identity.distribution!r} + ' v1.0' if marker.exists() else '')\n"
        "elif sys.argv[1:3] == ['tool', 'uninstall']:\n"
        "    marker.unlink(missing_ok=True)\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    backend.executable.chmod(0o700)
    installed = install_support_fixture(
        install_plan,
        environment,
        {PurePosixPath("controller.py"): b"# saved controller\n"},
    )
    assert installed.status == "ready"
    initial = prepare_uninstall(directory)
    assert initial.plan is not None and initial.can_execute
    calls = 0

    def fail_once(_context) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider cleanup failed once")

    with pytest.raises(RuntimeError, match="failed once"):
        controllers.stage_uninstall(initial.plan, provider_cleanup=fail_once)

    failed = prepare_uninstall(directory)
    assert failed.plan is not None and failed.can_execute
    assert failed.plan.operation_id == initial.plan.operation_id
    assert failed.plan.inventory == initial.plan.inventory
    conflicting = prepare_uninstall(directory, complete=True)
    assert not conflicting.can_execute
    assert conflicting.plan is None
    with pytest.raises(
        InstallationError, match="different installation operation"
    ):
        controllers.stage_uninstall(
            replace(failed.plan, expected_generation=uuid4()),
            provider_cleanup=fail_once,
        )

    resumed = controllers.stage_uninstall(
        failed.plan, provider_cleanup=fail_once
    )
    persisted = inspect_installation(directory, app_id="fixture")
    assert calls == 2
    assert persisted.record is not None
    assert persisted.record.operation is not None
    assert persisted.record.operation.operation_id == initial.plan.operation_id
    assert OperationStep.PROVIDER_CLEANUP in persisted.record.operation.steps
    assert resumed.expected_revision == persisted.revision

    checkpointed = controllers.stage_uninstall(
        failed.plan,
        provider_cleanup=lambda _context: pytest.fail(
            "successful cleanup checkpoint was replayed"
        ),
    )
    assert checkpointed.expected_revision == persisted.revision

    from types import SimpleNamespace

    from apprc.distribution.runtime import removal
    from apprc.distribution.runtime.backend import inspect_uv_tools
    from tests.test_distribution_process_waiter import _owned_child

    with _owned_child() as original:
        safe_temp = tmp_path / "receiver-safe-temp"
        safe_temp.mkdir()
        process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO())
        with monkeypatch.context() as launch:
            launch.setattr(
                controllers.tempfile, "gettempdir", lambda: str(safe_temp)
            )
            launch.setattr(
                controllers,
                "external_base_python",
                lambda *_args, **_kwargs: Path(sys.executable),
            )
            launch.setattr(
                controllers.subprocess,
                "Popen",
                lambda *_args, **_kwargs: process,
            )
            handoff = controllers.start_uninstall_handoff(
                checkpointed,
                original_pid=original.pid,
                provider_cleanup=lambda _context: pytest.fail(
                    "successful cleanup checkpoint was replayed"
                ),
            )
        assert original.stdin is not None
        original.stdin.write("exit\n")
        original.stdin.flush()
        original.wait(timeout=5)
        monkeypatch.setattr(
            removal,
            "external_base_python",
            lambda *_args, **_kwargs: Path(sys.executable),
        )
        monkeypatch.setattr(removal.sys, "stdin", io.StringIO())
        removal.execute_handoff(handoff.plan_file)

    assert snapshot.identity.distribution not in inspect_uv_tools(
        backend, environment=environment
    )
    finished = inspect_installation(directory, app_id="fixture")
    assert finished.status == "removed-retained"
    assert finished.record is not None
    assert finished.record.current is None
    assert finished.record.operation is None
