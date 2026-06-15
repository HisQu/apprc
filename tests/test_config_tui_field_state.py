from __future__ import annotations

from apprc.config.tui.field_state import (
    config_value_sources,
    selected_field_for_row,
)
from tests.support_config import (
    APPRC_EXAMPLE_APP_OWNER,
    APPRC_EXAMPLE_APP_OWNERS,
)


def test_selected_field_for_row_ignores_non_field_rows() -> None:
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
            row_index=None,
        )
        is None
    )
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=[None],
            row_index=0,
        )
        is None
    )
    assert (
        selected_field_for_row(
            owners=APPRC_EXAMPLE_APP_OWNERS,
            row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
            row_index=10,
        )
        is None
    )


def test_selected_field_for_row_resolves_known_env_key() -> None:
    selected = selected_field_for_row(
        owners=APPRC_EXAMPLE_APP_OWNERS,
        row_env_keys=["APPRC_EXAMPLE_APP_PROFILE"],
        row_index=0,
    )

    assert selected is not None
    assert selected.spec.name == "profile"
    assert selected.owner.env_key("profile") == "APPRC_EXAMPLE_APP_PROFILE"


def test_config_value_sources_prefer_shell_over_local_and_shared() -> None:
    profile = APPRC_EXAMPLE_APP_OWNER.field("profile")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("profile")

    sources = config_value_sources(
        spec=profile,
        env_key=env_key,
        local_values={env_key: "local-profile"},
        shell_env={env_key: "shell-profile"},
        shared_values={env_key: "shared-profile"},
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["effective"].raw_value == "shell-profile"
    assert sources_by_key["effective"].origin_key == "shell"
    assert sources_by_key["shell"].raw_value == "shell-profile"
    assert sources_by_key["local"].raw_value == "local-profile"
    assert sources_by_key["shared"].raw_value == "shared-profile"


def test_config_value_sources_keep_empty_local_values_copyable() -> None:
    profile = APPRC_EXAMPLE_APP_OWNER.field("profile")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("profile")

    sources = config_value_sources(
        spec=profile,
        env_key=env_key,
        local_values={env_key: ""},
        shell_env={},
        shared_values={env_key: "shared-profile"},
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["effective"].raw_value == ""
    assert sources_by_key["effective"].origin_key == "local"
    assert sources_by_key["local"].raw_value == ""
    assert sources_by_key["local"].is_available is True


def test_config_value_sources_disable_missing_required_values() -> None:
    access_token = APPRC_EXAMPLE_APP_OWNER.field("access_token")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("access_token")

    sources = config_value_sources(
        spec=access_token,
        env_key=env_key,
        local_values={},
        shell_env={},
        shared_values={},
    )

    assert all(not source.is_available for source in sources)


def test_config_value_sources_fall_back_to_declared_shared_default() -> None:
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")
    env_key = APPRC_EXAMPLE_APP_OWNER.env_key("enabled")

    sources = config_value_sources(
        spec=enabled,
        env_key=env_key,
        local_values={},
        shell_env={},
        shared_values=None,
    )
    sources_by_key = {source.key: source for source in sources}

    assert sources_by_key["shared"].raw_value == "true"
    assert sources_by_key["effective"].raw_value == "true"
    assert sources_by_key["effective"].origin_key == "shared"
