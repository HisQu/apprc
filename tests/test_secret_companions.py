"""Managed user settings keep secret values in private companions."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import apprc as rc
from apprc.user_files.env_files.secrets import inspect_secret_file


def test_user_settings_save_reload_keeps_secret_in_private_companion(
    tmp_path: Path,
) -> None:
    app = rc.AppRC(
        app_id="secret-example",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "app"),
        user_dotenv=rc.UserDotenv(),
    )

    @app.config("client", prefix="DEMO_")
    class Client(rc.Config):
        token: str = rc.field("DEMO_TOKEN", default="", secret=True)
        label: str = rc.field("DEMO_LABEL", default="default")

    manager = app.manage(environment={})
    manager.setup()
    manager.apply_edit(
        manager.plan_update("DEMO_TOKEN", "private-token", scope="user")
    )
    manager.apply_edit(
        manager.plan_update("DEMO_LABEL", "saved-label", scope="user")
    )

    resolved = app.resolve(environment={})
    config = resolved.build(Client)
    secret_path = manager.writable_path("user", secret=True)
    ordinary_path = manager.writable_path("user")

    assert config.token == "private-token"
    assert config.label == "saved-label"
    assert secret_path.name == "apprc.user.secret.env"
    assert "DEMO_TOKEN" in secret_path.read_text(encoding="utf-8")
    assert "DEMO_TOKEN" not in ordinary_path.read_text(encoding="utf-8")
    status = manager.secret_status("user")
    assert status.available
    assert status.reason is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX private-file modes")
@pytest.mark.parametrize(
    "reason",
    (
        "parent_missing",
        "parent_not_directory",
        "parent_not_private",
        "secret_not_file",
        "secret_not_private",
    ),
)
def test_secret_status_classifies_filesystem_failures_without_mutation(
    tmp_path: Path, reason: str
) -> None:
    parent = tmp_path / "config"
    secret = parent / "secret.env"
    if reason == "parent_not_directory":
        parent.write_text("retained parent", encoding="utf-8")
    elif reason != "parent_missing":
        parent.mkdir(mode=0o700)
        parent.chmod(0o755 if reason == "parent_not_private" else 0o700)
        if reason == "secret_not_file":
            secret.mkdir()
        elif reason == "secret_not_private":
            secret.write_text("retained secret", encoding="utf-8")
            secret.chmod(0o644)
    parent_mode = parent.stat().st_mode if parent.exists() else None
    secret_mode = secret.stat().st_mode if secret.exists() else None

    status = inspect_secret_file(secret)

    assert not status.available
    assert status.reason == reason
    assert (parent.stat().st_mode if parent.exists() else None) == parent_mode
    assert (secret.stat().st_mode if secret.exists() else None) == secret_mode
    if reason == "parent_not_directory":
        assert parent.read_text(encoding="utf-8") == "retained parent"
    elif reason == "secret_not_private":
        assert secret.read_text(encoding="utf-8") == "retained secret"
