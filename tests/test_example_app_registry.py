from __future__ import annotations

from _example_apps_utils import example_app_specs, example_kits


def test_example_app_registry_exposes_all_dev_kits() -> None:
    """Keep dev-only example kit discovery out of maintainer scripts."""
    specs = example_app_specs()
    names = {spec.name for spec in specs}

    assert names == {
        "app_wide_config",
        "app_wide_storage",
        "cli_runtime",
        "env_only",
        "explicit_env_precedence",
        "storage_only",
    }
    assert set(example_kits()) == names
    assert all(spec.kit.spec.app_name for spec in specs)
