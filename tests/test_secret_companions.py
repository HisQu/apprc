"""Managed secret companions and explicit migration behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import apprc as rc
from apprc.interfaces.cli.diagnostics.payload import build_config_doctor_payload


def _app(tmp_path: Path) -> rc.AppRC:
    """Declare one editable secret and one ordinary field."""
    app = rc.AppRC(
        app_id="secret-example",
        user_dotenv=rc.UserDotenv(),
        storage=rc.Storage(selector_env_key="DEMO_STORAGE"),
        apprc_dir=tmp_path / "config",
    )

    @app.config("client", prefix="DEMO_")
    class Client(rc.Config):
        token: str = rc.field("DEMO_TOKEN", default="", secret=True)
        label: str = rc.field("DEMO_LABEL", default="default")

    return app


def test_secret_companions_follow_layer_precedence(tmp_path: Path) -> None:
    app = _app(tmp_path)
    manager = app.manage(environment={})
    manager.setup(storage_root=tmp_path / "data")

    user = manager.plan_update("DEMO_TOKEN", "user-key", scope="user")
    manager.apply_edit(user)
    storage = manager.plan_update("DEMO_TOKEN", "storage-key", scope="storage")
    manager.apply_edit(storage)

    assert user.path.name == "apprc.user.secret.env"
    assert storage.path.name == "apprc.storage.secret.env"
    assert "DEMO_TOKEN" not in manager.writable_path("user").read_text()
    assert manager.resolve().values["DEMO_TOKEN"] == "storage-key"
    assert manager.resolve().source.origins["DEMO_TOKEN"].path == storage.path
    assert (
        app.manage(environment={"DEMO_TOKEN": "shell-key"})
        .resolve()
        .values["DEMO_TOKEN"]
        == "shell-key"
    )


def test_legacy_secret_migration_is_explicit_and_archive_excludes_secret(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    manager = app.manage(environment={})
    manager.setup(storage_root=tmp_path / "data")
    ordinary = manager.writable_path("storage")
    ordinary.write_text(
        'DEMO_TOKEN="legacy-key"\n'
        '# AppRC disabled duplicate assignment: DEMO_TOKEN="old-key"\n'
        '# DEMO_TOKEN="commented-key"\n'
        '# AppRC disabled duplicate assignment: DEMO_TOKEN="older\n'
        '# multiline-key"\n'
        'DEMO_LABEL="safe"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="secrets migrate"):
        manager.plan_update("DEMO_TOKEN", "replacement", scope="storage")
    doctor = build_config_doctor_payload(app, storage=None, manager=manager)
    assert "legacy-key" not in str(doctor.to_payload())
    assert any("secrets migrate" in step for step in doctor.next_steps)

    plan = manager.plan_secret_migration("storage")
    assert plan.keys == ("DEMO_TOKEN",)
    assert "legacy-key" not in repr(plan)
    manager.apply_secret_migration(plan)
    assert "DEMO_TOKEN" not in ordinary.read_text()
    assert "multiline-key" not in ordinary.read_text()
    assert 'DEMO_LABEL="safe"' in ordinary.read_text()
    assert manager.resolve().values["DEMO_TOKEN"] == "legacy-key"

    archive = manager.archive_storage("default", tmp_path / "data.apprc.tar.xz")
    import tarfile

    with tarfile.open(archive, "r:xz") as stream:
        assert "apprc.storage.secret.env" not in stream.getnames()

    user_secret = manager.writable_path("user", secret=True)
    storage_secret = manager.writable_path("storage", secret=True)
    manager.apply_purge(manager.plan_purge())
    assert not user_secret.exists()
    assert not storage_secret.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode check")
def test_shared_storage_disables_secret_saving_without_disabling_storage(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    manager = app.manage(environment={})
    manager.setup(storage_root=tmp_path / "data")
    (tmp_path / "data").chmod(0o755)

    assert not manager.secret_status("storage").available
    manager.apply_edit(
        manager.plan_update("DEMO_LABEL", "ordinary", scope="storage")
    )
    with pytest.raises(ValueError, match="readable by other users"):
        manager.plan_update("DEMO_TOKEN", "private", scope="storage")
    assert manager.repair_secret_permissions("storage").available
    manager.apply_edit(
        manager.plan_update("DEMO_TOKEN", "private", scope="storage")
    )
