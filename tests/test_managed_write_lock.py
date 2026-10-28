"""Cross-process revision checks for AppRC-managed edits."""

from __future__ import annotations

from multiprocessing import get_context
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest

import apprc as rc
from apprc.user_files.app_home.writes import StaleEditError, managed_write_lock


def _app(root: Path) -> rc.AppRC:
    """Declare the same user file independently in each process."""
    app = rc.AppRC(
        app_id="lock-check",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(root),
        user_dotenv=rc.UserDotenv(),
    )

    @app.config("settings", prefix="LOCK_")
    class Settings(rc.Config):
        label: str = rc.field("LOCK_LABEL", default="initial")

    return app


def test_managed_write_lock_allows_nested_same_root_lock(
    tmp_path: Path,
) -> None:
    """Nested ownership initialization may safely reacquire one root lock."""
    root = tmp_path / "config"
    nested_acquired = False
    with managed_write_lock(root), managed_write_lock(root):
        nested_acquired = True
    assert nested_acquired


def _acquire_managed_lock(root: Path, results: Queue) -> None:
    """Signal after another process acquires a released managed root lock."""
    with managed_write_lock(root):
        results.put("acquired")


def test_managed_write_lock_releases_after_nested_exception(
    tmp_path: Path,
) -> None:
    """Another process can acquire the lock after nested scopes unwind."""
    root = tmp_path / "config"
    with pytest.raises(RuntimeError, match="test failure"):
        with managed_write_lock(root):
            with managed_write_lock(root):
                raise RuntimeError("test failure")

    context = get_context("spawn")
    results = context.Queue()
    process = context.Process(
        target=_acquire_managed_lock,
        args=(root, results),
    )
    process.start()
    try:
        process.join(timeout=12)
        assert process.exitcode == 0
        assert results.get(timeout=2) == "acquired"
    finally:
        if process.is_alive():
            process.terminate()
            process.join()


def _edit_in_process(
    root: Path, value: str, barrier: Barrier, results: Queue
) -> None:
    """Plan from one revision, then race another process to apply it."""
    manager = _app(root).manage(environment={})
    plan = manager.plan_update("LOCK_LABEL", value, scope="user")
    barrier.wait(timeout=10)
    try:
        manager.apply_edit(plan)
    except StaleEditError:
        results.put("stale")
    else:
        results.put("saved")


def test_two_processes_cannot_overwrite_the_same_planned_revision(
    tmp_path: Path,
) -> None:
    """Exactly one of two simultaneous saved edits should own the revision."""
    root = tmp_path / "config"
    manager = _app(root).manage(environment={})
    manager.setup()
    context = get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_edit_in_process, args=(root, value, barrier, results)
        )
        for value in ("first", "second")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in processes) == [
        "saved",
        "stale",
    ]
    assert manager.resolve().values["LOCK_LABEL"] in {"first", "second"}
