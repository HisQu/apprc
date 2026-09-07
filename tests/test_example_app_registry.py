from __future__ import annotations

from _example_apps_utils import example_app, example_app_specs


def test_example_app_registry_exposes_all_installed_commands() -> None:
    """Keep lab and smoke-runner command discovery in one registry."""
    specs = example_app_specs()
    names = {spec.name for spec in specs}

    assert names == {
        "cli-runtime",
        "explicit-env-precedence",
        "process-env",
        "storage",
        "user-dotenv",
        "user-dotenv-with-storage",
    }
    assert {spec.command_name for spec in specs} == {
        "apprc-cli-runtime",
        "apprc-explicit-env-precedence",
        "apprc-process-env",
        "apprc-storage",
        "apprc-user-dotenv",
        "apprc-user-dotenv-with-storage",
    }
    assert example_app("process-env").uses_user_dotenv is False
    assert example_app("process-env").uses_storage is False
    assert example_app("user-dotenv").uses_user_dotenv is True
    assert example_app("user-dotenv").uses_storage is False
    assert example_app("storage").uses_user_dotenv is False
    assert example_app("storage").uses_storage is True
    assert example_app("user-dotenv-with-storage").uses_user_dotenv is True
    assert example_app("user-dotenv-with-storage").uses_storage is True
    assert all(spec.app_id and spec.apprc_dir_env_key for spec in specs)
