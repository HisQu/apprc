from __future__ import annotations

from _example_apps_utils import example_app_specs, example_kits


def test_example_app_registry_exposes_all_dev_kits() -> None:
    """Keep dev-only example kit discovery out of maintainer scripts."""
    specs = example_app_specs()
    names = {spec.name for spec in specs}

    assert names == {
        "cli_runtime",
        "config_only",
        "explicit_env_precedence",
        "config_with_storage",
    }
    assert set(example_kits()) == names
    assert all(spec.kit.spec.app_id for spec in specs)
