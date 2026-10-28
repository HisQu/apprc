"""Application declarations retain immutable path and workspace contracts."""

from __future__ import annotations

from itertools import product

import pytest

import apprc as rc
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.paths import Layout, Paths

_DUPLICATE_OWNER_A_RC = rc.AppRC(app_id="duplicate_owner_a")


@_DUPLICATE_OWNER_A_RC.config(
    "duplicate", prefix="DUPLICATE_OWNER_A_", title="Duplicate Owner A"
)
class _DuplicateOwnerA(rc.Config):
    value: str = rc.field("DUPLICATE_OWNER_A_VALUE", default="a")


_DUPLICATE_OWNER_B_RC = rc.AppRC(app_id="duplicate_owner_b")


@_DUPLICATE_OWNER_B_RC.config(
    "duplicate", prefix="DUPLICATE_OWNER_B_", title="Duplicate Owner B"
)
class _DuplicateOwnerB(rc.Config):
    value: str = rc.field("DUPLICATE_OWNER_B_VALUE", default="b")


_DUPLICATE_ENV_A_RC = rc.AppRC(app_id="duplicate_env_a")


@_DUPLICATE_ENV_A_RC.config("first", prefix="DUPLICATE_ENV_")
class _DuplicateEnvA(rc.Config):
    value: str = rc.field("DUPLICATE_ENV_VALUE", default="a")


_DUPLICATE_ENV_B_RC = rc.AppRC(app_id="duplicate_env_b")


@_DUPLICATE_ENV_B_RC.config("second", prefix="DUPLICATE_ENV_")
class _DuplicateEnvB(rc.Config):
    value: str = rc.field("DUPLICATE_ENV_VALUE", default="b")


def _spec(
    *,
    paths: Paths = Paths(),
    layout: Layout | None = None,
    user_dotenv: UserDotenv | None = None,
    workspaces: Workspaces | None = None,
) -> AppConfigSpec:
    return AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        config_package="apprc",
        paths=paths,
        layout=layout,
        user_dotenv=user_dotenv,
        workspaces=workspaces,
    )


def test_app_config_spec_defaults_to_no_optional_capabilities() -> None:
    spec = _spec()

    assert spec.paths == Paths()
    assert spec.layout is None
    assert spec.user_dotenv is None
    assert spec.workspaces is None
    assert spec.workspace_selector_env_key is None
    assert spec.workspace_dotenv_filename == "apprc.workspace.env"
    assert spec.apprc_toml_filename == "apprc.toml"


def test_app_config_spec_keeps_setup_next_step() -> None:
    spec = AppConfigSpec(
        app_id="demo",
        display_name="Demo",
        setup_next_step="demo run",
    )

    assert spec.setup_next_step == "demo run"


@pytest.mark.parametrize(
    "paths",
    [
        Paths(config=config, appdata=appdata, cache=cache, state=state)
        for config, appdata, cache, state in product((False, True), repeat=4)
    ],
)
def test_app_config_spec_preserves_independent_path_capabilities(
    paths: Paths,
) -> None:
    assert _spec(paths=paths).paths == paths


def test_app_config_spec_derives_workspace_selector_from_app_identity() -> None:
    spec = _spec(
        paths=Paths(config=True),
        workspaces=Workspaces(),
    )

    assert spec.uses_workspaces() is True
    assert spec.workspace_selector_env_key == "DEMO_WORKSPACE"
    assert spec.require_workspaces() == Workspaces()


def test_app_config_spec_keeps_explicit_workspace_selector() -> None:
    spec = _spec(
        paths=Paths(config=True),
        workspaces=Workspaces(selector_env_key="CUSTOM_WORKSPACE"),
    )

    assert spec.workspace_selector_env_key == "CUSTOM_WORKSPACE"


def test_direct_workspaces_do_not_require_config_capability() -> None:
    spec = _spec(workspaces=Workspaces(registry=False))

    assert spec.uses_workspaces() is True
    assert spec.paths.config is False


def test_registry_workspaces_require_config_capability() -> None:
    with pytest.raises(
        ValueError, match="Registry-backed workspaces require paths.config=True"
    ):
        _spec(workspaces=Workspaces())


def test_user_dotenv_requires_config_capability() -> None:
    with pytest.raises(
        ValueError, match="UserDotenv requires paths.config=True"
    ):
        _spec(user_dotenv=UserDotenv())


def test_layout_declaration_is_preserved() -> None:
    layout = Layout.single_root("relative-root")

    assert _spec(layout=layout).layout == layout
    assert layout.root is not None
    assert layout.root.is_absolute()


def test_app_config_spec_rejects_manual_owner_argument() -> None:
    with pytest.raises(TypeError, match="owners"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            owners=(),  # pyright: ignore[reportCallIssue]
        )


def test_app_config_spec_rejects_duplicate_owner_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate owner key"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            envs=(_DuplicateOwnerA, _DuplicateOwnerB),
        )


def test_app_config_spec_rejects_duplicate_env_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate env key"):
        AppConfigSpec(
            app_id="demo",
            display_name="Demo",
            envs=(_DuplicateEnvA, _DuplicateEnvB),
        )


def test_app_config_spec_rejects_invalid_application_identity() -> None:
    with pytest.raises(ValueError, match="safe nonempty filename segment"):
        _spec().__class__(app_id="../demo", display_name="Demo")
