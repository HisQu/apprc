"""Grouped settings keep same-file fields and recover partial writes."""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

import apprc as rc
from apprc.user_files.app_home.writes import StaleEditError
from apprc.user_files.env_files import updates


def _manager(tmp_path: Path):
    """Prepare real private user configuration without external services."""
    app = rc.AppRC(
        app_id="batch-settings",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "application"),
        user_dotenv=rc.UserDotenv(),
    )

    @app.config("database", prefix="BATCH_")
    class Database(rc.Config):
        server: str = rc.field("BATCH_SERVER", default="old-host")
        user: str = rc.field("BATCH_USER", default="old-user")
        password: str = rc.field("BATCH_PASSWORD", default="", secret=True)
        port: int = rc.field("BATCH_PORT", default=3306)

    manager = app.manage(environment={})
    manager.setup()
    return manager


def test_grouped_save_coalesces_regular_values_and_keeps_password_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    plan = manager.plan_updates(
        {
            "BATCH_SERVER": "host",
            "BATCH_USER": "account",
            "BATCH_PASSWORD": "private-value",
        },
        scope="user",
    )
    assert len(plan.edits) == 2
    assert "private-value" not in repr(plan)
    writes: list[Path] = []
    original = updates.write_text_atomic

    def record_write(path, text, *, private=False):
        writes.append(path)
        return original(path, text, private=private)

    monkeypatch.setattr(updates, "write_text_atomic", record_write)
    result = manager.apply_updates(plan)
    assert len(result) == 3
    assert len(writes) == 2 and len(set(writes)) == 2
    regular = manager.writable_path("user")
    private = manager.writable_path("user", secret=True)
    assert dotenv_values(regular)["BATCH_SERVER"] == "host"
    assert dotenv_values(regular)["BATCH_USER"] == "account"
    assert "private-value" not in regular.read_text()
    assert "private-value" in private.read_text()
    assert "private-value" not in repr(result)


@pytest.mark.parametrize("failure", ["stale", "invalid", "privacy"])
def test_batch_preflight_failure_keeps_all_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from dataclasses import replace
    from apprc.user_files.env_files import secrets

    manager = _manager(tmp_path)
    regular = manager.writable_path("user")
    private = manager.writable_path("user", secret=True)
    before = (regular.read_bytes(), private.read_bytes())
    if failure == "invalid":
        with pytest.raises(ValueError):
            manager.plan_updates(
                {"BATCH_SERVER": "new", "BATCH_PORT": "not-integer"},
                scope="user",
            )
    else:
        plan = manager.plan_updates(
            {"BATCH_SERVER": "new", "BATCH_PASSWORD": "new-private"},
            scope="user",
        )
        if failure == "stale":
            regular.write_bytes(before[0] + b"# external change\n")
            before = (regular.read_bytes(), before[1])
        else:
            original = secrets.inspect_secret_file
            monkeypatch.setattr(
                secrets,
                "inspect_secret_file",
                lambda path: replace(
                    original(path),
                    available=False,
                    issue="Unavailable private path",
                ),
            )
        with pytest.raises((ValueError, StaleEditError)):
            manager.apply_updates(plan)
    assert (regular.read_bytes(), private.read_bytes()) == before


@pytest.mark.parametrize("after_write", [False, True])
@pytest.mark.parametrize("private_exists", [False, True])
def test_failed_second_write_restores_exact_bytes_or_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_write: bool,
    private_exists: bool,
) -> None:
    manager = _manager(tmp_path)
    regular = manager.writable_path("user")
    private = manager.writable_path("user", secret=True)
    if not private_exists:
        private.unlink()
    before = regular.read_bytes()
    old_private = private.read_bytes() if private_exists else None
    plan = manager.plan_updates(
        {"BATCH_SERVER": "new", "BATCH_PASSWORD": "new-private"}, scope="user"
    )
    original = updates.write_text_atomic

    def fail_second(path, text, *, private=False):
        if path == plan.edits[1].path:
            if after_write:
                original(path, text, private=private)
            raise OSError("second file write failed")
        return original(path, text, private=private)

    monkeypatch.setattr(updates, "write_text_atomic", fail_second)
    with pytest.raises(OSError, match="second file"):
        manager.apply_updates(plan)
    assert regular.read_bytes() == before
    assert (private.read_bytes() if private.exists() else None) == old_private


def test_rollback_preserves_foreign_change_and_both_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    regular = manager.writable_path("user")
    plan = manager.plan_updates(
        {"BATCH_SERVER": "new", "BATCH_PASSWORD": "new-private"}, scope="user"
    )
    original = updates.write_text_atomic

    def fail_second(path, text, *, private=False):
        if path == plan.edits[1].path:
            regular.write_bytes(b"# foreign edit\n")
            raise OSError("second write failure")
        return original(path, text, private=private)

    monkeypatch.setattr(updates, "write_text_atomic", fail_second)
    with pytest.raises(ExceptionGroup) as caught:
        manager.apply_updates(plan)
    assert regular.read_bytes() == b"# foreign edit\n"
    assert any(isinstance(error, OSError) for error in caught.value.exceptions)
    assert len(caught.value.exceptions) == 2


def test_external_change_between_writes_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    regular = manager.writable_path("user")
    private_path = manager.writable_path("user", secret=True)
    before = regular.read_bytes()
    plan = manager.plan_updates(
        {"BATCH_SERVER": "new", "BATCH_PASSWORD": "new-private"}, scope="user"
    )
    original = updates.write_text_atomic

    def mutate_next_file(path, text, *, private=False):
        result = original(path, text, private=private)
        private_path.write_bytes(b"# another writer\n")
        return result

    monkeypatch.setattr(updates, "write_text_atomic", mutate_next_file)
    with pytest.raises(StaleEditError):
        manager.apply_updates(plan)
    assert regular.read_bytes() == before
    assert private_path.read_bytes() == b"# another writer\n"
