"""Real-process authority, namespace retirement and managed-writer safety."""

from __future__ import annotations

import multiprocessing
import os
from dataclasses import replace
from errno import EIO
from multiprocessing.connection import _ConnectionBase
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from filelock import FileLock, Timeout

from apprc.definition.installation import (
    InstallationError,
    InstallationPlacement,
    InstallationRecord,
    InstallationWriteAuthority,
)
from apprc.definition.paths import Layout
from apprc.user_files.app_home.locations import write_text_atomic
from apprc.user_files.app_home.writes import managed_write_lock
from apprc.user_files.installation.coordination import (
    StaleLockNamespace,
    finish_namespace_retirement,
    installation_lock,
    retire_held_operation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation


def _record() -> InstallationRecord:
    return InstallationRecord(
        1,
        "coordination-fixture",
        uuid4(),
        "0.31.0",
        InstallationPlacement(Layout.native()),
        "removed-retained",
    )


def _stale_namespace_consumer(
    directory: Path, channel: _ConnectionBase
) -> None:
    """Pause once at the public acquired-descriptor callback, before validation."""
    first = True

    def factory(*args: object, **kwargs: object) -> FileLock:
        nonlocal first
        original = cast(Callable[[int], None], kwargs["on_acquired"])

        def acquired(fd: int) -> None:
            nonlocal first
            if first:
                first = False
                channel.send("physical-lock-acquired")
                channel.recv()
            original(fd)

        kwargs["on_acquired"] = acquired
        return FileLock(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    with patch(
        "apprc.user_files.installation.coordination.FileLock",
        side_effect=factory,
    ):
        with installation_lock(directory):
            inspection = inspect_installation(
                directory, app_id="coordination-fixture"
            )
            channel.send(str(inspection.snapshot.generation_id))
    channel.close()


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows native handles deliberately block lock unlink",
)
def test_acquired_old_inode_is_rejected_before_observing_new_authority(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    directory = tmp_path / "installation"
    process = context.Process(
        target=_stale_namespace_consumer, args=(directory, child)
    )
    process.start()
    child.close()
    try:
        assert parent.poll(10), (
            "Consumer did not reach acquired-descriptor barrier"
        )
        assert parent.recv() == "physical-lock-acquired"
        (directory / "locks" / "operation.lock").unlink()
        record = _record()
        with installation_lock(directory):
            write_record(directory, record, expected_revision=None)
        parent.send("namespace-replaced")
        assert parent.poll(10), (
            "Consumer failed to reacquire the replacement namespace"
        )
        assert parent.recv() == str(record.generation_id)
        process.join(10)
        assert process.exitcode == 0
        assert (
            inspect_installation(directory, app_id=record.app_id).record
            == record
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        parent.close()


def _publish_new_generation(
    directory: Path, record: InstallationRecord
) -> None:
    with installation_lock(directory):
        (directory / "saved-controller.py").write_text("new generation support")
        write_record(directory, record, expected_revision=None)


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX held-lock retirement; Windows uses post-release unlink",
)
def test_finalizer_never_removes_new_generation_support(tmp_path: Path) -> None:
    directory = tmp_path / "installation"
    old_generation = uuid4()
    with installation_lock(directory):
        retire_held_operation_lock(directory)
        newer = _record()
        process = multiprocessing.get_context("spawn").Process(
            target=_publish_new_generation,
            args=(directory, newer),
        )
        process.start()
        process.join(10)
        try:
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)
    result = finish_namespace_retirement(
        directory, generation_id=old_generation
    )
    assert result.container == "occupied"
    assert (
        directory / "saved-controller.py"
    ).read_text() == "new generation support"
    assert inspect_installation(directory, app_id=newer.app_id).record == newer


def _queued_old_inode_writer(
    directory: Path,
    original: InstallationRecord,
    expected_revision: str,
    channel: _ConnectionBase,
) -> None:
    """Keep a genuinely contended descriptor open through complete retirement."""
    import fcntl

    original_flock = fcntl.flock
    queued = False

    def flock(fd: int, operation: int) -> None:
        nonlocal queued
        if not queued and operation & fcntl.LOCK_EX:
            try:
                original_flock(fd, operation)
            except BlockingIOError:
                queued = True
                info = os.fstat(fd)
                channel.send(("old-inode-queued", info.st_dev, info.st_ino))
                assert _receive(channel) == "replacement-published"
                raise
            else:
                raise AssertionError(
                    "Old installer did not contend with removal"
                )
        original_flock(fd, operation)

    def factory(*args: object, **kwargs: object) -> FileLock:
        original_acquired = cast(Callable[[int], None], kwargs["on_acquired"])

        def acquired(fd: int) -> None:
            original_acquired(fd)
            info = os.fstat(fd)
            channel.send(
                ("active-namespace-acquired", info.st_dev, info.st_ino)
            )

        kwargs["on_acquired"] = acquired
        return FileLock(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    try:
        with (
            patch("fcntl.flock", side_effect=flock),
            patch(
                "apprc.user_files.installation.coordination.FileLock",
                side_effect=factory,
            ),
        ):
            with installation_lock(directory):
                try:
                    write_record(
                        directory,
                        replace(original, support_version="0.31.9"),
                        expected_revision=expected_revision,
                    )
                except InstallationError:
                    current = inspect_installation(
                        directory, app_id=original.app_id
                    )
                    channel.send(("stale-revision", current.revision))
                else:
                    (directory / "saved-controller.py").write_text(
                        "obsolete installer support", encoding="utf-8"
                    )
                    channel.send(("obsolete-installer-mutated",))
        result = finish_namespace_retirement(
            directory, generation_id=original.generation_id
        )
        channel.send(("late-retirement", result.container))
    finally:
        channel.close()


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX old-inode waiters survive held-lock unlink"
)
def test_queued_old_inode_cannot_mutate_a_third_installers_generation(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    original = _record()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process: BaseProcess | None = None
    newer_process: BaseProcess | None = None
    try:
        with installation_lock(directory):
            revision = write_record(directory, original, expected_revision=None)
            support = directory / "saved-controller.py"
            support.write_text("old generation support", encoding="utf-8")
            old_lock = (directory / "locks" / "operation.lock").stat()
            process = context.Process(
                target=_queued_old_inode_writer,
                args=(directory, original, revision, child),
            )
            process.start()
            child.close()
            assert _receive(parent) == (
                "old-inode-queued",
                old_lock.st_dev,
                old_lock.st_ino,
            )
            support.unlink()
            (directory / "installation.json").unlink()
            retire_held_operation_lock(directory)
        retired = finish_namespace_retirement(
            directory, generation_id=original.generation_id
        )
        assert retired.container == "removed"
        assert not directory.exists()
        newer = _record()
        newer_process = context.Process(
            target=_publish_new_generation, args=(directory, newer)
        )
        newer_process.start()
        newer_process.join(10)
        assert newer_process.exitcode == 0
        replacement = inspect_installation(directory, app_id=newer.app_id)
        assert replacement.record == newer
        new_lock = (directory / "locks" / "operation.lock").stat()
        assert (new_lock.st_dev, new_lock.st_ino) != (
            old_lock.st_dev,
            old_lock.st_ino,
        )
        parent.send("replacement-published")
        assert _receive(parent) == (
            "active-namespace-acquired",
            new_lock.st_dev,
            new_lock.st_ino,
        )
        assert _receive(parent) == ("stale-revision", replacement.revision)
        assert _receive(parent) == ("late-retirement", "occupied")
        process.join(10)
        assert process.exitcode == 0
        assert (
            inspect_installation(directory, app_id=newer.app_id) == replacement
        )
        assert support.read_text(encoding="utf-8") == "new generation support"
    finally:
        if process is not None:
            _stop_process(process)
        if newer_process is not None:
            _stop_process(newer_process)
        child.close()
        parent.close()


def _receive(channel: _ConnectionBase) -> object:
    """Bound every process barrier so a failed actor cannot hang the suite."""
    assert channel.poll(10), "Process did not reach its synchronization barrier"
    return channel.recv()


def _stop_process(process: BaseProcess) -> None:
    """Release a failed actor without leaving an unbounded join."""
    if process.is_alive():
        process.terminate()
        process.join(10)
    if process.is_alive():
        process.kill()
        process.join(10)
    assert not process.is_alive(), "Spawned actor did not stop"


def _competing_revision_writer(
    directory: Path, candidate: InstallationRecord, channel: _ConnectionBase
) -> None:
    """Capture one revision before either actor is allowed to publish."""
    try:
        planned = inspect_installation(directory, app_id=candidate.app_id)
        assert planned.revision is not None
        channel.send(("planned", planned.revision))
        assert _receive(channel) == "publish"
        with installation_lock(directory):
            try:
                revision = write_record(
                    directory, candidate, expected_revision=planned.revision
                )
            except InstallationError:
                current = inspect_installation(
                    directory, app_id=candidate.app_id
                )
                channel.send(("stale", current.revision))
            else:
                channel.send(("saved", revision))
    finally:
        channel.close()


def test_spawned_writers_cannot_overwrite_the_same_authority_revision(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    original = _record()
    with installation_lock(directory):
        revision = write_record(directory, original, expected_revision=None)
    candidates = (
        replace(original, generation_id=uuid4(), support_version="0.31.1"),
        replace(original, generation_id=uuid4(), support_version="0.31.2"),
    )
    context = multiprocessing.get_context("spawn")
    channels: list[_ConnectionBase] = []
    processes: list[BaseProcess] = []
    try:
        for candidate in candidates:
            parent, child = context.Pipe()
            process = context.Process(
                target=_competing_revision_writer,
                args=(directory, candidate, child),
            )
            process.start()
            child.close()
            channels.append(parent)
            processes.append(process)
        for channel in channels:
            assert _receive(channel) == ("planned", revision)
        for channel in channels:
            channel.send("publish")
        results = [
            cast(tuple[str, str], _receive(channel)) for channel in channels
        ]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert sorted(status for status, _ in results) == ["saved", "stale"]
        winner = next(
            candidate
            for candidate, (status, _) in zip(candidates, results)
            if status == "saved"
        )
        inspection = inspect_installation(directory, app_id=original.app_id)
        assert inspection.record == winner
        assert inspection.revision != revision
        assert all(
            saved_revision == inspection.revision
            for _, saved_revision in results
        )
    finally:
        for process in processes:
            _stop_process(process)
        for channel in channels:
            channel.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX unlink while held")
def test_retired_empty_container_can_be_removed_without_a_new_checkpoint(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    generation = uuid4()
    with installation_lock(directory):
        retire_held_operation_lock(directory)
    result = finish_namespace_retirement(directory, generation_id=generation)
    assert result.container == "removed"
    assert not directory.exists()


def _write_captured_resource(
    authority: InstallationWriteAuthority,
    root: Path,
    channel: _ConnectionBase,
    *,
    pause_after_lock: bool,
) -> None:
    """Try one real managed write with its invocation-captured authority."""
    try:
        if pause_after_lock:
            original_file_lock = FileLock
            paused = False

            def factory(*args: object, **kwargs: object) -> FileLock:
                def acquired(fd: int) -> None:
                    nonlocal paused
                    del fd
                    if not paused:
                        paused = True
                        channel.send("resource-lock-acquired")
                        assert _receive(channel) == "authority-replaced"

                return original_file_lock(*args, on_acquired=acquired, **kwargs)  # pyright: ignore[reportArgumentType]

            with patch(
                "apprc.user_files.app_home.writes.FileLock",
                side_effect=factory,
            ):
                with managed_write_lock(root, authority=authority):
                    write_text_atomic(root / "payload.txt", "old payload")
        else:
            with managed_write_lock(root, authority=authority):
                write_text_atomic(root / "payload.txt", "old payload")
    except InstallationError:
        channel.send("rejected")
    else:
        channel.send("written")
    finally:
        channel.close()


def test_captured_resource_writer_cannot_recreate_a_retired_generation(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    root = tmp_path / "retired-cache"
    root.mkdir()
    payload = root / "payload.txt"
    payload.write_text("old payload", encoding="utf-8")
    placement = InstallationPlacement(
        Layout.native(), cache_dir=root, capabilities=frozenset({"cache"})
    )
    record = replace(_record(), placement=placement)
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    captured = inspect_installation(directory, app_id=record.app_id).snapshot
    authority = InstallationWriteAuthority(record.app_id, captured)
    with installation_lock(directory):
        with managed_write_lock(root):
            payload.unlink()
            root.rmdir()
        (directory / "installation.json").unlink()
        retire_held_operation_lock(directory)
    retirement = finish_namespace_retirement(
        directory, generation_id=record.generation_id
    )
    assert retirement.container == "removed"

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_write_captured_resource,
        args=(authority, root, child),
        kwargs={"pause_after_lock": False},
    )
    process.start()
    child.close()
    try:
        assert _receive(parent) == "rejected"
        process.join(10)
        assert process.exitcode == 0
        assert not payload.exists()
        assert not root.exists()
    finally:
        _stop_process(process)
        parent.close()


def test_captured_resource_writer_revalidates_after_lock_before_mutation(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    root = tmp_path / "cache"
    placement = InstallationPlacement(
        Layout.native(), cache_dir=root, capabilities=frozenset({"cache"})
    )
    old = replace(_record(), placement=placement)
    with installation_lock(directory):
        revision = write_record(directory, old, expected_revision=None)
    captured = inspect_installation(directory, app_id=old.app_id).snapshot
    authority = InstallationWriteAuthority(old.app_id, captured)
    root.mkdir()
    payload = root / "payload.txt"
    payload.write_text("replacement payload", encoding="utf-8")
    newer = replace(old, generation_id=uuid4())
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_write_captured_resource,
        args=(authority, root, child),
        kwargs={"pause_after_lock": True},
    )
    process.start()
    child.close()
    try:
        assert _receive(parent) == "resource-lock-acquired"
        with installation_lock(directory):
            write_record(directory, newer, expected_revision=revision)
        parent.send("authority-replaced")
        assert _receive(parent) == "rejected"
        process.join(10)
        assert process.exitcode == 0
        assert payload.read_text(encoding="utf-8") == "replacement payload"
        assert (
            inspect_installation(directory, app_id=newer.app_id).record == newer
        )
    finally:
        _stop_process(process)
        parent.close()


def test_lifecycle_lock_honors_cancellation_before_creating_namespace(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    with pytest.raises(InstallationError):
        with installation_lock(directory, cancelled=lambda: True):
            pytest.fail("Cancelled lifecycle acquisition entered its context")
    assert not directory.exists()


def _hold_lifecycle_lock(
    directory: Path, channel: _ConnectionBase
) -> None:
    try:
        with installation_lock(directory):
            channel.send("holder-acquired")
            while _receive(channel) != "release":
                pass
        channel.send("holder-released")
    finally:
        channel.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX lock contention boundary")
def test_lifecycle_lock_cancels_after_real_process_contention(
    tmp_path: Path,
) -> None:
    import fcntl

    directory = tmp_path / "installation"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_hold_lifecycle_lock, args=(directory, child)
    )
    process.start()
    child.close()
    original_flock = fcntl.flock
    contention_seen = False
    cancellation_seen = False

    def flock(fd: int, operation: int) -> None:
        nonlocal contention_seen
        try:
            original_flock(fd, operation)
        except BlockingIOError:
            if operation & fcntl.LOCK_EX:
                contention_seen = True
            raise

    def cancelled() -> bool:
        nonlocal cancellation_seen
        if contention_seen:
            cancellation_seen = True
            return True
        return False

    try:
        assert _receive(parent) == "holder-acquired"
        with patch("fcntl.flock", side_effect=flock):
            with pytest.raises(InstallationError):
                with installation_lock(
                    directory, timeout=5, cancelled=cancelled
                ):
                    pytest.fail("Cancelled contended acquisition entered")
        assert contention_seen
        assert cancellation_seen
        assert (
            inspect_installation(
                directory, app_id="coordination-fixture"
            ).status
            == "missing"
        )
        assert not (directory / "saved-controller.py").exists()
    finally:
        try:
            parent.send("release")
            assert _receive(parent) == "holder-released"
            process.join(10)
            assert process.exitcode == 0
        finally:
            _stop_process(process)
            parent.close()


@pytest.mark.parametrize("race", ["stale-lock", "setup-disappeared"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX lock path boundary")
def test_lifecycle_retry_races_share_one_acquisition_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    import apprc.user_files.installation.coordination as coordination

    directory = tmp_path / "installation"
    operation_lock_path = directory / "locks" / "operation.lock"
    now = iter((0.0, 0.1, 0.75))
    monkeypatch.setattr(coordination, "monotonic", lambda: next(now))
    original_file_lock = FileLock
    original_stat = Path.stat

    def factory(*args: object, **kwargs: object) -> FileLock:
        def acquired(fd: int) -> None:
            del fd
            if race == "stale-lock":
                raise StaleLockNamespace("Controlled stale lock namespace.")
            raise AssertionError("Setup disappearance must precede callback")

        kwargs["on_acquired"] = acquired
        return original_file_lock(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    def stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if (
            race == "setup-disappeared"
            and path == directory
            and (directory / "locks").is_dir()
            and not operation_lock_path.exists()
        ):
            (directory / "locks").rmdir()
            directory.rmdir()
            raise FileNotFoundError(path)
        return original_stat(path, follow_symlinks=follow_symlinks)

    with patch(
        "apprc.user_files.installation.coordination.FileLock",
        side_effect=factory,
    ):
        if race == "setup-disappeared":
            with patch("pathlib.Path.stat", new=stat):
                with pytest.raises(Timeout):
                    with installation_lock(directory, timeout=0.5):
                        pytest.fail(
                            "Expired retry deadline entered its context"
                        )
        else:
            with pytest.raises(Timeout):
                with installation_lock(directory, timeout=0.5):
                    pytest.fail("Expired retry deadline entered its context")
    assert (
        inspect_installation(directory, app_id="coordination-fixture").status
        == "missing"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX callback rollback boundary")
def test_acquired_callback_rollback_failure_preserves_both_errors(
    tmp_path: Path,
) -> None:
    import fcntl

    directory = tmp_path / "installation"
    lock_path = directory / "locks" / "operation.lock"
    original_flock = fcntl.flock
    callback_error = StaleLockNamespace("Acquired namespace validation failed.")
    rollback_error = OSError(EIO, "rollback unlock failed")
    captured_fd: int | None = None
    retained_lock: FileLock | None = None

    def factory(*args: object, **kwargs: object) -> FileLock:
        nonlocal captured_fd, retained_lock

        def acquired(fd: int) -> None:
            nonlocal captured_fd
            captured_fd = fd
            raise callback_error

        kwargs["on_acquired"] = acquired
        lock = FileLock(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        retained_lock = lock
        return lock

    def flock(fd: int, operation: int) -> None:
        if captured_fd == fd and operation & fcntl.LOCK_UN:
            raise rollback_error
        original_flock(fd, operation)

    try:
        with (
            patch(
                "apprc.user_files.installation.coordination.FileLock",
                side_effect=factory,
            ),
            patch("fcntl.flock", side_effect=flock),
        ):
            with pytest.raises(ExceptionGroup) as captured:
                with installation_lock(directory):
                    pytest.fail(
                        "Failed callback rollback entered lifecycle context"
                    )

        errors = captured.value.exceptions
        assert any(error is callback_error for error in errors)
        assert any(error is rollback_error for error in errors)
        assert not (directory / "installation.json").exists()
    finally:
        if retained_lock is not None:
            retained_lock.release()
    assert lock_path.exists()
