"""Noninteractive operations use captured inputs and preserve managed files."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import apprc as rc
from apprc.user_files.app_home.locations import (
    AppRCDirectoryError,
    write_text_atomic,
)
from apprc.user_files.app_home.writes import StaleEditError


def declare_app(tmp_path: Path, *, storage: bool = False):
    """Register fields for management checks without requiring runtime validity."""
    app = rc.AppRC(
        app_id="management-test",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage() if storage else None,
        apprc_dir=tmp_path / "managed",
    )

    @app.config("settings", prefix="MANAGE_")
    class Settings(rc.Config):
        value: str = rc.field("MANAGE_VALUE", default="fallback")
        count: int = rc.field("MANAGE_COUNT", default=1)

    return app, Settings


def test_planning_is_zero_write_and_tracks_absence(tmp_path):
    app, _ = declare_app(tmp_path)
    manager = app.manage(environment={})
    inspected = manager.inspect()
    assert inspected.ready
    assert inspected.fields[0].display_value == "fallback"
    plan = manager.plan_update("value", "planned", scope="user")
    assert list(tmp_path.iterdir()) == []
    manager.setup()
    with pytest.raises(StaleEditError) as conflict:
        manager.apply_edit(plan)
    assert conflict.value.expected_revision is None
    assert manager.paths.user_dotenv.read_text() == ""


def test_concurrent_plans_do_not_overwrite_each_other(tmp_path):
    app, _ = declare_app(tmp_path)
    manager = app.manage(environment={})
    manager.setup()
    plans = [
        manager.plan_update("value", value, scope="user")
        for value in ("first", "second")
    ]

    def apply(plan):
        try:
            return manager.apply_edit(plan).value
        except StaleEditError:
            return "conflict"

    with ThreadPoolExecutor() as pool:
        results = list(pool.map(apply, plans))
    assert results.count("conflict") == 1
    assert manager.inspect().fields[0].value in {"first", "second"}


def test_removal_plan_preserves_comments_and_detects_staleness(tmp_path):
    app, _ = declare_app(tmp_path)
    manager = app.manage(environment={})
    manager.setup()
    path = manager.paths.user_dotenv
    path.write_bytes(b"# keep\r\nMANAGE_VALUE=first\r\nMANAGE_VALUE=last\r\n")
    plan = manager.plan_removal("value", scope="user")
    assert plan is not None
    path.write_bytes(path.read_bytes() + b"# external\r\n")
    with pytest.raises(StaleEditError):
        manager.apply_edit(plan)
    replacement = manager.plan_removal("value", scope="user")
    assert replacement is not None
    manager.apply_edit(replacement)
    assert path.read_bytes().startswith(b"# keep\r\n")
    assert b"# external\r\n" in path.read_bytes()
    assert manager.inspect().fields[0].value == "fallback"


def test_failed_atomic_replace_cleans_unique_temporary_file(
    tmp_path, monkeypatch
):
    target = tmp_path / "apprc.user.env"
    target.write_text("original")
    observed = []

    def fail_replace(self, destination):
        observed.append(self)
        raise OSError("replacement failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    for _ in range(2):
        with pytest.raises(AppRCDirectoryError, match="replacement failed"):
            write_text_atomic(target, "replacement")
    assert observed[0] != observed[1]
    assert list(tmp_path.iterdir()) == [target]
    assert target.read_text() == "original"


def test_inspection_includes_explicit_files_and_keeps_selection_separate(
    tmp_path,
):
    app, Settings = declare_app(tmp_path, storage=True)
    manager = app.manage(environment={})
    first, second = tmp_path / "first", tmp_path / "second"
    manager.setup(storage_root=first, storage_name="first")
    manager.register_storage("second", second)
    manager.apply_edit(
        manager.plan_update(
            "value", "second", scope="storage", storage="second"
        )
    )
    runtime = manager.resolve()
    inspected = manager.inspect(storage="second")
    assert inspected.fields[0].value == "second"
    assert manager.registry().selected_storage == "first"
    assert (
        runtime.selection is not None
        and runtime.selection.storage_name == "first"
    )
    assert runtime.build(Settings).value == "fallback"
    explicit = tmp_path / "run.env"
    explicit.write_text("MANAGE_VALUE=explicit\n")
    overridden = app.manage(
        rc.ResolveOptions(storage="second", env_files=(explicit,)),
        environment={},
    )
    state = overridden.inspect().fields[0]
    assert state.value == "explicit"
    assert state.origin.path == explicit
    plan = overridden.plan_update("value", "saved-later", scope="storage")
    assert overridden.preview_edit(plan).fields[0].value == "explicit"
    assert manager.inspect(storage="second").fields[0].value == "second"


def test_missing_storage_and_invalid_values_remain_inspectable(tmp_path):
    app, _ = declare_app(tmp_path, storage=True)
    manager = app.manage(
        rc.ResolveOptions(storage_required=True),
        environment={"MANAGE_COUNT": "bad"},
    )
    inspected = manager.inspect()
    assert not inspected.ready
    assert len(inspected.issues) == 2
    assert "bad" not in repr(inspected)
    assert list(tmp_path.iterdir()) == []
    manager.setup(storage_root=tmp_path / "first")
    assert len(manager.inspect().issues) == 1


def test_manager_captures_directory_without_environment_mutation(
    tmp_path, monkeypatch
):
    app, _ = declare_app(tmp_path)
    override = tmp_path / "override"
    monkeypatch.setenv("MANAGEMENT_TEST_APPRC_DIR", str(tmp_path / "ambient"))
    before = dict(os.environ)
    manager = app.manage(rc.ResolveOptions(apprc_dir=override), environment={})
    manager.setup()
    assert manager.paths.root == override
    assert dict(os.environ) == before


def test_core_operations_do_not_import_terminal_libraries(tmp_path):
    script = """
import importlib.abc
import sys
from pathlib import Path

class NoTerminal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"typer", "textual", "rich", "prompt_toolkit"}:
            raise AssertionError("Terminal import: " + fullname)

sys.meta_path.insert(0, NoTerminal())
import apprc as rc
app = rc.AppRC(app_id="core-test", user_dotenv=rc.UserDotenv(), apprc_dir=Path(sys.argv[1]))
@app.config("settings", prefix="CORE_")
class Settings(rc.Config):
    value: str = rc.field("CORE_VALUE", default="default")
manager = app.manage(environment={})
assert manager.inspect().ready
manager.setup()
manager.apply_edit(manager.plan_update("value", "saved", scope="user"))
assert manager.resolve().build(Settings).value == "saved"
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "core")],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_setup_does_not_recreate_a_missing_registered_root(
    tmp_path: Path,
) -> None:
    """Repeated setup cannot silently replace data that was moved elsewhere."""
    import shutil

    app = rc.AppRC(
        app_id="missing_root",
        storage=rc.Storage(),
        apprc_dir=tmp_path / "config",
    )
    manager = app.manage(environment={})
    root = tmp_path / "data"
    manager.setup(storage_root=root)
    shutil.rmtree(root)
    with pytest.raises(rc.files.ConfigSetupError, match="does not exist"):
        manager.setup(storage_root=root)
    assert not root.exists()
    assert manager.registry().selected("default").root == root


def test_missing_explicit_source_can_be_inspected_but_not_resolved(
    tmp_path: Path,
) -> None:
    """Repair clients see the source failure without falling back silently."""
    app = rc.AppRC(app_id="missing_source")
    manager = app.manage(
        rc.ResolveOptions(env_files=(tmp_path / "absent.env",)), environment={}
    )
    assert not manager.inspect().ready
    with pytest.raises(FileNotFoundError):
        manager.resolve()
