"""Behavioral safety regressions for external recovery and namespace retirement."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from multiprocessing.connection import _ConnectionBase
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

from apprc.definition.installation import InstallationError
from apprc.distribution.rendering import _stdlib_worker
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.distribution.runtime.removal import _restore_support
from apprc.distribution.runtime import namespace_finalizer


def _support_manifest(recovery: Path, entries: list[dict[str, object]]) -> None:
    recovery.mkdir(parents=True)
    (recovery / "support").mkdir()
    (recovery / "support" / "saved.py").write_bytes(b"saved support")
    (recovery / "support-backup.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


def test_restore_rejects_corrupt_paths_before_any_restore_write(
    tmp_path: Path,
) -> None:
    digest = hashlib.sha256(b"saved support").hexdigest()
    for index, path in enumerate(
        ("C:escape.py", "nested/C:escape.py", "x\\y", "../escape.py")
    ):
        recovery = tmp_path / f"recovery-{index}"
        _support_manifest(
            recovery,
            [
                {"path": "saved.py", "digest": digest, "mode": 0o600},
                {"path": path, "digest": digest, "mode": 0o600},
            ],
        )
        installation = tmp_path / f"installation-{index}"
        installation.mkdir()
        unrelated = tmp_path / "escape.py"
        unrelated.write_bytes(b"user content")

        with pytest.raises(InstallationError, match="path is unsafe"):
            _restore_support(recovery, installation)

        assert not (installation / "saved.py").exists()
        assert unrelated.read_bytes() == b"user content"

    recovery = tmp_path / "bad-types"
    _support_manifest(
        recovery,
        [{"path": "saved.py", "digest": digest, "mode": "0600"}],
    )
    with pytest.raises(InstallationError, match="malformed"):
        _restore_support(recovery, tmp_path / "bad-types-installation")


def test_restore_preserves_edits_and_restores_exact_private_backup(
    tmp_path: Path,
) -> None:
    digest = hashlib.sha256(b"saved support").hexdigest()
    recovery = tmp_path / "recovery"
    _support_manifest(
        recovery,
        [{"path": "saved.py", "digest": digest, "mode": 0o755}],
    )
    installation = tmp_path / "installation"
    create_private_directory_if_missing(installation)
    edited = installation / "saved.py"
    edited.write_bytes(b"user edit")
    if os.name != "nt":
        edited.chmod(0o600)

    with pytest.raises(InstallationError, match="changed path"):
        _restore_support(recovery, installation)
    assert edited.read_bytes() == b"user edit"

    edited.unlink()
    _restore_support(recovery, installation)
    assert edited.read_bytes() == b"saved support"
    if os.name != "nt":
        assert edited.stat().st_mode & 0o777 == 0o700

    (recovery / "support" / "saved.py").write_bytes(b"changed backup")
    edited.unlink()
    with pytest.raises(InstallationError, match="do not match"):
        _restore_support(recovery, installation)
    assert not edited.exists()


def _write_finalization_plan(plan: Path, directory: Path) -> None:
    plan.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    plan.write_text(
        json.dumps({"directory": str(directory), "support": []}),
        encoding="utf-8",
    )
    plan.chmod(0o600)


def _run_finalizer(
    script: Path, plan: Path, directory: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(script),
            "--plan",
            str(plan),
            "--directory",
            str(directory),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_emitted_finalizer_runs_isolated_and_removes_absent_or_empty_namespace(
    tmp_path: Path,
) -> None:
    script = tmp_path / "final-worker.py"
    script.write_bytes(_stdlib_worker())
    plan = tmp_path / "recovery" / "finalization.json"
    absent = tmp_path / "absent"
    _write_finalization_plan(plan, absent)
    result = _run_finalizer(script, plan, absent)
    assert result.returncode == 0, result.stderr
    assert not absent.exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    _write_finalization_plan(plan, empty)
    result = _run_finalizer(script, plan, empty)
    assert result.returncode == 0, result.stderr
    assert not empty.exists()


def test_finalizer_preserves_new_authority_and_lock_before_record(
    tmp_path: Path,
) -> None:
    script = tmp_path / "final-worker.py"
    script.write_bytes(_stdlib_worker())
    plan = tmp_path / "recovery" / "finalization.json"
    newer = tmp_path / "newer"
    newer.mkdir()
    authority = newer / "installation.json"
    authority.write_text("new generation", encoding="utf-8")
    _write_finalization_plan(plan, newer)
    result = _run_finalizer(script, plan, newer)
    assert result.returncode == 0, result.stderr
    assert authority.read_text(encoding="utf-8") == "new generation"

    lock_only = tmp_path / "lock-only"
    locks = lock_only / "locks"
    locks.mkdir(parents=True)
    lock = locks / "operation.lock"
    lock.write_bytes(b"live lock")
    _write_finalization_plan(plan, lock_only)
    result = _run_finalizer(script, plan, lock_only)
    assert result.returncode == 0, result.stderr
    assert lock.read_bytes() == b"live lock"
    assert lock_only.is_dir()


def test_finalizer_rejects_traversal_and_duplicate_plan_keys(
    tmp_path: Path,
) -> None:
    script = tmp_path / "final-worker.py"
    script.write_bytes(_stdlib_worker())
    directory = tmp_path / "installation"
    directory.mkdir()
    plan = tmp_path / "recovery" / "finalization.json"
    plan.parent.mkdir(mode=0o700, parents=True)
    plan.write_text(
        '{"directory":'
        + json.dumps(str(directory))
        + ',"directory":"../escape","support":[]}',
        encoding="utf-8",
    )
    plan.chmod(0o600)
    result = _run_finalizer(script, plan, directory)
    assert result.returncode != 0
    assert directory.is_dir()

    _write_finalization_plan(plan, directory)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(script),
            "--plan",
            str(plan),
            "--directory",
            str(tmp_path / ".." / "installation"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert directory.is_dir()


def _hold_operation_lock(
    lock_path: Path, directory: Path, channel: _ConnectionBase
) -> None:
    try:
        with FileLock(
            str(lock_path),
            timeout=10,
            preserve_lock_file=True,
            fallback_to_soft=False,
        ):
            channel.send("held")
            if channel.recv() == "continue":
                (directory / "continued-write").write_text(
                    "completed", encoding="utf-8"
                )
                channel.send("written")
    finally:
        channel.close()


def _compete_for_operation_lock(
    lock_path: Path, channel: _ConnectionBase
) -> None:
    try:
        try:
            with FileLock(
                str(lock_path),
                timeout=0.2,
                preserve_lock_file=True,
                fallback_to_soft=False,
            ):
                channel.send("acquired")
        except Timeout:
            channel.send("excluded")
    finally:
        channel.close()


def test_finalizer_does_not_break_a_live_lock_holder_or_admit_competing_writer(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    locks = directory / "locks"
    locks.mkdir(parents=True)
    lock_path = locks / "operation.lock"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    contender: BaseProcess | None = None
    contender_parent: _ConnectionBase | None = None
    holder = context.Process(
        target=_hold_operation_lock, args=(lock_path, directory, child)
    )
    holder.start()
    child.close()
    try:
        assert parent.poll(10) and parent.recv() == "held"
        script = tmp_path / "final-worker.py"
        script.write_bytes(_stdlib_worker())
        plan = tmp_path / "recovery" / "finalization.json"
        _write_finalization_plan(plan, directory)
        result = _run_finalizer(script, plan, directory)
        assert result.returncode == 0, result.stderr

        contender_parent, contender_child = context.Pipe()
        contender = context.Process(
            target=_compete_for_operation_lock,
            args=(lock_path, contender_child),
        )
        contender.start()
        contender_child.close()
        assert (
            contender_parent.poll(10) and contender_parent.recv() == "excluded"
        )
        contender.join(10)
        assert contender.exitcode == 0

        parent.send("continue")
        assert parent.poll(10) and parent.recv() == "written"
        holder.join(10)
        assert holder.exitcode == 0
        assert (directory / "continued-write").read_text(
            encoding="utf-8"
        ) == "completed"
    finally:
        if contender is not None and contender.is_alive():
            contender.terminate()
            contender.join(10)
        if contender_parent is not None:
            contender_parent.close()
        if holder.is_alive():
            parent.send("continue")
            holder.join(10)
        if holder.is_alive():
            holder.terminate()
            holder.join(10)
        parent.close()


@pytest.mark.parametrize("race", ["occupied", "disappeared", "permission"])
def test_finalizer_distinguishes_empty_directory_races_from_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    directory = tmp_path / "installation"
    directory.mkdir()
    plan = tmp_path / "recovery" / "finalization.json"
    _write_finalization_plan(plan, directory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "namespace_finalizer",
            "--plan",
            str(plan),
            "--directory",
            str(directory),
        ],
    )
    original_rmdir = Path.rmdir

    def raced_rmdir(path: Path) -> None:
        if path == directory:
            if race == "occupied":
                (directory / "new-entry").write_text("new", encoding="utf-8")
                return original_rmdir(path)
            if race == "disappeared":
                original_rmdir(path)
                raise FileNotFoundError
            raise PermissionError("denied")
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", raced_rmdir)
    if race == "permission":
        with pytest.raises(PermissionError, match="denied"):
            namespace_finalizer.main()
        assert directory.is_dir()
    else:
        namespace_finalizer.main()
        if race == "occupied":
            assert (directory / "new-entry").read_text(
                encoding="utf-8"
            ) == "new"
        else:
            assert not directory.exists()
