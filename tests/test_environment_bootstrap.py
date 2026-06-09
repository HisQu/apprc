from __future__ import annotations

import os
from pathlib import Path

from apprc.config.environment import EnvBootstrapSpec, bootstrap_env
from apprc.config.storage_registry import register_storage


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


def _spec(package_name: str) -> EnvBootstrapSpec:
    """Return a bootstrap spec for the demo test package."""
    return EnvBootstrapSpec(
        app_name="demo",
        display_name="Demo",
        config_package=package_name,
        storage_root_env_key="DEMO_D_STORAGE",
        registry_filename="demo.toml",
        shared_env_filename=".env.shared",
        local_env_filename=".env.demo",
    )


def test_bootstrap_env_uses_shell_over_explicit_env_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
        make_default=True,
        path=tmp_path / "config" / "demo" / "demo.toml",
        local_env_filename=".env.demo",
    )
    (storage_root / ".env.demo").write_text(
        'DEMO_MODEL="local-model"\n',
        encoding="utf-8",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_shell=False,
        load_dotenv_layers=True,
        storage_name=None,
    )

    assert os.environ["DEMO_MODEL"] == "shell-model"
    assert os.environ["DEMO_RETRY_COUNT"] == "3"
    assert os.environ["DEMO_D_STORAGE"] == str(storage_root.resolve())
    assert result.storage_name == "alpha"
    assert result.used_default_storage is True
    assert result.local_env == storage_root.resolve() / ".env.demo"


def test_bootstrap_env_can_let_explicit_env_override_shell(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
        make_default=True,
        path=tmp_path / "config" / "demo" / "demo.toml",
        local_env_filename=".env.demo",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_shell=True,
        load_dotenv_layers=True,
        storage_name=None,
    )

    assert os.environ["DEMO_MODEL"] == "explicit-model"


def test_bootstrap_env_without_dotenv_layers_uses_existing_storage_root_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    storage_root = tmp_path / "from-shell"
    monkeypatch.setenv("DEMO_D_STORAGE", str(storage_root))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=None,
        env_file_overrides_shell=False,
        load_dotenv_layers=False,
        storage_name=None,
    )

    assert result.shared_env is None
    assert result.local_env is None
    assert result.storage_root == storage_root
    assert os.environ["DEMO_D_STORAGE"] == str(storage_root)


def test_bootstrap_env_normalizes_storage_root_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    normalized_root = tmp_path / "demo-storage"
    monkeypatch.setenv(
        "DEMO_D_STORAGE",
        r"D:\Training\demo-project",
    )
    monkeypatch.setattr(
        "apprc.config.environment.normalize_storage_root_path",
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
        env_file_overrides_shell=False,
        load_dotenv_layers=False,
        storage_name=None,
    )

    assert result.storage_root == normalized_root


def test_bootstrap_env_without_dotenv_layers_keeps_explicit_storage_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
        make_default=True,
        path=tmp_path / "config" / "demo" / "demo.toml",
        local_env_filename=".env.demo",
    )
    explicit_root.mkdir()
    (explicit_root / ".env.demo").write_text(
        'DEMO_LOCAL="local-value"\n',
        encoding="utf-8",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text(
        f'DEMO_D_STORAGE="{explicit_root}"\nDEMO_MODEL="explicit-model"\n',
        encoding="utf-8",
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_file=explicit_env,
        env_file_overrides_shell=True,
        load_dotenv_layers=False,
        storage_name=None,
    )

    assert result.shared_env is None
    assert result.local_env is None
    assert result.storage_name is None
    assert result.storage_root == explicit_root.resolve()
    assert result.used_default_storage is False
    assert "DEMO_D_STORAGE" not in os.environ
    assert "DEMO_MODEL" not in os.environ
    assert "DEMO_LOCAL" not in os.environ
