"""Maintained source identity, legacy receipt and artifact-composition scenarios."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.request import Request
from zipfile import ZipFile, ZipInfo

import pytest

from apprc.definition.installation import (
    InstallationIdentity,
    InstallationSource,
)
from apprc.distribution.models import (
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import (
    _environment,
    generate_artifacts,
    install_support_files,
    render_bootstraps,
)
from apprc.distribution.runtime.acquisition import (
    SourceSelection,
    _archive_inputs,
    installation_source,
    parse_source_arguments,
    prepare_source,
)
from apprc.distribution.runtime.legacy import inspect_legacy_receipt
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.env_files.secrets import ensure_secret_file


def _legacy_receipt(root: Path) -> Path:
    receipt = root / "receipt.json"
    root.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": 1,
        "distribution": "sample-app",
        "command": "sample-app",
        "version": "2.4.1",
        "source_ref": "release:2.4.1",
        "python": str(root / "base-python"),
        "uv": str(root / "uv"),
        "tool_dir": str(root / "tools"),
        "tool_bin_dir": str(root / "commands"),
        "appdata_supported": False,
        "uv_bootstrapped": True,
        "package_removed": False,
        "uv_binaries": [{"path": str(root / "uv"), "sha256": "a" * 64}],
    }
    receipt.write_text(
        json.dumps(value, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "uninstall.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return receipt


def test_legacy_receipt_rejects_unknown_identity_and_captures_exact_runnables(
    tmp_path: Path,
) -> None:
    receipt = _legacy_receipt(tmp_path / "legacy" / "installation")
    inspection = inspect_legacy_receipt(
        receipt, distribution="sample-app", command="sample-app"
    )

    assert inspection.compatible
    evidence = inspection.migration_evidence()
    assert evidence.receipt.path == receipt
    assert evidence.backend.tool_dir == receipt.parent / "tools"
    assert [
        (item.path.name, item.inert_path.name) for item in evidence.runnables
    ] == [
        ("uninstall.sh", ".retired-uninstall.sh"),
    ]
    assert (
        evidence.runnables[0].revision
        == hashlib.sha256(
            (receipt.parent / "uninstall.sh").read_bytes()
        ).hexdigest()
    )

    rejected = inspect_legacy_receipt(
        receipt, distribution="other-app", command="sample-app"
    )
    assert not rejected.compatible
    with pytest.raises(ValueError, match="cannot be migrated"):
        rejected.migration_evidence()


def test_legacy_receipt_unknown_fields_are_not_adopted(tmp_path: Path) -> None:
    receipt = _legacy_receipt(tmp_path / "legacy" / "installation")
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["layout"] = "native"
    receipt.write_text(json.dumps(value), encoding="utf-8")

    inspection = inspect_legacy_receipt(
        receipt, distribution="sample-app", command="sample-app"
    )

    assert not inspection.compatible
    assert inspection.diagnostics[0].code == "legacy-receipt-invalid"


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
    remote_artifacts = {
        item.destination: item.content for item in render_bootstraps(main_spec)
    }
    installer_directory = metadata.distribution_path / "artifacts" / "installer"
    assert (
        remote_artifacts[PurePosixPath("app-install.sh")]
        == remote_artifacts[installer_directory / "bootstrap.sh"]
    )
    assert remote_artifacts[PurePosixPath("app-install.cmd")]
    assert (
        remote_artifacts[PurePosixPath("bootstrap.ps1")]
        == remote_artifacts[installer_directory / "bootstrap.ps1"]
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


@pytest.mark.skipif(
    not Path("/bin/sh").is_file(), reason="POSIX shell is unavailable"
)
def test_rendered_shell_bootstrap_rejects_invalid_selectors_before_uv(
    tmp_path: Path,
) -> None:
    project = tmp_path / "checkout"
    metadata = ProjectMetadata(
        project,
        InstallationIdentity(
            "bootstrap-app",
            "bootstrap-app",
            "bootstrap_app",
            None,
            ("bootstrap-app",),
        ),
        "1.2.3",
    )
    spec = DistributionSpec(metadata)
    bootstrap_path = (
        metadata.distribution_path / "artifacts" / "installer" / "bootstrap.sh"
    )
    bootstrap = next(
        artifact.content
        for artifact in render_bootstraps(spec)
        if artifact.destination == bootstrap_path
    )
    script = tmp_path / "bootstrap.sh"
    script.write_bytes(bootstrap)
    environment = dict(os.environ)
    environment.pop("UV", None)

    missing_version = subprocess.run(
        ["/bin/sh", str(script), "--version"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert missing_version.returncode == 2
    assert "--version requires an exact X.Y.Z version" in missing_version.stderr

    obsolete_alias = subprocess.run(
        ["/bin/sh", str(script), "--main-ref", "main"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert obsolete_alias.returncode == 2
    assert "not a supported public selector" in obsolete_alias.stderr

    local_missing = subprocess.run(
        ["/bin/sh", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert local_missing.returncode == 2
    assert "just make-artifacts" in local_missing.stderr

    local_client = subprocess.run(
        ["/bin/sh", str(script), "--github-client", "gh"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert local_client.returncode == 2
    assert "just make-artifacts" in local_client.stderr


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


def test_remote_main_bootstrap_resolves_one_ref_and_transports_its_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_spec = DistributionSpec(
        ProjectMetadata(
            tmp_path,
            InstallationIdentity(
                "main-app", "main-app", "main_app", None, ("main-app",)
            ),
            "1.2.3",
            distribution_path=PurePosixPath("src/main café_distr"),
        ),
        source_mode="checkout",
        repository_url="https://github.com/example/main-app.git",
    )
    bootstrap_path = (
        source_spec.metadata.distribution_path
        / "artifacts"
        / "installer"
        / "bootstrap.sh"
    )
    bootstrap = next(
        artifact.content
        for artifact in render_bootstraps(source_spec)
        if artifact.destination == bootstrap_path
    )
    marker = b"""cat >"$FETCHER" <<'APPRC_MAIN_BOOTSTRAP'\n"""
    source = (
        bootstrap.split(marker, 1)[1]
        .split(b"\nAPPRC_MAIN_BOOTSTRAP", 1)[0]
        .decode("utf-8")
    )
    namespace: dict[str, Any] = {"__name__": "main_bootstrap_test"}
    exec(compile(source, "main_fetcher.py", "exec"), namespace)
    commit = "c" * 40
    api_url = "https://api.github.com/repos/example/main-app/commits/main"
    payload_url = (
        f"https://raw.githubusercontent.com/example/main-app/{commit}/"
        "src/main%20caf%C3%A9_distr/artifacts/installer/main-installer.py"
    )
    package_url = (
        f"https://api.github.com/repos/example/main-app/tarball/{commit}"
    )
    requests: list[str] = []

    class Response:
        def __init__(self, content: bytes) -> None:
            self.remaining = content

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int = -1) -> bytes:
            size = len(self.remaining) if limit < 0 else limit
            chunk, self.remaining = self.remaining[:size], self.remaining[size:]
            return chunk

    def urlopen(request: Request, timeout: float) -> Response:
        assert timeout == 60
        requests.append(request.full_url)
        if request.full_url == api_url:
            return Response(json.dumps({"sha": commit}).encode())
        if request.full_url == payload_url:
            return Response(b"installer payload from selected commit")
        if request.full_url == package_url:
            archive_bytes = BytesIO()
            with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
                content = (
                    "[build-system]\nrequires=['setuptools']\n"
                    "build-backend='setuptools.build_meta'\n"
                    "[project]\nname='main-app'\nversion='1.0.0'\n"
                ).encode()
                member = tarfile.TarInfo("main-app/pyproject.toml")
                member.size = len(content)
                archive.addfile(member, BytesIO(content))
            return Response(archive_bytes.getvalue())
        raise AssertionError(
            f"Unexpected remote-main request: {request.full_url}"
        )

    uv = tmp_path / "uv"
    uv.write_bytes(b"uv fixture")
    commands: list[tuple[list[str], dict[str, str]]] = []

    class Result:
        returncode = 0

    def run(command: list[str], *, env: dict[str, str], check: bool) -> Result:
        assert check is False
        commands.append((command, env))
        transport_start = command.index("--source-mode")
        selection, remaining = parse_source_arguments(
            source_spec, command[transport_start:]
        )
        assert selection.github_client is None
        assert remaining == ("--repair", "literal%20")
        prepared = selection.prepare(tmp_path / "prepared")
        assert prepared.source.requirement == (
            f"git+https://github.com/example/main-app.git@{commit}"
        )
        assert selection.package_path is not None
        package_path = selection.package_path
        assert (
            prepared.digest
            == hashlib.sha256(package_path.read_bytes()).hexdigest()
        )
        return Result()

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", urlopen)
    monkeypatch.setattr(namespace["subprocess"], "run", run)
    monkeypatch.setenv("APPRC_UV_PATH", str(uv))
    monkeypatch.setattr(
        namespace["sys"],
        "argv",
        ["main_fetcher.py", "--main", "--repair", "literal%20"],
    )
    assert namespace["main"]() == 0
    assert requests == [api_url, payload_url, package_url]
    command, environment = commands[-1]
    assert command[command.index("--source-mode") + 1] == "main"
    assert (
        command[command.index("--source-repository") + 1]
        == "https://github.com/example/main-app"
    )
    assert command[command.index("--source-commit") + 1] == commit
    assert command[command.index("--source-package") + 1].endswith(
        "source.tar.gz"
    )
    assert command[-2:] == ["--repair", "literal%20"]
    assert environment["APPRC_UV_PATH"] == str(uv)

    gh_commands: list[list[str]] = []

    def run_gh_api(command: list[str], *, check: bool, stdout: Any) -> Result:
        assert check
        gh_commands.append(command)
        stdout.write(b"authenticated installer payload")
        return Result()

    monkeypatch.setattr(namespace["subprocess"], "run", run_gh_api)
    authenticated_payload = tmp_path / "authenticated-main-installer.py"
    namespace["_download"](payload_url, authenticated_payload, "gh")
    assert (
        authenticated_payload.read_bytes() == b"authenticated installer payload"
    )
    assert gh_commands == [
        [
            "gh",
            "api",
            "repos/example/main-app/contents/src/main%20caf%C3%A9_distr/artifacts/installer/main-installer.py?ref="
            + commit,
            "-H",
            "Accept: application/vnd.github.raw",
        ]
    ]


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
    assert str(project).encode() not in script
    artifacts = generate_artifacts(spec, payload)
    destinations = {str(item.destination) for item in artifacts}
    assert {
        "bootstrap.ps1",
        "app-install.sh",
        "app-install.cmd",
    } <= destinations
    app_shell = next(
        item.content
        for item in artifacts
        if item.destination == PurePosixPath("app-install.sh")
    )
    assert b"main-installer.py" in app_shell
    assert str(project).encode() not in app_shell


def test_release_bootstrap_selects_one_tag_and_rejects_manifest_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = (
        _environment()
        .get_template("release_fetcher.py.jinja")
        .render(
            app_id="release-app",
            distribution="release-app",
            repository_url="https://github.com/example/release-app",
            release_version="latest",
        )
    )
    namespace: dict[str, Any] = {"__name__": "release_bootstrap_test"}
    exec(compile(source, "release_fetcher.py", "exec"), namespace)
    selected = namespace["_select_release"]
    assert callable(selected)

    class Response:
        def __init__(self, content: bytes) -> None:
            self.remaining = content

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int = -1) -> bytes:
            size = len(self.remaining) if limit < 0 else limit
            chunk, self.remaining = self.remaining[:size], self.remaining[size:]
            return chunk

    requests: list[str] = []
    latest_body = json.dumps({"draft": False, "tag_name": "v2.4.0"}).encode()

    def latest_urlopen(request: Request, timeout: float) -> Response:
        assert timeout == 60
        requests.append(request.full_url)
        return Response(latest_body)

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", latest_urlopen)
    assert selected(
        "https://api.github.com/repos/example/release-app", "latest"
    ) == {
        "draft": False,
        "tag_name": "v2.4.0",
    }
    assert requests == [
        "https://api.github.com/repos/example/release-app/releases/latest"
    ]

    requests.clear()
    exact_body = json.dumps({"draft": False, "tag_name": "v1.0.0"}).encode()

    def exact_urlopen(request: Request, timeout: float) -> Response:
        assert timeout == 60
        requests.append(request.full_url)
        return Response(exact_body)

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", exact_urlopen)
    assert selected(
        "https://api.github.com/repos/example/release-app", "1.0.0"
    ) == {
        "draft": False,
        "tag_name": "v1.0.0",
    }
    assert requests == [
        "https://api.github.com/repos/example/release-app/releases/tags/v1.0.0",
    ]

    monkeypatch.setattr(
        namespace["sys"],
        "argv",
        ["release_fetcher.py", "--version", "1.0.0", "--repair"],
    )
    assert namespace["_arguments"]() == (
        "1.0.0",
        "public",
        ["--repair"],
    )
    monkeypatch.setattr(
        namespace["sys"],
        "argv",
        ["release_fetcher.py", "--version", "latest"],
    )
    with pytest.raises(RuntimeError, match="exact X.Y.Z"):
        namespace["_arguments"]()
    monkeypatch.setattr(
        namespace["sys"], "argv", ["release_fetcher.py", "--version"]
    )
    with pytest.raises(RuntimeError, match="exact X.Y.Z"):
        namespace["_arguments"]()
    with pytest.raises(RuntimeError, match="Duplicate JSON"):
        namespace["_json_loads"](b'{"version":"1.0.0","version":"2.0.0"}')

    contents = {
        "main-installer.py": b"payload",
        "release-app-1.0.0.tar.gz": b"sdist",
        "release-app-1.0.0.whl": b"wheel",
    }
    manifest_assets = [
        {
            "filename": name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for name, content in contents.items()
    ]
    release_assets = {
        name: {
            "size": len(content),
            "browser_download_url": (
                f"https://github.com/example/release-app/releases/download/v1.0.0/{name}"
            ),
        }
        for name, content in contents.items()
    }
    release_assets["release-manifest.json"] = {
        "size": 12,
        "browser_download_url": (
            "https://github.com/example/release-app/releases/download/v1.0.0/release-manifest.json"
        ),
    }
    manifest = {
        "schema_version": 1,
        "app_id": "release-app",
        "distribution": "release-app",
        "version": "1.0.0",
        "commit": "a" * 40,
        "payload_format": "script",
        "assets": manifest_assets,
    }
    validate_manifest = namespace["_validate_manifest"]
    assert (
        validate_manifest(manifest, release_assets, "latest")[0]
        == "main-installer.py"
    )
    with pytest.raises(RuntimeError, match="identity"):
        validate_manifest(
            {**manifest, "app_id": "other-app"}, release_assets, "latest"
        )
    with pytest.raises(RuntimeError, match="version"):
        validate_manifest(manifest, release_assets, "2.0.0")
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    release_assets["release-manifest.json"]["size"] = len(manifest_bytes)
    downloads = {**contents, "release-manifest.json": manifest_bytes}
    release_body = json.dumps(
        {
            "draft": False,
            "tag_name": "v1.0.0",
            "assets": [
                {
                    "name": name,
                    "size": len(content),
                    "browser_download_url": release_assets[name][
                        "browser_download_url"
                    ],
                }
                for name, content in downloads.items()
            ],
        }
    ).encode()
    route_requests: list[str] = []

    def route_urlopen(request: Request, timeout: float) -> Response:
        assert timeout == 60
        route_requests.append(request.full_url)
        if request.full_url.endswith("/releases/latest"):
            return Response(release_body)
        name = request.full_url.rsplit("/", 1)[1]
        return Response(downloads[name])

    uv = tmp_path / "uv"
    uv.write_bytes(b"uv fixture")
    executed: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> Result:
        executed.append(command)
        return Result()

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", route_urlopen)
    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    monkeypatch.setattr(
        namespace["sys"],
        "argv",
        [
            "release_fetcher.py",
            "--dry-run",
            "custom arg",
        ],
    )
    monkeypatch.setenv("APPRC_UV_PATH", str(uv))
    assert namespace["main"]() == 0
    assert (
        len([url for url in route_requests if url.endswith("/releases/latest")])
        == 1
    )
    assert executed[0][0] == str(uv)
    assert executed[0][-2:] == ["--dry-run", "custom arg"]
    package_url = release_assets["release-app-1.0.0.tar.gz"][
        "browser_download_url"
    ]
    assert package_url in route_requests
    assert executed[0][executed[0].index("--source-package") + 1].endswith(
        "release-app-1.0.0.tar.gz"
    )
    assert "--script" in executed[0]
    downloads["main-installer.py"] = contents["main-installer.py"]
    downloads["release-app-1.0.0.tar.gz"] = b"incorrect package bytes"
    assert namespace["main"]() == 2
    assert len(executed) == 1

    downloads["main-installer.py"] = b"PAYLOAD"
    downloads["release-app-1.0.0.tar.gz"] = contents["release-app-1.0.0.tar.gz"]
    assert namespace["main"]() == 2
    assert len(executed) == 1


def test_release_gh_client_acquires_the_selected_hashed_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = (
        _environment()
        .get_template("release_fetcher.py.jinja")
        .render(
            app_id="release-app",
            distribution="release-app",
            repository_url="https://github.com/example/release-app",
            release_version="1.0.0",
        )
    )
    namespace: dict[str, Any] = {"__name__": "release_gh_test"}
    exec(compile(source, "release_fetcher.py", "exec"), namespace)
    package_name = "release-app-1.0.0.tar.gz"
    pyproject = (
        "[build-system]\n"
        'requires = ["setuptools>=80"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "[project]\nname = 'release-app'\nversion = '1.0.0'\n"
    ).encode()
    metadata = b"Metadata-Version: 2.1\nName: release-app\nVersion: 1.0.0\n"
    package_buffer = BytesIO()
    with tarfile.open(fileobj=package_buffer, mode="w:gz") as archive:
        for relative, content in {
            "pyproject.toml": pyproject,
            "PKG-INFO": metadata,
            "release_app.egg-info/PKG-INFO": metadata,
            "release_app.egg-info/SOURCES.txt": b"pyproject.toml\n",
        }.items():
            member = tarfile.TarInfo(f"release-app-1.0.0/{relative}")
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    package_bytes = package_buffer.getvalue()
    asset_url = (
        "https://github.com/example/release-app/releases/download/"
        f"v1.0.0/{package_name}"
    )
    assets = {
        package_name: {
            "size": len(package_bytes),
            "sha256": hashlib.sha256(package_bytes).hexdigest(),
            "filename": package_name,
        }
    }
    release_assets = {
        package_name: {
            "size": len(package_bytes),
            "browser_download_url": asset_url,
        }
    }
    commands: list[list[str]] = []
    content = package_bytes

    class Result:
        returncode = 0

    def run(command: list[str], *, check: bool) -> Result:
        assert check
        commands.append(command)
        directory = Path(command[command.index("--dir") + 1])
        name = command[command.index("--pattern") + 1]
        (directory / name).write_bytes(content)
        return Result()

    monkeypatch.setattr(namespace["subprocess"], "run", run)
    namespace["GITHUB_CLIENT"] = "gh"
    namespace["RELEASE_TAG"] = "v1.0.0"
    download_directory = tmp_path / "gh-download"
    download_directory.mkdir(mode=0o700)
    package = download_directory / package_name
    namespace["_download_asset"](package_name, release_assets, assets, package)
    assert package.read_bytes() == package_bytes
    assert commands[0][:5] == ["gh", "release", "download", "v1.0.0", "--repo"]

    release_spec = DistributionSpec(
        ProjectMetadata(
            tmp_path,
            InstallationIdentity(
                "release-app",
                "release-app",
                "release_app",
                None,
                ("release-app",),
            ),
            "1.0.0",
        ),
        source_mode="release",
        repository_url="https://github.com/example/release-app",
        release_version="1.0.0",
        release_commit="a" * 40,
        release_asset=asset_url,
        release_digest=hashlib.sha256(package_bytes).hexdigest(),
        runtime_requirements=("apprc-core==0.31.0",),
    )
    selection, remaining = parse_source_arguments(
        release_spec,
        ("--source-package", str(package), "--github-client", "gh", "--repair"),
    )
    assert remaining == ("--repair",)
    prepared = selection.prepare(tmp_path / "prepared-release")
    assert prepared.source == selection.source
    assert prepared.source.requirement == asset_url
    assert prepared.project_directory == Path(prepared.requirement)
    assert (
        Path(prepared.requirement) / "pyproject.toml"
    ).read_bytes() == pyproject
    assert prepared.constraints is not None
    assert (
        prepared.constraints.read_text(encoding="utf-8")
        == "apprc-core==0.31.0\n"
    )

    package.unlink()
    content = b"modified package bytes"
    with pytest.raises(RuntimeError, match="differs from its manifest"):
        namespace["_download_asset"](
            package_name, release_assets, assets, package
        )
    assert not package.exists()


def test_default_generated_composition_is_complete_and_author_root_independent(
    tmp_path: Path,
) -> None:
    project = tmp_path / "application"
    package = project / "payload" / "app_lifecycle"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '"""Fixture composition."""\n', encoding="utf-8"
    )
    (package / "install.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    (package / "uninstall.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    payload = PayloadTree(
        project / "payload",
        tuple(
            PurePosixPath("app_lifecycle") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
    )
    metadata = ProjectMetadata(
        project,
        InstallationIdentity(
            "fixture-app", "fixture-app", "fixture", None, ("fixture",)
        ),
        "1.0.0",
        distribution_path=PurePosixPath("src/fixture_distr"),
        launcher_command="fixture",
    )
    spec = DistributionSpec(metadata)

    artifacts = generate_artifacts(spec, payload)
    relocated = generate_artifacts(
        replace(
            spec,
            metadata=replace(
                metadata, project_root=tmp_path / "other author root"
            ),
        ),
        payload,
    )
    support_files = install_support_files(spec, payload)
    assert {
        PurePosixPath(name)
        for name in (
            "repair-installer.py",
            "app-uninstall.py",
            "controller.py",
            "inspection.py",
            "final-worker.py",
            "uninstall.py",
            "launcher.py",
            "launch-command.json",
            "launch.sh",
            "launch.ps1",
            "launch.cmd",
            "uninstall.sh",
            "uninstall.ps1",
            "uninstall.cmd",
        )
    } <= set(support_files)
    observed = {str(item.destination) for item in artifacts}
    assert {
        "app-install.sh",
        "app-install.cmd",
        "app-launch.sh",
        "app-launch.cmd",
        "app-uninstall.sh",
        "app-uninstall.cmd",
        "src/fixture_distr/artifacts/installer/main-installer.py",
        "src/fixture_distr/artifacts/installer/bootstrap.sh",
        "src/fixture_distr/artifacts/installer/bootstrap.ps1",
        "src/fixture_distr/artifacts/installer/repair-installer.py",
        "src/fixture_distr/artifacts/installer/app-uninstall.py",
        "src/fixture_distr/artifacts/uninstaller/controller.py",
        "src/fixture_distr/artifacts/uninstaller/inspection.py",
        "src/fixture_distr/artifacts/uninstaller/final-worker.py",
        "src/fixture_distr/artifacts/uninstaller/uninstall.py",
        "src/fixture_distr/artifacts/launcher/launcher.py",
        "src/fixture_distr/artifacts/launcher/launch-command.json",
        "src/fixture_distr/artifacts/launcher/launch.sh",
        "src/fixture_distr/artifacts/launcher/launch.ps1",
        "src/fixture_distr/artifacts/launcher/launch.cmd",
        "src/fixture_distr/artifacts/uninstaller/uninstall.sh",
        "src/fixture_distr/artifacts/uninstaller/uninstall.ps1",
        "src/fixture_distr/artifacts/uninstaller/uninstall.cmd",
    }.issubset(observed)
    assert [(item.destination, item.content) for item in artifacts] == [
        (item.destination, item.content) for item in relocated
    ]


def test_no_app_stack_script_and_zipapp_share_exact_standalone_payload(
    tmp_path: Path,
) -> None:
    from apprc.distribution.standalone import payload_archive

    project = tmp_path / "plain-project"
    package = project / "payload" / "plain_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '"""Standalone application."""\n', encoding="utf-8"
    )
    install_source = "def main():\n    return 0\n"
    uninstall_source = "def main():\n    return 0\n"
    (package / "install.py").write_text(install_source, encoding="utf-8")
    (package / "uninstall.py").write_text(uninstall_source, encoding="utf-8")
    payload = PayloadTree(
        project / "payload",
        tuple(
            PurePosixPath("plain_app") / name
            for name in ("__init__.py", "install.py", "uninstall.py")
        ),
        entry_module="plain_app.install",
        uninstall_entry_module="plain_app.uninstall",
    )
    metadata = ProjectMetadata(
        project,
        InstallationIdentity(
            "plain-app", "plain-app", "plain_app", None, ("plain-app",)
        ),
        "1.0.0",
    )
    script_spec = DistributionSpec(metadata)
    script_artifacts = generate_artifacts(script_spec, payload)
    script = next(
        artifact.content
        for artifact in script_artifacts
        if artifact.destination.name == "main-installer.py"
    )
    assert script.startswith(b"#!/usr/bin/env -S uv run --script\n")
    assert b"platformdirs==4.10.0" in script
    assert b"filelock==3.32.7" in script

    zipapp_spec = replace(script_spec, payload_format="zipapp")
    zipapp_artifacts = generate_artifacts(zipapp_spec, payload)
    zipapp = next(
        artifact.content
        for artifact in zipapp_artifacts
        if artifact.destination.name == "main-installer.pyz"
    )
    with ZipFile(BytesIO(zipapp)) as archive:
        assert archive.namelist() == ["__main__.py"]
        assert archive.read("__main__.py") == script
    with ZipFile(BytesIO(payload_archive(script_spec, payload))) as archive:
        assert (
            archive.read("plain_app/install.py").decode("utf-8")
            == install_source
        )
        assert (
            archive.read("plain_app/uninstall.py").decode("utf-8")
            == uninstall_source
        )

    repeated = generate_artifacts(zipapp_spec, payload)
    repeated_zipapp = next(
        artifact.content
        for artifact in repeated
        if artifact.destination.name == "main-installer.pyz"
    )
    assert repeated_zipapp == zipapp


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
