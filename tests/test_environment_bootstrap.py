from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apprc.definition.app_config.kit import AppConfigKit
from apprc.definition.app_config.storage import Storage
from apprc.user_files.env_files import write_env_file
from apprc.user_files.storage_roots.registry import register_storage
from apprc.user_files.storage_roots.selector import StorageSelectorError
from tests.support_config import ApprcExampleAppEnv


@pytest.fixture(autouse=True)
def _clear_example_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove process values written by previous bootstrap tests."""
    for key in tuple(os.environ):
        if key.startswith("APPRC_EXAMPLE_APP_"):
            monkeypatch.delenv(key, raising=False)


def _kit(tmp_path: Path) -> AppConfigKit:
    """Return an isolated storage-capable application declaration."""
    return AppConfigKit(
        app_id="apprc_example_app",
        display_name="Example App",
        config_package="config_with_storage.config",
        envs=(ApprcExampleAppEnv,),
        storage=Storage(selector_env_key="APPRC_EXAMPLE_APP_STORAGE"),
        apprc_dir=tmp_path / "apprc",
    )


def _register(kit: AppConfigKit, *, name: str, root: Path) -> None:
    """Register one test storage using the application's fixed files."""
    register_storage(
        name=name,
        root=root,
        path=kit.spec.preferred_apprc_toml_path(),
        storage_dotenv_filename=kit.spec.storage_dotenv_filename,
    )


def test_bootstrap_rejects_path_valued_runtime_selector(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    _register(kit, name="default", root=root)

    with pytest.raises(StorageSelectorError, match="registered storage name"):
        kit.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=str(root),
        )


def test_bootstrap_uses_first_registered_storage_as_toml_default(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _register(kit, name="alpha", root=alpha)
    _register(kit, name="beta", root=beta)

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_name == "alpha"
    assert result.storage_root == alpha.resolve()
    assert result.storage_selector_source == "apprc.toml selected_storage"
    assert os.environ["APPRC_EXAMPLE_APP_STORAGE"] == str(alpha.resolve())


def test_bootstrap_cli_selector_beats_process_and_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        _register(kit, name=name, root=tmp_path / name)
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("APPRC_EXAMPLE_APP_STORAGE=beta\n", encoding="utf-8")

    result = kit.bootstrap(
        env_files=(explicit,),
        env_file_overrides_os_environ=True,
        load_dotenv_layers=True,
        storage="gamma",
    )

    assert result.storage_name == "gamma"
    assert result.storage_selector_source == "--storage"


@pytest.mark.parametrize(
    ("explicit_overrides", "expected"),
    [(False, "alpha"), (True, "beta")],
)
def test_bootstrap_preserves_explicit_env_override_policy(
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

    result = kit.bootstrap(
        env_files=(explicit,),
        env_file_overrides_os_environ=explicit_overrides,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_name == expected


def test_user_dotenv_does_not_select_storage(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    _register(kit, name="alpha", root=tmp_path / "alpha")
    _register(kit, name="beta", root=tmp_path / "beta")
    write_env_file(
        kit.spec.user_dotenv_path(),
        {
            "APPRC_EXAMPLE_APP_STORAGE": "beta",
            "APPRC_EXAMPLE_APP_PROFILE": "from-user",
        },
        owners=kit.spec.owners,
    )

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_name == "alpha"
    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-user"


def test_storage_dotenv_overrides_user_dotenv(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage"
    _register(kit, name="default", root=root)
    kit.spec.user_dotenv_path().write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-user"\n', encoding="utf-8"
    )
    kit.spec.storage_dotenv_path(root).write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-storage"\n', encoding="utf-8"
    )

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-storage"
    assert result.user_dotenv == kit.spec.user_dotenv_path()
    assert result.storage_dotenv == kit.spec.storage_dotenv_path(root)


def test_bootstrap_rejects_missing_registered_root(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    registry = kit.spec.preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "missing"\n\n'
        '[storages.missing]\nroot = "../missing"\n',
        encoding="utf-8",
    )

    with pytest.raises(StorageSelectorError, match="does not exist"):
        kit.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


def test_bootstrap_rejects_registered_root_file(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    root = tmp_path / "storage-file"
    root.write_text("not a directory", encoding="utf-8")
    registry = kit.spec.preferred_apprc_toml_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(
        'selected_storage = "invalid"\n\n'
        f"[storages.invalid]\nroot = {json.dumps(str(root))}\n",
        encoding="utf-8",
    )

    with pytest.raises(StorageSelectorError, match="not a directory"):
        kit.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )
