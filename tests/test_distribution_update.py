"""Update selection, Git safety, and release verification."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from packaging.version import Version

from apprc import AppRC
from apprc.definition.installation import EditableCheckout, OwnedOutput
from apprc.distribution import _release_assets
from apprc.distribution.models import (
    AppCapabilities,
    GitHubReleaseSource,
    NativeBinding,
)
from apprc.distribution.runtime import update
from apprc.distribution.runtime._update_handoff import (
    EditableUpdateRetryError,
    UpdateWork,
)
from apprc.distribution.runtime.installation import require_update_record
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from tests.support_installation import installation_record, managed_installation


@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("release_tag", [None, "preview/v2.0rc1"])
def test_release_download_uses_one_tag_and_checks_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
    release_tag: str | None,
) -> None:
    repository = "author/app"
    slug = "preview%2Fv2.0rc1" if release_tag else "v2.0"
    lookup = f"tags/{slug}" if release_tag else "latest"
    base = f"https://github.com/{repository}/releases/download/{slug}"
    setup = "app-setup-linux-x86_64"
    artifact = b"candidate executable"
    digest = hashlib.sha256(artifact if valid else b"different").hexdigest()
    responses = {
        f"https://api.github.com/repos/{repository}/releases/{lookup}": json.dumps(
            {
                "tag_name": release_tag or "v2.0",
                "draft": False,
                "prerelease": release_tag is not None,
            }
        ).encode(),
        f"{base}/{setup}": artifact,
        f"{base}/SHA256SUMS": f"{digest}  {setup}\n".encode(),
    }
    monkeypatch.setattr(
        _release_assets,
        "urlopen",
        lambda request, **_kwargs: BytesIO(responses.pop(request.full_url)),
    )

    def download() -> _release_assets.DownloadedReleaseSetup:
        return _release_assets.download_release_setup(
            GitHubReleaseSource(repository, True),
            app_id="app",
            target="x86_64-unknown-linux-gnu",
            directory=tmp_path,
            environment={},
            release_tag=release_tag,
        )

    if valid:
        result = download()
        assert result.path.read_bytes() == artifact
        assert result.digest == digest
        assert result.tag == (release_tag or "v2.0")
    else:
        with pytest.raises(ValueError, match="release checksum"):
            download()
    assert responses == {}


@pytest.mark.parametrize(
    ("release_tag", "metadata"),
    [
        ("v2.0rc1", None),
        ("v2.0rc1", {"tag_name": "v2.0rc1", "draft": True, "prerelease": True}),
        (
            "v2.0rc1",
            {"tag_name": "V2.0rc1", "draft": False, "prerelease": True},
        ),
        (
            "v2.0rc1",
            {"tag_name": "v2.0rc1", "draft": False, "prerelease": "yes"},
        ),
        ("v2.0rc1", {"draft": False, "prerelease": True}),
        (None, {"tag_name": "v2.0rc1", "draft": False, "prerelease": True}),
    ],
)
def test_public_release_requires_matching_published_metadata_before_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_tag: str | None,
    metadata: dict[str, object] | None,
) -> None:
    requests: list[str] = []

    def open_release(request: Request, **_kwargs: object) -> BytesIO:
        requests.append(request.full_url)
        if metadata is None:
            raise URLError("release not found")
        return BytesIO(json.dumps(metadata).encode())

    monkeypatch.setattr(_release_assets, "urlopen", open_release)
    repository = "author/app"

    with pytest.raises(ValueError, match=repository) as failure:
        _release_assets.download_release_setup(
            GitHubReleaseSource(repository, True),
            app_id="app",
            target="x86_64-unknown-linux-gnu",
            directory=tmp_path,
            environment={},
            release_tag=release_tag,
        )

    lookup = f"tags/{release_tag}" if release_tag is not None else "latest"
    assert requests == [
        f"https://api.github.com/repos/{repository}/releases/{lookup}"
    ]
    if release_tag is not None:
        assert release_tag in str(failure.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("release_tag", ["", " \t", ".", ".."])
def test_release_download_rejects_invalid_explicit_tag_before_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, release_tag: str
) -> None:
    monkeypatch.setattr(
        _release_assets,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("unexpected release request"),
    )
    with pytest.raises(ValueError, match="--release requires"):
        _release_assets.download_release_setup(
            GitHubReleaseSource("author/app", True),
            app_id="app",
            target="x86_64-unknown-linux-gnu",
            directory=tmp_path,
            environment={},
            release_tag=release_tag,
        )


@pytest.mark.parametrize(
    ("release_tag", "outcome"),
    [
        (None, "published"),
        ("-v2.0rc1", "published"),
        ("-v2.0rc1", "draft"),
        ("-v2.0rc1", "missing"),
        ("-v2.0rc1", "forbidden"),
        ("-v2.0rc1", "missing-setup"),
        ("-v2.0rc1", "missing-manifest"),
    ],
)
def test_private_release_download_uses_exact_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_tag: str | None,
    outcome: str,
) -> None:
    repository = "author/private-app"
    tag = release_tag or "v2.0"
    environment = {"PATH": "fixture"}
    setup = tmp_path / "app-setup-windows-x86_64.exe"
    manifest = tmp_path / "SHA256SUMS"
    artifact = b"candidate executable"
    digest = hashlib.sha256(artifact).hexdigest()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _release_assets.shutil, "which", lambda *_a, **_kw: "gh"
    )

    def run(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        assert kwargs["env"] == environment
        if args[1] == "api":
            status = {"missing": 404, "forbidden": 403}.get(outcome, 200)
            body = json.dumps(
                {
                    "tag_name": tag,
                    "draft": outcome == "draft",
                    "prerelease": True,
                }
            ).encode()
            return subprocess.CompletedProcess(
                args,
                int(status != 200),
                stdout=f"HTTP/2.0 {status}\r\n\r\n".encode() + body,
            )
        if args[2] == "view":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "tagName": tag,
                        "isDraft": outcome == "draft",
                        "isPrerelease": release_tag is not None,
                    }
                ).encode(),
            )
        if outcome != "missing-setup":
            setup.write_bytes(artifact)
        if outcome != "missing-manifest":
            manifest.write_text(f"{digest}  {setup.name}\n", encoding="ascii")
        return subprocess.CompletedProcess(args, 0, stdout=b"")

    monkeypatch.setattr(_release_assets.subprocess, "run", run)

    def download() -> _release_assets.DownloadedReleaseSetup:
        return _release_assets.download_release_setup(
            GitHubReleaseSource(repository, False),
            app_id="app",
            target="x86_64-pc-windows-msvc",
            directory=tmp_path,
            environment=environment,
            release_tag=release_tag,
        )

    expected_calls = [
        [
            "gh",
            "release",
            "view",
            "--repo",
            f"github.com/{repository}",
            "--json",
            "tagName,isDraft,isPrerelease",
        ]
        if release_tag is None
        else [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--include",
            f"repos/{repository}/releases/tags/{release_tag}",
        ]
    ]
    if outcome not in {"draft", "missing", "forbidden"}:
        expected_calls.append(
            [
                "gh",
                "release",
                "download",
                "--repo",
                f"github.com/{repository}",
                "--pattern",
                setup.name,
                "--pattern",
                manifest.name,
                "--dir",
                str(tmp_path),
                "--",
                tag,
            ]
        )
    if outcome == "published":
        assert download() == (setup, digest, tag, None)
        assert setup.read_bytes() == artifact
    else:
        with pytest.raises(ValueError, match=repository) as failure:
            download()
        assert tag in str(failure.value)
        if outcome in {"missing", "forbidden"}:
            assert "gh auth status" in str(failure.value)
        if outcome in {"draft", "missing", "forbidden"}:
            assert not list(tmp_path.iterdir())
        else:
            assert setup.name in str(failure.value)
            assert manifest.name in str(failure.value)
    assert calls == expected_calls


@pytest.mark.parametrize(
    ("requested", "published_tags", "winner", "expected", "lookup_status"),
    [
        (
            "2.0.0rc1",
            ("v2.0.0rc1", "v2.0.0-rc.1"),
            "v2.0.0rc1",
            "2.0.0rc1",
            404,
        ),
        ("v2.0.0rc1", ("v2.0.0-rc.1",), "v2.0.0-rc.1", "2.0.0rc1", 404),
        ("2.0.0-rc.1", ("2.0.0-rc.1",), "2.0.0-rc.1", "2.0.0rc1", 404),
        ("v2.0.0-rc.1", ("2.0.0rc1",), "2.0.0rc1", "2.0.0rc1", 404),
        ("2.0.0.301", ("v2.0.0rc1",), "v2.0.0rc1", "2.0.0rc1", 404),
        ("v2.0.0.400", ("v2.0",), "v2.0", "2.0.0", 404),
        ("2.0.0.301", ("v2.0.0.301",), "v2.0.0.301", "2.0.0.301", 404),
        (
            "2.0.0.301",
            ("v2.0.0rc1", "v2.0.0.301"),
            None,
            "matches releases",
            404,
        ),
        ("2.0.0", (), None, "No published release", 404),
        ("2.0.0", ("2.0.0",), None, "at tag", 403),
    ],
)
@pytest.mark.parametrize("public", [True, False])
def test_release_version_resolves_before_downloading_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    published_tags: tuple[str, ...],
    winner: str | None,
    expected: str,
    lookup_status: int,
    public: bool,
) -> None:
    setup_name = "app-setup-linux-x86_64"
    digest = hashlib.sha256(b"setup").hexdigest()
    assets = {
        setup_name: b"setup",
        "SHA256SUMS": f"{digest}  {setup_name}\n".encode(),
    }
    downloaded: list[str] = []
    looked_up: list[str] = []

    def metadata(tag: str) -> bytes:
        return json.dumps(
            {
                "tag_name": tag,
                "draft": False,
                "prerelease": "-" in tag or "rc" in tag,
            }
        ).encode()

    def open_release(request: Request, **_kwargs: object) -> BytesIO:
        if "/releases/tags/" in request.full_url:
            tag = request.full_url.rsplit("/", 1)[-1]
            looked_up.append(tag)
            if tag not in published_tags:
                raise HTTPError(
                    request.full_url,
                    lookup_status,
                    "unavailable",
                    Message(),
                    None,
                )
            return BytesIO(metadata(tag))
        _, tag, asset = request.full_url.rsplit("/", 2)
        downloaded.append(tag)
        return BytesIO(assets[asset])

    def run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        tag = arguments[-1].rsplit("/", 1)[-1]
        if arguments[1] == "api":
            looked_up.append(tag)
            if tag not in published_tags:
                return subprocess.CompletedProcess(
                    arguments,
                    1,
                    stdout=f"HTTP/2.0 {lookup_status}\n\n{{}}".encode(),
                )
            return subprocess.CompletedProcess(
                arguments, 0, stdout=b"HTTP/2.0 200 OK\n\n" + metadata(tag)
            )
        assert arguments[1:3] == ["release", "download"]
        downloaded.append(tag)
        for name, contents in assets.items():
            (tmp_path / name).write_bytes(contents)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(_release_assets, "urlopen", open_release)
    monkeypatch.setattr(
        _release_assets.shutil, "which", lambda *_a, **_kw: "gh"
    )
    monkeypatch.setattr(_release_assets.subprocess, "run", run)

    def download() -> _release_assets.DownloadedReleaseSetup:
        return _release_assets.download_release_setup(
            GitHubReleaseSource("author/app", public),
            app_id="app",
            target="x86_64-unknown-linux-gnu",
            directory=tmp_path,
            environment={},
            requested_version=Version(requested),
        )

    if winner is None:
        with pytest.raises(ValueError, match=expected) as failure:
            download()
        if lookup_status == 403:
            assert looked_up == ["v2.0.0"]
        elif published_tags:
            assert all(tag in str(failure.value) for tag in published_tags)
            assert "--release TAG" in str(failure.value)
        assert not downloaded
    else:
        selected = download()
        assert selected.tag == winner
        assert selected.version == Version(expected)
        assert selected.path.read_bytes() == b"setup"
        assert downloaded and set(downloaded) == {winner}


@pytest.mark.parametrize(
    (
        "version",
        "changed",
        "release_tag",
        "release_version",
        "resolved",
        "error",
    ),
    [
        ("1.0", False, None, None, None, ""),
        ("1.0", True, None, None, None, "bump the version"),
        ("0.9", False, None, None, None, "older than installed"),
        ("2.0", True, None, None, None, ""),
        ("0.9rc1", False, "older/v0.9rc1", None, None, "older than installed"),
        ("2.0rc1", True, "preview/v2.0rc1", None, None, ""),
        ("2.0.0rc1", True, None, "2.0.0.301", "2.0.0rc1", ""),
        (
            "2.0.0.0rc1",
            True,
            None,
            "2.0.0.301",
            "2.0.0rc1",
            "expected 2.0.0rc1",
        ),
        ("2.0.0rc2", True, None, "2.0.0rc1", "2.0.0rc1", "expected 2.0.0rc1"),
        ("0.9rc1", False, None, "0.9rc1", "0.9rc1", "older than installed"),
        ("2.0", True, None, "invalid", None, "Invalid requested version"),
    ],
)
def test_managed_update_compares_verified_binding_to_active_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    changed: bool,
    release_tag: str | None,
    release_version: str | None,
    resolved: str | None,
    error: str,
) -> None:
    directory, runtime = managed_installation(tmp_path)
    manager = InstallationManager(
        AppRC(app_id="handoff-app").schema, directory=directory
    )
    record = manager.inspect().require_usable()
    assert record is not None
    binding = NativeBinding(
        record.identity,
        record.command_name,
        "App",
        "1.0",
        runtime.source,
        runtime.selection,
        AppCapabilities(),
        record.placement.layout,
        "TEST",
        release_source=GitHubReleaseSource("author/app", True),
    )
    candidate = replace(
        binding,
        version=version,
        source=replace(runtime.source, commit="a" * 40)
        if changed
        else runtime.source,
    )
    setup = tmp_path / "setup"
    setup.touch()
    selections: list[tuple[str | None, Version | None]] = []
    tag = release_tag or f"v{resolved or version}"

    def download(
        *_args: object,
        release_tag: str | None = None,
        requested_version: Version | None = None,
        **_kwargs: object,
    ) -> _release_assets.DownloadedReleaseSetup:
        selections.append((release_tag, requested_version))
        return _release_assets.DownloadedReleaseSetup(
            setup, "digest", tag, Version(resolved) if resolved else None
        )

    monkeypatch.setattr(update, "download_release_setup", download)
    monkeypatch.setattr(
        update,
        "_inspect_native_products",
        lambda *_args, **_kwargs: (candidate, None),
    )
    monkeypatch.setattr(update.platform, "machine", lambda: "x86_64")
    confirmed: list[str] = []
    applied: list[UpdateWork] = []
    monkeypatch.setattr(
        update, "run_update", lambda work, _env: applied.append(work) or 0
    )
    monkeypatch.setattr(
        update,
        "_hand_off_windows",
        lambda _stage, work, *_args: applied.append(work),
    )

    def perform() -> int:
        return update.update_application(
            manager,
            binding=binding,
            regular_app_id=record.identity.app_id,
            maintenance_group="app",
            confirm=confirmed.append,
            release_tag=release_tag,
            release_version=release_version,
        )

    if error:
        with pytest.raises(ValueError, match=error):
            perform()
    else:
        assert perform() == 0
    if release_version == "invalid":
        assert not selections
    else:
        assert selections == [
            (release_tag, Version(release_version) if release_version else None)
        ]
    assert bool(confirmed) is (not error and version != runtime.version)
    assert bool(applied) == bool(confirmed)
    if confirmed:
        assert f"from {runtime.version} to {version}" in confirmed[0]
        if release_tag is not None or release_version is not None:
            assert tag in confirmed[0]
    if applied:
        assert "--apprc-update-revision" in applied[0]["command"]
        assert applied[0]["command"][0] == str(setup)


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


@pytest.mark.skipif(
    sys.platform != "linux", reason="Isolates a POSIX editable subprocess flow"
)
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "dirty",
        "ignored",
        "diverged",
        "sync",
        "registration",
        "tag",
        "version",
    ],
)
def test_editable_update_uses_saved_checkout_and_reports_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    for key, value in (
        ("user.name", "Update Test"),
        ("user.email", "test@example.invalid"),
    ):
        _git(upstream, "config", key, value)
    metadata = upstream / "pyproject.toml"
    metadata.write_text(
        '[project]\nname = "coordination-fixture"\nversion = "1.0"\n'
    )
    (upstream / ".gitignore").write_text(".venv/\n")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "base")
    checkout = tmp_path / "checkout's project"
    _git(tmp_path, "clone", "-q", str(upstream), str(checkout))
    start = _git(checkout, "rev-parse", "HEAD")
    metadata.write_text(metadata.read_text().replace("1.0", "2.0"))
    if outcome == "ignored":
        (checkout / ".git" / "info" / "exclude").write_text("local.env\n")
        (checkout / "local.env").write_text("local configuration")
        (upstream / "local.env").write_text("upstream configuration")
        _git(upstream, "add", "local.env")
    _git(upstream, "commit", "-qam", "version bump")
    end = _git(upstream, "rev-parse", "HEAD")
    if outcome == "dirty":
        (checkout / "local").touch()
    elif outcome == "diverged":
        _git(
            checkout,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "local",
        )
        start = _git(checkout, "rev-parse", "HEAD")

    prefix = checkout / ".venv"
    prefix.mkdir()
    command_dir = tmp_path / "global command's bin"
    command_dir.mkdir()
    base = installation_record()
    record = replace(
        base,
        status="ready",
        active_runtime=EditableCheckout(checkout, prefix),
        owned_outputs=(
            OwnedOutput(
                "command", str(command_dir / base.command_name), "0" * 64
            ),
        ),
    )
    manager = InstallationManager(
        AppRC(app_id=record.identity.app_id).schema,
        directory=tmp_path / "installation",
        environment={
            **os.environ,
            "GIT_WORK_TREE": str(upstream),
            "UV_PROJECT_ENVIRONMENT": str(tmp_path / "other"),
            "UV_ALL_EXTRAS": "true",
        },
    )
    with installation_lock(manager.directory):
        write_record(manager.directory, record, expected_revision=None)

    original = cast(
        Callable[..., subprocess.CompletedProcess[str]], subprocess.run
    )
    calls: list[tuple[list[str], dict[str, object]]] = []
    fail_registration = outcome == "registration"

    def run(arguments: Sequence[str], **kwargs: object):
        command = list(arguments)
        if outcome in {"tag", "version"}:
            pytest.fail(f"editable release selection launched {command[0]}")
        if command[0] == str(prefix / "bin" / "python"):
            return subprocess.CompletedProcess(command, 0)
        if command[0] in {
            sys.executable,
            str(prefix / "bin" / record.command_name),
        }:
            calls.append((command, kwargs))
            code = (
                1
                if (
                    command[0] == sys.executable
                    and outcome == "sync"
                    or command[0] != sys.executable
                    and fail_registration
                )
                else 0
            )
            if code and kwargs.get("check"):
                raise subprocess.CalledProcessError(code, command)
            return subprocess.CompletedProcess(command, code)
        return original(arguments, **kwargs)

    monkeypatch.setattr(
        update,
        "_tool",
        lambda name, _env: (
            sys.executable if name == "uv" else shutil.which(name)
        ),
    )
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    confirmed: list[str] = []

    def perform() -> int:
        return update.update_application(
            manager,
            binding=None,
            regular_app_id=None,
            maintenance_group="app",
            confirm=confirmed.append,
            release_tag="v2.0" if outcome == "tag" else None,
            release_version="2.0" if outcome == "version" else None,
        )

    if outcome in {"tag", "version"}:
        selector = "--release" if outcome == "tag" else "--version"
        with pytest.raises(
            ValueError, match=f"{selector} requires a managed"
        ) as failure:
            perform()
        assert "upstream branch" in str(failure.value)
        assert not confirmed
        return

    if outcome == "ignored":
        with pytest.raises(subprocess.CalledProcessError):
            perform()
        assert confirmed and not calls
        assert _git(checkout, "rev-parse", "HEAD") == start
        assert (checkout / "local.env").read_text() == "local configuration"
        return

    if outcome in {"dirty", "diverged", "sync"}:
        expected = {
            "dirty": "dirty",
            "diverged": "fast-forward",
            "sync": "Dependency sync failed",
        }[outcome]
        error_type = (
            EditableUpdateRetryError if outcome == "sync" else ValueError
        )
        with pytest.raises(error_type, match=expected) as failure:
            perform()
        if outcome == "sync":
            assert shlex.split(str(failure.value).splitlines()[-1]) == [
                f"UV_PROJECT_ENVIRONMENT={prefix}",
                sys.executable,
                "sync",
                "--locked",
            ]
    else:
        assert perform() == int(outcome == "registration")

    if outcome in {"dirty", "diverged"}:
        assert not calls and not confirmed
        assert _git(checkout, "rev-parse", "HEAD") == start
    else:
        assert confirmed
        assert _git(checkout, "rev-parse", "HEAD") == end
        assert calls[0][0] == [sys.executable, "sync", "--locked"]
        assert calls[0][1]["cwd"] == checkout
        assert isinstance(env := calls[0][1]["env"], dict)
        assert env["UV_PROJECT_ENVIRONMENT"] == str(prefix)
        assert "UV_ALL_EXTRAS" not in env and "GIT_WORK_TREE" not in env
        count = 1 if outcome == "sync" else 2
        assert len(calls) == count
        if count == 2:
            assert str(command_dir) in calls[1][0]
        if outcome == "registration":
            recovery = capsys.readouterr().err.splitlines()
            assert any("retry registration" in line for line in recovery[:-1])
            assert shlex.split(recovery[-1]) == calls[1][0][:-4]
            fail_registration = False
            calls.clear()
            confirmed.clear()
            assert perform() == 0
            assert _git(checkout, "rev-parse", "HEAD") == end
            assert confirmed
            assert calls[-1][0][0] == str(prefix / "bin" / record.command_name)
            assert "--apprc-update-revision" in calls[-1][0]


def test_expected_update_rejects_a_stale_record(tmp_path: Path) -> None:
    directory, _ = managed_installation(tmp_path)
    manager = InstallationManager(
        AppRC(app_id="handoff-app").schema, directory=directory
    )
    inspection = manager.inspect()
    record = inspection.require_usable()
    assert record is not None and inspection.revision is not None
    with pytest.raises(ValueError, match="installation changed"):
        require_update_record(inspection, (record.generation_id, "0" * 64))


@pytest.mark.parametrize("acknowledge", [False, True])
def test_handoff_opens_all_waiters_before_applying_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acknowledge: bool,
) -> None:
    from io import StringIO

    from apprc.distribution.runtime import _update_handoff

    stage = tmp_path / "handoff"
    stage.mkdir()
    plan = stage / "update.json"
    plan.write_text(
        json.dumps(
            {"processes": [[10, "launcher"], [20, "native"]], "work": {}}
        )
    )
    events: list[str] = []

    def open_waiter(_pid: int, token: str) -> str:
        events.append(f"open {token}")
        return token

    monkeypatch.setattr(_update_handoff, "_open_process_waiter", open_waiter)
    monkeypatch.setattr(
        _update_handoff,
        "_wait_open_process",
        lambda token: events.append(f"wait {token}"),
    )
    monkeypatch.setattr(
        _update_handoff,
        "run_update",
        lambda *_args, **_kwargs: events.append("apply") or 0,
    )
    monkeypatch.setattr(sys, "stdin", StringIO("EXIT\n" if acknowledge else ""))
    monkeypatch.setattr(sys, "stdout", StringIO())
    assert _update_handoff._main(plan) == int(not acknowledge)
    after_ready = (
        ["wait launcher", "wait native", "apply"] if acknowledge else []
    )
    assert events == ["open launcher", "open native", *after_ready]
    assert not stage.exists()
