from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from apprc.config.app_spec import AppConfigSpec, RegistryEnvError
from apprc.config.environment import bootstrap_env
from apprc.config.storage.registry import register_storage


pytestmark = [pytest.mark.requires_apprc_env("DEMO")]


@pytest.fixture(autouse=True)
def _restore_demo_env(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    if request.node.get_closest_marker("allow_missing_apprc_env") is None:
        registry_path = tmp_path / "config" / "demo" / "demo.apprc.toml"
        storage_root = tmp_path / "demo-storage"
        storage_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DEMO_APPRC_TOML", str(registry_path))
        monkeypatch.setenv("DEMO_STORAGE", str(storage_root.resolve()))

    original = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("DEMO_")
    }
    yield
    for key in tuple(os.environ):
        if key.startswith("DEMO_"):
            del os.environ[key]
    os.environ.update(original)


def _shared_env_package(
    monkeypatch,
    tmp_path: Path,
    content: str,
) -> str:
    """Create an importable package that owns a test shared dotenv file."""
    package_name = f"demo_shared_{tmp_path.name}".replace("-", "_")
    package_dir = tmp_path / package_name
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / ".env.shared").write_text(content, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return package_name


def _spec(package_name: str) -> AppConfigSpec:
    """Return a bootstrap spec for the demo test package."""
    return AppConfigSpec(
        app_name="demo",
        display_name="Demo",
        config_package=package_name,
        owners=(),
        storage_env_key="DEMO_STORAGE",
        apprc_toml_filename="demo.apprc.toml",
        shared_env_filename=".env.shared",
        local_env_filename=".env.demo",
    )


def _set_demo_apprc_toml(monkeypatch, tmp_path: Path) -> Path:
    """Point the demo bootstrap spec at a test registry file."""
    registry_path = tmp_path / "config" / "demo" / "demo.apprc.toml"
    monkeypatch.setenv("DEMO_APPRC_TOML", str(registry_path))
    return registry_path


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_uses_storage_without_registry_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("DEMO_STORAGE", str(storage_root))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.registry_path is None
    assert result.storage_name is None
    assert result.storage_root == storage_root.resolve()
    assert result.local_env == storage_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_bare_storage_without_registry_is_relative_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.setenv("DEMO_STORAGE", "alpha")
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.registry_path is None
    assert result.storage_name is None
    assert result.storage_selector_value == "alpha"
    assert result.storage_root == (tmp_path / "alpha").resolve()


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_explicit_env_file_can_select_single_storage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    storage_root = tmp_path / "explicit-storage"
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text(
        f'DEMO_STORAGE="{storage_root}"\nDEMO_MODEL="explicit-model"\n',
        encoding="utf-8",
    )
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.registry_path is None
    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_root == storage_root.resolve()
    assert os.environ["DEMO_MODEL"] == "explicit-model"


def test_bootstrap_env_configured_registry_must_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_registry = tmp_path / "missing.toml"
    monkeypatch.setenv("DEMO_APPRC_TOML", str(missing_registry))
    monkeypatch.setenv("DEMO_STORAGE", str(tmp_path / "storage"))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    with pytest.raises(RegistryEnvError, match="missing registry file"):
        bootstrap_env(
            spec=_spec(package_name),
            env_file=None,
            env_file_overrides_os_environ=False,
            load_dotenv_layers=False,
            storage=None,
        )


def test_bootstrap_env_uses_os_environ_over_explicit_env_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("DEMO_MODEL", "shell-model")
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\nDEMO_RETRY_COUNT="3"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", str(storage_root))
    (storage_root / ".env.demo").write_text(
        'DEMO_MODEL="local-model"\n',
        encoding="utf-8",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["DEMO_MODEL"] == "shell-model"
    assert os.environ["DEMO_RETRY_COUNT"] == "3"
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())
    assert result.storage_name is None
    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_selector_value == str(storage_root)
    assert result.local_env == storage_root.resolve() / ".env.demo"


def test_bootstrap_env_uses_explicit_env_over_dotenv_layers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    (storage_root / ".env.demo").write_text(
        'DEMO_MODEL="local-model"\n',
        encoding="utf-8",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["DEMO_MODEL"] == "explicit-model"


def test_bootstrap_env_can_let_explicit_env_override_os_environ(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.setenv("DEMO_MODEL", "shell-model")
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_os_environ=True,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["DEMO_MODEL"] == "explicit-model"


def test_bootstrap_env_without_dotenv_layers_uses_os_environ_storage_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    storage_root = tmp_path / "from-shell"
    monkeypatch.setenv("DEMO_STORAGE", str(storage_root))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.shared_env is None
    assert result.local_env is None
    assert result.storage_root == storage_root
    assert os.environ["DEMO_STORAGE"] == str(storage_root)


def test_bootstrap_env_normalizes_storage_root_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    normalized_root = tmp_path / "demo-storage"
    monkeypatch.setenv(
        "DEMO_STORAGE",
        r"D:\Training\demo-project",
    )
    monkeypatch.setattr(
        "apprc.config.storage.selector.normalize_storage_root_path",
        lambda path: normalized_root,
    )
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.storage_root == normalized_root


def test_bootstrap_env_storage_selector_selects_active_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    alpha_root = tmp_path / "alpha-storage"
    beta_root = tmp_path / "beta-storage"
    register_storage(
        name="alpha",
        root=alpha_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    register_storage(
        name="beta",
        root=beta_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage="beta",
    )

    assert result.storage_name == "beta"
    assert result.storage_selector_source == "--storage"
    assert result.storage_selector_value == "beta"
    assert result.storage_root == beta_root.resolve()
    assert result.local_env == beta_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(beta_root.resolve())


def test_bootstrap_env_storage_option_wins_over_env_selector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    alpha_root = tmp_path / "alpha-storage"
    beta_root = tmp_path / "beta-storage"
    register_storage(
        name="alpha",
        root=alpha_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    register_storage(
        name="beta",
        root=beta_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "alpha")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage="beta",
    )

    assert result.storage_name == "beta"
    assert result.storage_selector_source == "--storage"
    assert result.storage_selector_value == "beta"
    assert result.storage_root == beta_root.resolve()


def test_bootstrap_env_storage_env_name_selects_registered_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    beta_root = tmp_path / "beta-storage"
    register_storage(
        name="beta",
        root=beta_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "beta")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_name == "beta"
    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_selector_value == "beta"
    assert result.storage_root == beta_root.resolve()
    assert result.local_env == beta_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(beta_root.resolve())


def test_bootstrap_env_storage_env_bare_unknown_name_is_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    register_storage(
        name="alpha",
        root=tmp_path / "alpha-storage",
        path=registry_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "beta")

    with pytest.raises(ValueError, match="Use './beta'"):
        bootstrap_env(
            spec=_spec(package_name),
            env_file=None,
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


def test_bootstrap_env_requires_storage_selector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_demo_apprc_toml(monkeypatch, tmp_path)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    with pytest.raises(ValueError, match="DEMO_STORAGE is required"):
        bootstrap_env(
            spec=_spec(package_name),
            env_file=None,
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_without_dotenv_layers_keeps_explicit_storage_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    default_root = tmp_path / "default-storage"
    explicit_root = tmp_path / "explicit-storage"
    register_storage(
        name="alpha",
        root=default_root,
        path=registry_path,
        local_env_filename=".env.demo",
    )
    explicit_root.mkdir()
    (explicit_root / ".env.demo").write_text(
        'DEMO_LOCAL="local-value"\n',
        encoding="utf-8",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text(
        f'DEMO_STORAGE="{explicit_root}"\nDEMO_MODEL="explicit-model"\n',
        encoding="utf-8",
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_os_environ=True,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.shared_env is None
    assert result.local_env is None
    assert result.storage_name is None
    assert result.storage_root == explicit_root.resolve()
    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_selector_value == str(explicit_root)
    assert os.environ["DEMO_STORAGE"] == str(explicit_root.resolve())
    assert "DEMO_MODEL" not in os.environ
    assert "DEMO_LOCAL" not in os.environ
