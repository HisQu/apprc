"""Update selection, Git safety, and release verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from apprc import AppRC
from apprc.definition.installation import EditableCheckout, OwnedOutput
from apprc.distribution import _release_assets
from apprc.distribution.models import (
    AppCapabilities,
    GitHubReleaseSource,
    NativeBinding,
)
from apprc.distribution.runtime import update
from apprc.distribution.runtime._update_handoff import UpdateWork
from apprc.distribution.runtime.installation import require_update_record
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from tests.support_installation import installation_record, managed_installation


@pytest.mark.parametrize("valid", [True, False])
def test_release_download_uses_one_tag_and_checks_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    repository = "author/app"
    base = f"https://github.com/{repository}/releases/download/v2.0"
    setup = "app-setup-linux-x86_64"
    artifact = b"candidate executable"
    digest = hashlib.sha256(artifact if valid else b"different").hexdigest()
    responses = {
        f"https://api.github.com/repos/{repository}/releases/latest": json.dumps(
            {"tag_name": "v2.0", "draft": False, "prerelease": False}
        ).encode(),
        f"{base}/{setup}": artifact,
        f"{base}/SHA256SUMS": f"{digest}  {setup}\n".encode(),
    }
    monkeypatch.setattr(
        _release_assets,
        "urlopen",
        lambda request, **_kwargs: BytesIO(responses.pop(request.full_url)),
    )

    def download() -> tuple[Path, str]:
        return _release_assets.download_release_setup(
            GitHubReleaseSource(repository, True),
            app_id="app",
            target="x86_64-unknown-linux-gnu",
            directory=tmp_path,
            environment={},
        )

    if valid:
        path, downloaded_digest = download()
        assert path.read_bytes() == artifact
        assert downloaded_digest == digest
    else:
        with pytest.raises(ValueError, match="release checksum"):
            download()
    assert responses == {}


@pytest.mark.parametrize(
    ("version", "changed", "error"),
    [
        ("1.0", False, ""),
        ("1.0", True, "bump the version"),
        ("0.9", False, "older than installed"),
        ("2.0", True, ""),
    ],
)
def test_managed_update_compares_verified_binding_to_active_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    changed: bool,
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
    monkeypatch.setattr(
        update,
        "download_release_setup",
        lambda *_args, **_kwargs: (setup, "digest"),
    )
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
        )

    if error:
        with pytest.raises(ValueError, match=error):
            perform()
    else:
        assert perform() == 0
    assert bool(confirmed) == (version == "2.0")
    assert bool(applied) == bool(confirmed)
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
    ["success", "dirty", "ignored", "diverged", "sync", "registration"],
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
    checkout = tmp_path / "checkout"
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
    command_dir = tmp_path / "commands"
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
        )

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
        with pytest.raises(ValueError, match=expected):
            perform()
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
            assert "retry" in capsys.readouterr().err
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
