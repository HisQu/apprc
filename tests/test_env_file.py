from __future__ import annotations

from pathlib import Path

import pytest

from apprc.definition.env_config.schema import ConfigField
from apprc.user_files.env_files import (
    ensure_workspace_dotenv_file,
    normalize_env_value,
    write_env_file,
)
from apprc.user_files.env_files.updates import (
    apply_env_file_edit,
    plan_env_file_value_removal,
    plan_env_file_value_update,
)
from apprc.user_files.workspace_roots.paths import WorkspaceRootPathError
from tests.support_config import (
    WORKSPACE_EXAMPLE_OWNER as APPRC_EXAMPLE_APP_OWNER,
)
from tests.support_config import (
    WORKSPACE_EXAMPLE_OWNERS as APPRC_EXAMPLE_APP_OWNERS,
)


def test_write_env_file_orders_known_keys_before_unknown_keys(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "apprc.workspace.env"

    write_env_file(
        env_path,
        {
            "Z_USER_EXTRA": "last",
            "APPRC_EXAMPLE_APP_RETRY_COUNT": "7",
            "A_USER_EXTRA": "first",
            "APPRC_EXAMPLE_APP_PROFILE": "local-profile",
        },
        owners=APPRC_EXAMPLE_APP_OWNERS,
    )

    assert env_path.read_bytes().decode("utf-8") == (
        'APPRC_EXAMPLE_APP_PROFILE="local-profile"\n'
        'APPRC_EXAMPLE_APP_RETRY_COUNT="7"\n'
        'A_USER_EXTRA="first"\n'
        'Z_USER_EXTRA="last"\n'
    )


def test_ensure_workspace_dotenv_file_creates_file_in_existing_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    path = ensure_workspace_dotenv_file(
        workspace_root,
        filename="apprc.workspace.env",
    )

    assert path == workspace_root.resolve() / "apprc.workspace.env"
    assert path.is_file()


def test_ensure_workspace_dotenv_file_rejects_missing_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"

    with pytest.raises(WorkspaceRootPathError):
        ensure_workspace_dotenv_file(
            workspace_root,
            filename="apprc.workspace.env",
        )


def test_removal_plan_missing_file_is_zero_write(tmp_path: Path) -> None:
    env_path = tmp_path / "apprc.user.env"

    plan = plan_env_file_value_removal(
        path=env_path,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )

    assert plan is None
    assert not env_path.exists()


def test_removal_plan_absent_key_preserves_existing_file(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "apprc.user.env"
    env_path.write_bytes(b'OTHER="value"\r\n')

    plan = plan_env_file_value_removal(
        path=env_path,
        reference="APPRC_EXAMPLE_APP_PROFILE",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )

    assert plan is None
    assert env_path.read_bytes() == b'OTHER="value"\r\n'


def test_edit_plan_preserves_unrelated_user_text(tmp_path: Path) -> None:
    env_path = tmp_path / "apprc.user.env"
    env_path.write_bytes(
        (
            "# Keep this explanation\r\n"
            "export APPRC_EXAMPLE_APP_PROFILE = old # active profile\r\n"
            "UNKNOWN='keep this quoting'\r\n"
            "\r\n"
            "APPRC_EXAMPLE_APP_PROFILE=stale\r\n"
            "BROKEN='unterminated\r\n"
        ).encode("utf-8")
    )

    original = env_path.read_bytes()
    plan = plan_env_file_value_update(
        path=env_path,
        reference="app.profile",
        raw_value="new profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )

    assert plan.text == (
        "# Keep this explanation\r\n"
        'export APPRC_EXAMPLE_APP_PROFILE = "new profile" # active profile\r\n'
        "UNKNOWN='keep this quoting'\r\n"
        "\r\n"
        "# AppRC disabled duplicate assignment: "
        "APPRC_EXAMPLE_APP_PROFILE=stale\r\n"
        "BROKEN='unterminated\r\n"
    )
    assert env_path.read_bytes() == original

    apply_env_file_edit(plan)
    assert env_path.read_bytes() == plan.text.encode("utf-8")


def test_edit_plan_comments_multiline_duplicate(tmp_path: Path) -> None:
    env_path = tmp_path / "apprc.user.env"
    env_path.write_text(
        "APPRC_EXAMPLE_APP_PROFILE=first\n"
        'APPRC_EXAMPLE_APP_PROFILE="old\nvalue" # duplicate\n',
        encoding="utf-8",
    )

    plan = plan_env_file_value_update(
        path=env_path,
        reference="app.profile",
        raw_value="new",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )
    apply_env_file_edit(plan)

    assert env_path.read_text(encoding="utf-8") == (
        'APPRC_EXAMPLE_APP_PROFILE="new"\n'
        "# AppRC disabled duplicate assignment: "
        'APPRC_EXAMPLE_APP_PROFILE="old\n'
        '# value" # duplicate\n'
    )


def test_removal_plan_removes_every_active_occurrence(tmp_path: Path) -> None:
    env_path = tmp_path / "apprc.user.env"
    env_path.write_text(
        "# profile settings\n"
        "APPRC_EXAMPLE_APP_PROFILE=first # remove with assignment\n"
        "\n"
        "KEEP=1\n"
        "# APPRC_EXAMPLE_APP_PROFILE=commented\n"
        "APPRC_EXAMPLE_APP_PROFILE=second\n",
        encoding="utf-8",
    )

    plan = plan_env_file_value_removal(
        path=env_path,
        reference="app.profile",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )

    assert plan is not None
    apply_env_file_edit(plan)

    assert env_path.read_text(encoding="utf-8") == (
        "# profile settings\n\nKEEP=1\n# APPRC_EXAMPLE_APP_PROFILE=commented\n"
    )


def test_edit_plan_appends_after_missing_final_newline(tmp_path: Path) -> None:
    env_path = tmp_path / "apprc.user.env"
    env_path.write_bytes(b"KEEP=1\r\nOTHER=2")

    plan = plan_env_file_value_update(
        path=env_path,
        reference="app.profile",
        raw_value="new",
        owners=APPRC_EXAMPLE_APP_OWNERS,
        layer_name="apprc.user.env",
    )
    apply_env_file_edit(plan)

    assert env_path.read_bytes().decode("utf-8") == (
        'KEEP=1\r\nOTHER=2\r\nAPPRC_EXAMPLE_APP_PROFILE="new"\r\n'
    )


def test_normalize_env_value_rejects_invalid_choices_and_bool() -> None:
    mode = APPRC_EXAMPLE_APP_OWNER.field("mode")
    enabled = APPRC_EXAMPLE_APP_OWNER.field("enabled")

    with pytest.raises(ValueError):
        normalize_env_value(mode, "OTHER")
    with pytest.raises(ValueError):
        normalize_env_value(enabled, "maybe")


def test_normalize_env_value_uses_runtime_converter_for_float() -> None:
    ratio = ConfigField("ratio", "RATIO", float, default=0.5)

    assert normalize_env_value(ratio, "1") == "1.0"

    with pytest.raises(ValueError):
        normalize_env_value(ratio, "nope")
