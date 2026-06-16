from __future__ import annotations

from pathlib import Path

from apprc.cli.config.output import storage_list_payload
from apprc.config.storage.registry import register_storage


def test_storage_list_payload_reports_local_env_status(tmp_path: Path) -> None:
    apprc_toml_path = tmp_path / "config" / "demo.apprc.toml"
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    register_storage(
        name="beta",
        root=beta_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    registry = register_storage(
        name="alpha",
        root=alpha_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )

    payload = storage_list_payload(
        registry,
        local_env_filename=".env.demo",
        active_storage_root=alpha_root,
    )

    assert payload["apprc_toml_path"] == str(apprc_toml_path)
    assert payload["storages"] == [
        {
            "active": True,
            "local_env": str(alpha_root.resolve() / ".env.demo"),
            "local_env_exists": True,
            "name": "alpha",
            "root": str(alpha_root.resolve()),
            "root_exists": True,
        },
        {
            "active": False,
            "local_env": str(beta_root.resolve() / ".env.demo"),
            "local_env_exists": True,
            "name": "beta",
            "root": str(beta_root.resolve()),
            "root_exists": True,
        },
    ]
