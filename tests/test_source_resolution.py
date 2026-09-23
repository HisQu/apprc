from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

import json
import os
from pathlib import Path

import pytest

from apprc import AppRC, ResolveOptions
from tests.support_declaration import app_from_envs
from apprc.definition.app_config.storage import Storage
from apprc.definition.app_config.user_dotenv import UserDotenv
from apprc.user_files.env_files import write_env_file
from apprc.user_files.storage_roots.registry import register_storage
from apprc.user_files.storage_roots.selector import StorageSelectorError
from apprc.user_files.storage_roots.selector import (
    MissingStorageSelectorError,
)
from tests.support_config import ApprcExampleAppEnv


@pytest.fixture(autouse=True)
def _clear_example_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove process values written by previous bootstrap tests."""
    for key in tuple(os.environ):
        if key.startswith("APPRC_EXAMPLE_APP_"):
            monkeypatch.delenv(key, raising=False)


def _kit(tmp_path: Path) -> AppRC:
    """Return an isolated storage-capable application declaration."""
    return app_from_envs(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="user_dotenv_with_storage.config",
        envs=(ApprcExampleAppEnv,),
        user_dotenv=UserDotenv(),
        storage=Storage(selector_env_key="APPRC_EXAMPLE_APP_STORAGE"),
        apprc_dir=tmp_path / "apprc",
    )


def _optional_kit(tmp_path: Path) -> AppRC:
    """Return a declaration whose managed layers are opt-in at runtime."""
    return app_from_envs(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="user_dotenv_with_storage.config",
        envs=(ApprcExampleAppEnv,),
        user_dotenv=UserDotenv(),
        storage=Storage(
            selector_env_key="APPRC_EXAMPLE_APP_STORAGE",
        ),
        apprc_dir=tmp_path / "apprc",
    )


def _register(kit: AppRC, *, name: str, root: Path) -> None:
    """Register one test storage using the application's fixed files."""
    register_storage(
        name=name,
        root=root,
        path=AppFiles(kit.schema).preferred_apprc_toml_path(),
        storage_dotenv_filename=kit.schema.storage_dotenv_filename,
    )


def test_resolution_associates_registered_path_selector(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    _register(kit, name="default", root=root)

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(root),
        )
    )

    assert result.selection is not None
    assert result.selection.selector_kind == "path"
    assert result.selection is not None
    assert result.selection.storage_name == "default"
    assert result.selection is not None
    assert result.selection.root == root.resolve()


def test_resolution_uses_initialized_unregistered_path_without_registry(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "unregistered"
    root.mkdir()
    AppFiles(kit.schema).storage_dotenv_path(root).write_text(
        "", encoding="utf-8"
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(root),
        )
    )

    assert result.selection is not None
    assert result.selection.selector_kind == "path"
    assert result.selection is not None
    assert result.selection.storage_name is None
    assert result.selection is not None
    assert result.selection.root == root.resolve()
    assert result.storage_count == 0
    assert not AppFiles(kit.schema).preferred_apprc_toml_path().exists()


def test_resolution_resolves_relative_path_from_apprc_toml(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    root.mkdir()
    AppFiles(kit.schema).storage_dotenv_path(root).write_text(
        "", encoding="utf-8"
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="../storage",
        )
    )

    assert result.selection is not None
    assert result.selection.root == root.resolve()


def test_resolution_rejects_path_without_storage_dotenv(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "uninitialized"
    root.mkdir()

    with pytest.raises(
        StorageSelectorError, match="missing.*apprc.storage.env"
    ):
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=str(root),
            )
        )


def test_resolution_uses_direct_path_when_registry_is_invalid(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    root.mkdir()
    AppFiles(kit.schema).storage_dotenv_path(root).write_text(
        "", encoding="utf-8"
    )
    registry = AppFiles(kit.schema).preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text("invalid = true\n", encoding="utf-8")

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(root),
        )
    )

    assert result.selection is not None
    assert result.selection.root == root.resolve()
    assert result.selection is not None
    assert result.selection.storage_name is None


def test_optional_managed_layers_can_be_absent_without_writes(
    tmp_path: Path,
) -> None:
    kit = _optional_kit(tmp_path)
    explicit = tmp_path / "run.env"
    explicit.write_text(
        "APPRC_EXAMPLE_APP_PROFILE=explicit\n",
        encoding="utf-8",
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(explicit,),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is None
    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "explicit"
    assert not AppFiles(kit.schema).apprc_dir().exists()


def test_optional_storage_is_loaded_when_selected(tmp_path: Path) -> None:
    kit = _optional_kit(tmp_path)
    storage_root = tmp_path / "storage"
    _register(kit, name="default", root=storage_root)
    AppFiles(kit.schema).storage_dotenv_path(storage_root).write_text(
        "APPRC_EXAMPLE_APP_PROFILE=storage\n",
        encoding="utf-8",
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "default"
    assert result.selection is not None
    assert result.selection.root == storage_root.resolve()
    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "storage"


def test_runtime_can_require_optional_storage(tmp_path: Path) -> None:
    kit = _optional_kit(tmp_path)

    kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )
    with pytest.raises(MissingStorageSelectorError):
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=None,
                storage_required=True,
            )
        )


def test_optional_storage_rejects_invalid_explicit_selector(
    tmp_path: Path,
) -> None:
    kit = _optional_kit(tmp_path)
    _register(kit, name="default", root=tmp_path / "storage")

    with pytest.raises(StorageSelectorError, match="Unknown storage 'missing'"):
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage="missing",
            )
        )


def test_optional_storage_rejects_missing_selected_root(tmp_path: Path) -> None:
    kit = _optional_kit(tmp_path)
    registry = AppFiles(kit.schema).preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "missing"\n\n'
        '[storages.missing]\nroot = "../missing"\n',
        encoding="utf-8",
    )

    with pytest.raises(StorageSelectorError, match="does not exist"):
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=None,
            )
        )


def test_resolution_does_not_choose_between_duplicate_root_aliases(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    root.mkdir()
    AppFiles(kit.schema).storage_dotenv_path(root).write_text(
        "", encoding="utf-8"
    )
    registry = AppFiles(kit.schema).preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "alpha"\n\n'
        f"[storages.alpha]\nroot = {json.dumps(str(root))}\n\n"
        f"[storages.beta]\nroot = {json.dumps(str(root))}\n",
        encoding="utf-8",
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(root),
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name is None
    assert result.selection is not None
    assert result.selection.selector_kind == "path"


def test_resolution_uses_first_registered_storage_as_toml_default(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _register(kit, name="alpha", root=alpha)
    _register(kit, name="beta", root=beta)

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "alpha"
    assert result.selection is not None
    assert result.selection.root == alpha.resolve()
    assert result.selection is not None
    assert result.selection.source == "apprc.toml selected_storage"
    assert result.values["APPRC_EXAMPLE_APP_STORAGE"] == str(alpha.resolve())


def test_resolution_cli_selector_beats_process_and_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        _register(kit, name=name, root=tmp_path / name)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("APPRC_EXAMPLE_APP_STORAGE=beta\n", encoding="utf-8")

    result = kit.resolve(
        ResolveOptions(
            env_files=(explicit,),
            env_file_overrides_os_environ=True,
            load_dotenv_layers=True,
            storage="gamma",
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "gamma"
    assert result.selection is not None
    assert result.selection.source == "--storage"


@pytest.mark.parametrize(
    ("explicit_overrides", "expected"),
    [(False, "alpha"), (True, "beta")],
)
def test_resolution_preserves_explicit_env_override_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    explicit_overrides: bool,
    expected: str,
) -> None:
    kit = _kit(tmp_path)
    _register(kit, name="alpha", root=tmp_path / "alpha")
    _register(kit, name="beta", root=tmp_path / "beta")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("APPRC_EXAMPLE_APP_STORAGE=beta\n", encoding="utf-8")

    result = kit.resolve(
        ResolveOptions(
            env_files=(explicit,),
            env_file_overrides_os_environ=explicit_overrides,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == expected


def test_repeated_resolution_does_not_inherit_previous_file_values(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _register(kit, name="alpha", root=alpha)
    _register(kit, name="beta", root=beta)
    AppFiles(kit.schema).storage_dotenv_path(alpha).write_text(
        "APPRC_EXAMPLE_APP_PROFILE=alpha\n",
        encoding="utf-8",
    )
    AppFiles(kit.schema).storage_dotenv_path(beta).write_text(
        "APPRC_EXAMPLE_APP_PROFILE=beta\n",
        encoding="utf-8",
    )

    kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="alpha",
        )
    )
    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="beta",
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "beta"
    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "beta"


def test_later_resolution_captures_current_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    _register(kit, name="alpha", root=tmp_path / "alpha")
    _register(kit, name="beta", root=tmp_path / "beta")

    kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage="alpha",
        )
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "beta")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_PROFILE", "caller")
    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "beta"
    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "caller"


def test_user_dotenv_does_not_select_storage(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    _register(kit, name="alpha", root=tmp_path / "alpha")
    _register(kit, name="beta", root=tmp_path / "beta")
    write_env_file(
        AppFiles(kit.schema).user_dotenv_path(),
        {
            "APPRC_EXAMPLE_APP_STORAGE": "beta",
            "APPRC_EXAMPLE_APP_PROFILE": "from-user",
        },
        owners=kit.schema.owners,
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.selection is not None
    assert result.selection.storage_name == "alpha"
    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "from-user"


def test_storage_dotenv_overrides_user_dotenv(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    _register(kit, name="default", root=root)
    AppFiles(kit.schema).user_dotenv_path().write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-user"\n', encoding="utf-8"
    )
    AppFiles(kit.schema).storage_dotenv_path(root).write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-storage"\n', encoding="utf-8"
    )

    result = kit.resolve(
        ResolveOptions(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
    )

    assert result.values["APPRC_EXAMPLE_APP_PROFILE"] == "from-storage"
    assert result.paths is not None
    assert result.paths.user_dotenv == AppFiles(kit.schema).user_dotenv_path()
    assert next(
        layer.path
        for layer in result.layers
        if layer.origin == "shell_dotenv_storage"
    ) == AppFiles(kit.schema).storage_dotenv_path(root)


def test_resolution_rejects_missing_registered_root(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    registry = AppFiles(kit.schema).preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "missing"\n\n'
        '[storages.missing]\nroot = "../missing"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        StorageSelectorError, match="does not exist"
    ) as exc_info:
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=None,
            )
        )

    assert str(tmp_path / "missing") in str(exc_info.value)


def test_resolution_rejects_registered_root_file(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage-file"
    root.write_text("not a directory", encoding="utf-8")
    registry = AppFiles(kit.schema).preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "invalid"\n\n'
        f"[storages.invalid]\nroot = {json.dumps(str(root))}\n",
        encoding="utf-8",
    )

    with pytest.raises(StorageSelectorError, match="not a directory"):
        kit.resolve(
            ResolveOptions(
                env_files=(),
                env_file_overrides_os_environ=False,
                load_dotenv_layers=True,
                storage=None,
            )
        )
