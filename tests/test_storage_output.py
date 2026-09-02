from __future__ import annotations

from pathlib import Path

from apprc.interfaces.cli.config_command._output import storage_list_payload
from apprc.user_files.storage_roots.registry import register_storage


def test_storage_list_payload_reports_storage_env_status(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "config" / "demo.apprc.toml"
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    register_storage(
        name="beta",
        root=beta_root,
        path=index_path,
        storage_env_filename=".env.demo",
    )
    registry = register_storage(
        name="alpha",
        root=alpha_root,
        path=index_path,
        storage_env_filename=".env.demo",
    )

    payload = storage_list_payload(
        registry,
        storage_env_filename=".env.demo",
        active_storage_root=alpha_root,
    )

    assert payload["apprc_toml"] == str(index_path)
    assert payload["storages"] == [
        {
            "active": True,
            "name": "alpha",
            "root": str(alpha_root.resolve()),
            "root_exists": True,
            "storage_env": str(alpha_root.resolve() / ".env.demo"),
            "storage_env_exists": True,
        },
        {
            "active": False,
            "name": "beta",
            "root": str(beta_root.resolve()),
            "root_exists": True,
            "storage_env": str(beta_root.resolve() / ".env.demo"),
            "storage_env_exists": True,
        },
    ]
