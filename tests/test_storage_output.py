from __future__ import annotations

from pathlib import Path

from apprc.cli.storage_output import storage_list_payload
from apprc.config.storage_registry import register_storage


def test_storage_list_payload_reports_local_env_status(tmp_path: Path) -> None:
    registry_path = tmp_path / "config" / "demo_apprc.toml"
    alpha_root = tmp_path / "alpha"
    beta_root = tmp_path / "beta"
    register_storage(
        name="beta",
        root=beta_root,
        make_default=False,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    registry = register_storage(
        name="alpha",
        root=alpha_root,
        make_default=True,
        path=registry_path,
        local_env_filename=".env.demo",
    )

    payload = storage_list_payload(registry, local_env_filename=".env.demo")

    assert payload["default_storage"] == "alpha"
    assert payload["storages"] == [
        {
            "default": True,
            "local_env": str(alpha_root.resolve() / ".env.demo"),
            "local_env_exists": True,
            "name": "alpha",
            "root": str(alpha_root.resolve()),
            "root_exists": True,
        },
        {
            "default": False,
            "local_env": str(beta_root.resolve() / ".env.demo"),
            "local_env_exists": True,
            "name": "beta",
            "root": str(beta_root.resolve()),
            "root_exists": True,
        },
    ]
