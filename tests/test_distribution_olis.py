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
    environment = {"RELEASE_REPO_OLIS": _REPOSITORY, "RELEASE_PUBLIC": public}
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
        ({"RELEASE_REPO_OLIS": "Example/../bad"}, False),
        ({"RELEASE_REPO_OLIS": _REPOSITORY, "RELEASE_PUBLIC": "TRUE"}, False),
        ({"RELEASE_REPO_OLIS": _REPOSITORY}, True),
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

    assert "Existing OLIS files may be stale" in caplog.text
    assert ("OLIS generation failed" in caplog.text) == bool(settings)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_unconfigured_build_with_no_olis_does_not_warn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    frontends._write_olis(
        tmp_path, "fixture", {"RELEASE_REPOSITORY": _REPOSITORY}
    )

    assert not caplog.records
    assert not list(tmp_path.iterdir())


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
        'printf "%s\\n" "$@" > "$OLIS_MARKER"\nexit "$OLIS_SETUP_STATUS"\n',
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
        {"RELEASE_PUBLIC": public, "RELEASE_REPO_OLIS": _REPOSITORY},
    )
    marker = tmp_path / "setup-ran"
    script = tmp_path / _OUTPUTS[0]
    command = ["bash"]
    script_input = script.read_bytes()
    if scenario == "file-stdin":
        command.append(str(script))
        script_input = b"supplied\n"
    elif scenario == "piped-tty":
        command = [
            "script",
            "-qec",
            'cat "$OLIS_SCRIPT" | bash -s -- --smoke "a space"',
            "/dev/null",
        ]
        script_input = b""
    else:
        command.extend(("-s", "--"))
    if scenario != "piped-tty":
        command.extend(("--smoke", "a space"))
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
    if marker.exists():
        assert marker.read_text().splitlines() == ["--smoke", "a space"]
    assert list(temporary.iterdir()) == []


@pytest.mark.skipif(
    platform.system() != "Linux" or shutil.which("pwsh") is None,
    reason="A Linux PowerShell host is needed to run the rendered Windows wrapper with mock downloads.",
)
@pytest.mark.parametrize("public", ["true", "false"])
@pytest.mark.parametrize(
    ("valid_checksum", "expected"), [(True, 17), (False, 1)]
)
def test_powershell_olis_forwards_options_after_checksum(
    tmp_path: Path, public: str, valid_checksum: bool, expected: int
) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    setup = downloads / "fixture-setup-windows-x86_64.exe"
    setup.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$OLIS_MARKER"\nexit 17\n'
    )
    setup.chmod(0o755)
    digest = (
        hashlib.sha256(setup.read_bytes()).hexdigest()
        if valid_checksum
        else "0" * 64
    )
    (downloads / "SHA256SUMS").write_text(f"{digest}  {setup.name}\n")
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    gh = mock_bin / "gh"
    gh.write_text(
        '#!/bin/sh\nfor last do :; done\ncp -p "$OLIS_DOWNLOADS/"* "$last/"\n'
    )
    gh.chmod(0o755)
    driver = tmp_path / "invoke.ps1"
    driver.write_text(
        "function global:Invoke-WebRequest {\n"
        "    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile)\n"
        "    $name = ([Uri]$Uri).Segments[-1]\n"
        "    [IO.File]::Copy((Join-Path $env:OLIS_DOWNLOADS $name), $OutFile)\n"
        '    if ($name.EndsWith(".exe")) { chmod +x $OutFile }\n'
        "}\n"
        '& $env:OLIS_SCRIPT --smoke "a space"\n'
        "exit $LASTEXITCODE\n"
    )
    frontends._write_olis(
        tmp_path,
        "fixture",
        {"RELEASE_PUBLIC": public, "RELEASE_REPO_OLIS": _REPOSITORY},
    )
    marker = tmp_path / "marker"
    output = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(driver)],
        env={
            **os.environ,
            "OS": "Windows_NT",
            "PROCESSOR_ARCHITECTURE": "AMD64",
            "PATH": str(mock_bin) + os.pathsep + os.environ["PATH"],
            "OLIS_DOWNLOADS": str(downloads),
            "OLIS_MARKER": str(marker),
            "OLIS_SCRIPT": str(tmp_path / _OUTPUTS[1]),
        },
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert output.returncode == expected, output.stderr
    if valid_checksum:
        assert marker.read_text().splitlines() == ["--smoke", "a space"]
    else:
        assert not marker.exists()


@pytest.mark.skipif(
    platform.system() != "Linux", reason="Uses local mock executables."
)
@pytest.mark.parametrize("shell", ["bash", "pwsh"])
@pytest.mark.parametrize(
    ("scenario", "installer_args", "expected_tag", "error"),
    [
        ("ok", (), "", ""),
        ("ok", ("-b",), "v0.24.0b10", ""),
        ("ok", ("--beta",), "v0.24.0b10", ""),
        ("ok", ("-rc",), "v0.23.1rc10", ""),
        ("ok", ("--release-candidate",), "v0.23.1rc10", ""),
        ("ok", ("--", "--beta"), "", ""),
        ("empty", ("--beta",), None, "No published prerelease"),
        ("lookup", ("--beta",), None, "GitHub release lookup failed"),
        (
            "ok",
            ("--regular", "--beta"),
            None,
            "cannot be combined with --regular",
        ),
        ("ok", ("--beta", "-rc"), None, "Choose one release channel"),
        ("download", ("--beta",), "v0.24.0b10", ""),
        ("bad-hash", ("--beta",), "v0.24.0b10", "checksum verification failed"),
    ],
)
def test_private_olis_selects_release_before_downloading(
    tmp_path: Path,
    shell: str,
    scenario: str,
    installer_args: tuple[str, ...],
    expected_tag: str | None,
    error: str,
) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} is needed to exercise the rendered installer.")

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    setup_name = (
        _LINUX_SETUP if shell == "bash" else "fixture-setup-windows-x86_64.exe"
    )
    setup = downloads / setup_name
    setup.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$OLIS_MARKER"\n')
    setup.chmod(0o755)
    digest = (
        "0" * 64
        if scenario == "bad-hash"
        else hashlib.sha256(setup.read_bytes()).hexdigest()
    )
    (downloads / "SHA256SUMS").write_text(f"{digest}  {setup_name}\n")

    release_rows = tmp_path / "release-rows"
    release_rows.write_text(
        "v0.23.1rc10\ttrue\tfalse\nv0.23.1rc99\ttrue\ttrue\n"
        if scenario == "empty"
        else (
            "v0.24.0b2\ttrue\tfalse\n"
            "v0.24.0b99\ttrue\ttrue\n"
            "v0.23.1rc10\ttrue\tfalse\n"
            "v0.24.0b100\tfalse\tfalse\n"
            "v0.23.1rc2\ttrue\tfalse\n"
            "v0.24.1b1-extra\ttrue\tfalse\n"
            "v0.24.0b10\ttrue\tfalse\n"
            "v0.9.0b99\ttrue\tfalse\n"
        )
    )
    commands = tmp_path / "commands"
    commands.mkdir()
    gh = commands / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        '  "api --paginate")\n'
        '    [ "$3" = "repos/$OLIS_REPOSITORY/releases?per_page=100" ] || exit 98\n'
        '    printf "queried\\n" > "$OLIS_QUERY_LOG"\n'
        '    cat "$OLIS_RELEASE_ROWS"\n'
        '    [ "$OLIS_SCENARIO" != lookup ] ;;\n'
        '  "release download")\n'
        "    shift 2\n"
        '    printf "%s\\n" "$@" > "$OLIS_DOWNLOAD_LOG"\n'
        '    [ "$OLIS_SCENARIO" != download ] || exit 42\n'
        "    for last do :; done\n"
        '    cp -p "$OLIS_DOWNLOADS/"* "$last/" ;;\n'
        "  *) exit 99 ;;\n"
        "esac\n"
    )
    gh.chmod(0o755)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    temporary_link = tmp_path / "temporary-link"
    temporary_link.symlink_to(temporary, target_is_directory=True)
    temporary_parent = (
        temporary_link if installer_args == ("--beta",) else temporary
    )
    frontends._write_olis(
        tmp_path, "fixture", {"RELEASE_REPO_OLIS": _REPOSITORY}
    )
    marker, query_log, download_log = (
        tmp_path / name for name in ("marker", "query-log", "download-log")
    )
    args = ["--smoke", "a space", *installer_args]
    script_input = None
    if shell == "bash":
        script = tmp_path / _OUTPUTS[0]
        script_input = script.read_bytes()
        command = [shell, "-s", "--", *args]
    else:
        script = tmp_path / _OUTPUTS[1]
        driver = tmp_path / "invoke.ps1"
        driver.write_text(
            "try { & ([scriptblock]::Create((Get-Content -Raw $env:OLIS_SCRIPT))) @args }\n"
            "catch { [Console]::Error.WriteLine($_.Exception.Message) }\n"
            "exit $LASTEXITCODE\n"
        )
        command = [shell, "-NoProfile", "-File", str(driver), *args]

    result = subprocess.run(
        command,
        input=script_input,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(temporary_parent),
            "OS": "Windows_NT",
            "PROCESSOR_ARCHITECTURE": "AMD64",
            "OLIS_REPOSITORY": _REPOSITORY,
            "OLIS_DOWNLOADS": str(downloads),
            "OLIS_MARKER": str(marker),
            "OLIS_SCENARIO": scenario,
            "OLIS_SCRIPT": str(script),
            "OLIS_RELEASE_ROWS": str(release_rows),
            "OLIS_QUERY_LOG": str(query_log),
            "OLIS_DOWNLOAD_LOG": str(download_log),
        },
        check=False,
        timeout=20,
    )
    success = scenario == "ok" and expected_tag is not None
    assert (result.returncode == 0) == success, result.stderr
    if error:
        assert error.encode() in result.stderr
    assert query_log.exists() == (
        expected_tag not in (None, "") or scenario in {"empty", "lookup"}
    )
    assert download_log.exists() == (expected_tag is not None)
    if expected_tag is not None:
        downloaded = download_log.read_text().splitlines()
        assert downloaded[:-1] == [
            *([expected_tag] if expected_tag else []),
            "-R",
            _REPOSITORY,
            "-p",
            setup_name,
            "-p",
            "SHA256SUMS",
            "-D",
        ]
        assert not Path(downloaded[-1]).exists()
    assert marker.exists() == success
    if success:
        expected_args = ["--preview", *args[:2]] if expected_tag else args
        assert marker.read_text().splitlines() == expected_args
    assert not list(temporary.iterdir())
