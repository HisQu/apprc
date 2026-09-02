from __future__ import annotations

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


def _kit() -> AppConfigKit:
    return AppConfigKit(
        app_name="apprc_example_app",
        display_name="Example App",
        config_package="storage_only.config",
        envs=(ApprcExampleAppEnv,),
        storage=Storage(env_key="APPRC_EXAMPLE_APP_STORAGE"),
    )


def test_bootstrap_storage_path_selector_does_not_create_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = _kit()

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_root == storage_root.resolve()
    assert result.storage_env == storage_root.resolve() / "apprc.storage.env"
    assert result.index_path == kit.spec.default_index_path()
    assert result.index_path is not None
    assert result.storage_env is not None
    assert not result.index_path.exists()
    assert not result.storage_env.exists()
    assert os.environ["APPRC_EXAMPLE_APP_STORAGE"] == str(
        storage_root.resolve()
    )


def test_bootstrap_rejects_missing_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Report the owning app's setup command without creating the root.

    :param monkeypatch: Isolated process environment fixture.
    :param tmp_path: Temporary parent for the missing storage root.
    """
    missing_root = tmp_path / "missing-storage"
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(missing_root))

    with pytest.raises(StorageSelectorError) as error:
        _kit().bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )

    message = str(error.value)
    assert "Selected Example App storage root does not exist" in message
    assert str(missing_root.resolve()) in message
    assert (
        "apprc_example_app config setup --yes --storage-root STORAGE_ROOT"
        in message
    )
    assert not missing_root.exists()


def test_bootstrap_rejects_storage_root_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a selected file before reading storage-local configuration.

    :param monkeypatch: Isolated process environment fixture.
    :param tmp_path: Temporary parent for the invalid storage root.
    """
    storage_file = tmp_path / "storage-file"
    storage_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_file))

    with pytest.raises(StorageSelectorError) as error:
        _kit().bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )

    message = str(error.value)
    assert "Selected Example App storage root is not a directory" in message
    assert "APPRC_EXAMPLE_APP_STORAGE" in message


def test_bootstrap_path_selector_ignores_corrupt_optional_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = _kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_root == storage_root.resolve()
    assert result.index_path == index_path
    assert result.storage_name is None


def test_bootstrap_bare_selector_fails_with_corrupt_existing_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")
    kit = _kit()
    index_path = kit.spec.index_path()
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[invalid", encoding="utf-8")

    with pytest.raises(ValueError):
        kit.bootstrap(
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


def test_bootstrap_reads_app_wide_selector_only_when_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    kit = _kit()
    app_wide_env = kit.spec.app_wide_env_path()
    write_env_file(
        app_wide_env,
        {
            "APPRC_EXAMPLE_APP_STORAGE": str(storage_root),
            "APPRC_EXAMPLE_APP_PROFILE": "from-app",
        },
        owners=kit.spec.owners,
    )

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_root == storage_root.resolve()
    assert result.storage_selector_source == "app config"
    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-app"
    assert not kit.spec.default_index_path().exists()


def test_bootstrap_storage_env_overrides_app_wide_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    kit = _kit()
    app_wide_env = kit.spec.app_wide_env_path()
    app_wide_env.parent.mkdir(parents=True)
    app_wide_env.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-app"\n',
        encoding="utf-8",
    )
    kit.spec.storage_env_path(storage_root).write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-storage"\n',
        encoding="utf-8",
    )

    kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-storage"


def test_bootstrap_named_selector_uses_index_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    kit = _kit()
    index_path = tmp_path / "config" / "apprc_example_app.apprc.toml"
    alpha_root = tmp_path / "alpha"
    register_storage(
        name="alpha",
        root=alpha_root,
        path=index_path,
        storage_env_filename=kit.spec.storage_env_filename,
    )
    monkeypatch.setenv("APPRC_EXAMPLE_APP_APPRC_TOML", str(index_path))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", "alpha")

    result = kit.bootstrap(
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_name == "alpha"
    assert result.storage_root == alpha_root.resolve()
    assert result.storage_count == 1
    assert result.index_path == index_path


def test_bootstrap_preserves_explicit_env_override_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("APPRC_EXAMPLE_APP_STORAGE", str(storage_root))
    monkeypatch.setenv("APPRC_EXAMPLE_APP_PROFILE", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text(
        'APPRC_EXAMPLE_APP_PROFILE="from-explicit"\n',
        encoding="utf-8",
    )
    kit = _kit()

    kit.bootstrap(
        env_files=(env_file,),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )
    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-shell"

    kit.bootstrap(
        env_files=(env_file,),
        env_file_overrides_os_environ=True,
        load_dotenv_layers=True,
        storage=None,
    )
    assert os.environ["APPRC_EXAMPLE_APP_PROFILE"] == "from-explicit"
