"""Managed user settings keep secret values in private companions."""

from __future__ import annotations

from pathlib import Path

import apprc as rc


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
