from __future__ import annotations

from _example_apps_utils import example_app, example_app_specs
from cache_only.config.app import MyRC as CACHE_ONLY_RC


def test_example_app_registry_exposes_all_installed_commands() -> None:
    """Keep lab and smoke-runner command discovery in one registry."""
    specs = example_app_specs()
    names = {spec.name for spec in specs}

    assert names == {
        "cache-only",
        "cli-runtime",
        "library-client",
        "explicit-env-precedence",
        "process-env",
        "workspace",
        "user-dotenv",
        "user-dotenv-with-workspace",
    }
    assert {spec.command_name for spec in specs} == {
        "apprc-cache-only",
        "apprc-cli-runtime",
        "apprc-library-client",
        "apprc-explicit-env-precedence",
        "apprc-process-env",
        "apprc-workspace",
        "apprc-user-dotenv",
        "apprc-user-dotenv-with-workspace",
    }
    assert example_app("process-env").uses_user_dotenv is False
    assert example_app("process-env").uses_workspace is False
    assert example_app("user-dotenv").uses_user_dotenv is True
    assert example_app("user-dotenv").uses_workspace is False
    assert example_app("library-client").uses_user_dotenv is True
    assert example_app("library-client").uses_workspace is False
    assert example_app("workspace").uses_user_dotenv is False
    assert example_app("workspace").uses_workspace is True
    assert example_app("user-dotenv-with-workspace").uses_user_dotenv is True
    assert example_app("user-dotenv-with-workspace").uses_workspace is True
    assert all(spec.app_id and spec.root_env_key for spec in specs)
    cache_only = example_app("cache-only")
    assert cache_only.uses_user_dotenv is False
    assert cache_only.uses_workspace is False

    assert CACHE_ONLY_RC.schema.paths.cache is True
    assert CACHE_ONLY_RC.schema.paths.config is False
    assert CACHE_ONLY_RC.schema.paths.appdata is False
    assert CACHE_ONLY_RC.schema.paths.state is False
    assert CACHE_ONLY_RC.schema.owners == ()
    assert CACHE_ONLY_RC.schema.user_dotenv is None
    assert CACHE_ONLY_RC.schema.workspaces is None
