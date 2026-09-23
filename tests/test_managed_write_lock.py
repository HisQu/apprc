"""Cross-process revision checks for AppRC-managed edits."""

from __future__ import annotations

from multiprocessing import get_context
from multiprocessing.synchronize import Barrier
from multiprocessing.queues import Queue
from pathlib import Path

import apprc as rc
from apprc.user_files.app_home.writes import StaleEditError


def _app(root: Path) -> rc.AppRC:
    """Declare the same user file independently in each process."""
    app = rc.AppRC(
        app_id="lock-check", user_dotenv=rc.UserDotenv(), apprc_dir=root
    )

    @app.config("settings", prefix="LOCK_")
    class Settings(rc.Config):
        label: str = rc.field("LOCK_LABEL", default="initial")

    return app


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
    manager.setup_user_dotenv()
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
