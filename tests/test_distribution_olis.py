"""Test one-line install generation and the executed Linux OLIS contract."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

import apprc.distribution.frontends as frontends
from apprc.definition.installation import InstallationIdentity, ProjectSnapshot
from apprc.distribution.models import DistributionSpec, ProjectMetadata
from apprc.distribution.native import NativeArtifact, NativeTarget
from apprc.distribution.project import PreparedProject

_LINUX: NativeTarget = "x86_64-unknown-linux-gnu"
_REPOSITORY = "Example-Org/releases"
_LINUX_SETUP = "fixture-setup-linux-x86_64"
_OUTPUTS = ("install_from_github.sh", "install_from_github.ps1")


@pytest.mark.parametrize("public", ["true", "false", ""])
def test_configured_build_generates_both_olis_for_one_native_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public: str
) -> None:
    archive = tmp_path / "prepared.zip"
    archive.write_bytes(b"prepared project")
    source = ProjectSnapshot(
        hashlib.sha256(archive.read_bytes()).hexdigest(), "a" * 64, "b" * 40
    )
    job = PreparedProject(archive, source)
    uv = tmp_path / "uv"
    uv.touch()

    def compile_setup(
        *,
        target: NativeTarget,
        destination: Path,
        runtime_archive: Path,
        entrypoint: str,
    ) -> NativeArtifact:
        destination.parent.mkdir()
        destination.write_bytes(b"compiled setup fixture")
        return NativeArtifact(
            destination,
            target,
            destination.stat().st_size,
            hashlib.sha256(destination.read_bytes()).hexdigest(),
            destination,
        )

    class Compiler:
        def __init__(self, workspace: Path, *, environment: object) -> None:
            pass

        build = staticmethod(compile_setup)

    monkeypatch.setattr(frontends, "NativeFrontendBuilder", Compiler)
    monkeypatch.setattr(
        frontends, "_validate_prepared_project", lambda *args: None
    )
    monkeypatch.setattr(
        frontends, "_sdk_archive", lambda *args: b"embedded SDK fixture"
    )
    monkeypatch.setattr(
        frontends.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, "uv 99.0.0\n"
        ),
    )
    environment = {"RELEASE_REPOSITORY": _REPOSITORY, "RELEASE_PUBLIC": public}
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    dist = tmp_path / "dist"
    versions = []
    for version in ("1.0.0", "2.0.0"):
        spec = DistributionSpec(ProjectMetadata(tmp_path, identity, version))
        result = frontends.build_native_distribution(
            spec,
            job,
            uv=uv,
            workspace=tmp_path / version,
            targets=(_LINUX,),
            environment=environment,
        )
        assert [item.path.name for item in result.artifacts] == [_LINUX_SETUP]
        manifest = f"{result.artifacts[0].sha256}  {_LINUX_SETUP}\n".encode()
        assert (
            (dist / "SHA256SUMS").read_bytes()
            == manifest
            == result.checksums.content
        )
        assert (
            result.artifacts[0].path.read_bytes() == b"compiled setup fixture"
        )
        assert {p.name for p in dist.iterdir()} == {
            *_OUTPUTS,
            "SHA256SUMS",
            _LINUX_SETUP,
        }
        versions.append(tuple((dist / name).read_bytes() for name in _OUTPUTS))
    assert versions[0] == versions[1]
    linux, windows = (text.decode("utf-8") for text in versions[1])
    assert all(
        _REPOSITORY in text and "@@" not in text and "\r" not in text
        for text in (linux, windows)
    )
    assert (
        _LINUX_SETUP in linux and "fixture-setup-windows-x86_64.exe" in windows
    )
    assert "curl -fsSL <PUBLIC_SCRIPT_URL> | bash" in linux
    assert "irm <PUBLIC_SCRIPT_URL> | iex" in windows
    for text in (linux, windows):
        assert ("releases/latest/download" in text) == (public == "true")
        assert ("gh release download" in text) == (public != "true")


@pytest.mark.parametrize(
    ("settings", "fails_write"),
    [
        ({}, False),
        ({"RELEASE_REPOSITORY": "Example/../bad"}, False),
        ({"RELEASE_REPOSITORY": _REPOSITORY, "RELEASE_PUBLIC": "TRUE"}, False),
        ({"RELEASE_REPOSITORY": _REPOSITORY}, True),
    ],
)
def test_olis_problems_only_warn_and_leave_native_outputs_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    settings: dict[str, str],
    fails_write: bool,
) -> None:
    (tmp_path / _LINUX_SETUP).write_bytes(b"existing native setup")
    (tmp_path / "SHA256SUMS").write_bytes(b"existing manifest")
    for name in _OUTPUTS:
        (tmp_path / name).write_bytes(b"previous OLIS")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    if fails_write:

        def fail(*args: object, **kwargs: object) -> None:
            raise OSError("controlled OLIS write failure")

        monkeypatch.setattr(frontends, "_write_atomic", fail)

    frontends._write_olis(tmp_path, "fixture", settings)

    assert (
        "Native build succeeded. OLIS files may be missing or stale"
        in caplog.text
    )
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.skipif(
    platform.system() != "Linux"
    or platform.machine() != "x86_64"
    or not shutil.which("bash")
    or not shutil.which("sha256sum"),
    reason="Execute the Linux x86-64 OLIS with local Bash and sha256sum.",
)
@pytest.mark.parametrize("public", ["true", "false"])
@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        ("ok", 0),
        ("download", 42),
        ("bad-hash", 1),
        ("duplicate", 1),
        ("setup", 17),
        ("file-stdin", 0),
        ("piped-tty", 0),
        ("cleanup", 17),
    ],
)
def test_linux_olis_checks_before_running_and_cleans_up(
    tmp_path: Path, public: str, scenario: str, status: int
) -> None:
    if scenario == "piped-tty" and shutil.which("script") is None:
        pytest.skip(
            "The script utility supplies the controlling test terminal."
        )
    commands = tmp_path / "commands"
    commands.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    setup = downloads / _LINUX_SETUP
    setup.write_text(
        "#!/bin/sh\n"
        'case "$OLIS_SCENARIO" in\n'
        'file-stdin) read -r response; [ "$response" = supplied ] || exit 88 ;;\n'
        "piped-tty) [ -t 0 ] || exit 88 ;;\n"
        "esac\n"
        'touch "$OLIS_MARKER"\nexit "$OLIS_SETUP_STATUS"\n',
        encoding="utf-8",
    )
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    line = f"{'0' * 64 if scenario == 'bad-hash' else digest}  {_LINUX_SETUP}\n"
    (downloads / "SHA256SUMS").write_text(
        line * (2 if scenario == "duplicate" else 1)
    )
    (commands / "curl").write_text(
        '#!/bin/sh\n[ "$OLIS_SCENARIO" != download ] || exit 42\n'
        '[ "$2" = "https://github.com/$OLIS_REPOSITORY/releases/latest/download/${2##*/}" ] || exit 99\n'
        'cp "$OLIS_DOWNLOADS/${2##*/}" "$4"\n',
        encoding="utf-8",
    )
    (commands / "gh").write_text(
        '#!/bin/sh\n[ "$OLIS_SCENARIO" != download ] || exit 42\n'
        'case "$*" in *"$OLIS_REPOSITORY"*) ;; *) exit 99 ;; esac\n'
        'for last do :; done\ncp "$OLIS_DOWNLOADS/"* "$last/"\n',
        encoding="utf-8",
    )
    if scenario == "cleanup":
        (commands / "rm").write_text(
            '#!/bin/sh\n/bin/rm "$@"\nexit 64\n', encoding="utf-8"
        )
    for command in commands.iterdir():
        command.chmod(0o755)
    frontends._write_olis(
        tmp_path,
        "fixture",
        {"RELEASE_PUBLIC": public, "RELEASE_REPOSITORY": _REPOSITORY},
    )
    marker = tmp_path / "setup-ran"
    script = tmp_path / _OUTPUTS[0]
    command = ["bash"]
    script_input = script.read_bytes()
    if scenario == "file-stdin":
        command.append(str(script))
        script_input = b"supplied\n"
    elif scenario == "piped-tty":
        command = ["script", "-qec", 'cat "$OLIS_SCRIPT" | bash', "/dev/null"]
        script_input = b""
    result = subprocess.run(
        command,
        input=script_input,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(temporary),
            "OLIS_REPOSITORY": _REPOSITORY,
            "OLIS_DOWNLOADS": str(downloads),
            "OLIS_MARKER": str(marker),
            "OLIS_SCENARIO": scenario,
            "OLIS_SCRIPT": str(script),
            "OLIS_SETUP_STATUS": "17"
            if scenario in {"setup", "cleanup"}
            else "0",
        },
        check=False,
        timeout=10,
    )
    assert result.returncode == status, result.stderr
    assert marker.exists() == (
        scenario in {"ok", "setup", "file-stdin", "piped-tty", "cleanup"}
    )
    assert list(temporary.iterdir()) == []
