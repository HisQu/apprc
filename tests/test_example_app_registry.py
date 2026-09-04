from __future__ import annotations

from _example_apps_utils import example_app, example_app_specs


def test_example_app_registry_exposes_all_installed_commands() -> None:
    """Keep lab and smoke-runner command discovery in one registry."""
    specs = example_app_specs()
    names = {spec.name for spec in specs}

    assert names == {
        "cli-runtime",
        "config-only",
        "explicit-env-precedence",
        "config-with-storage",
    }
    assert {spec.command_name for spec in specs} == {
        "apprc-cli-runtime",
        "apprc-config-only",
        "apprc-config-with-storage",
        "apprc-explicit-env-precedence",
    }
    assert example_app("config-only").uses_storage is False
    assert example_app("config-with-storage").uses_storage is True
    assert all(spec.app_id and spec.apprc_dir_env_key for spec in specs)
