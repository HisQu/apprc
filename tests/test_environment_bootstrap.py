from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from apprc.runtime_config import EnvConfig, env_field, env_owner
from apprc.runtime_config.app_spec import AppConfigSpec
from apprc.runtime_config.bootstrap.orchestrator import bootstrap_env
from apprc.runtime_config.storage.registry import register_storage
from tests.support_config import StorageFreeExampleEnv


pytestmark = [pytest.mark.requires_apprc_env("DEMO")]


@env_owner(
    key="demo.runtime",
    title="Demo Runtime",
    env_prefix="DEMO_",
    rc_path=("demo",),
)
class _DemoBootstrapEnv(EnvConfig):
    storage: Path = env_field("STORAGE")
    model: str = env_field("MODEL", default="default-model")
    retry_count: int = env_field("RETRY_COUNT", default=0)


@pytest.fixture(autouse=True)
def _restore_demo_env(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    prefixes = ("DEMO_", "STORAGE_FREE_APP_")
    original = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(prefixes)
    }
    for key in tuple(os.environ):
        if key.startswith(prefixes):
            del os.environ[key]

    if request.node.get_closest_marker("allow_missing_apprc_env") is None:
        apprc_toml_path = tmp_path / "config" / "demo" / "demo.apprc.toml"
        storage_root = tmp_path / "demo-storage"
        storage_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DEMO_APPRC_TOML", str(apprc_toml_path))
        monkeypatch.setenv("DEMO_STORAGE", str(storage_root.resolve()))

    yield
    for key in tuple(os.environ):
        if key.startswith(prefixes):
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
        envs=(_DemoBootstrapEnv,),
        storage_env_key="DEMO_STORAGE",
        apprc_toml_filename="demo.apprc.toml",
        shared_env_filename=".env.shared",
        local_env_filename=".env.demo",
    )


def _storage_free_spec(package_name: str) -> AppConfigSpec:
    """Return a storage-free bootstrap spec for global config tests."""
    return AppConfigSpec(
        app_name="storage_free_app",
        display_name="Storage-Free App",
        config_package=package_name,
        envs=(StorageFreeExampleEnv,),
        apprc_toml_filename="storage_free_app.apprc.toml",
    )


class _BootstrapLogSink:
    """Collect bootstrap log messages for assertions."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        """Store the rendered informational message."""
        if args:
            self.messages.append(str(msg) % args)
            return
        self.messages.append(str(msg))


def _set_demo_apprc_toml(monkeypatch, tmp_path: Path) -> Path:
    """Point the demo bootstrap spec at a test AppRC TOML file."""
    apprc_toml_path = tmp_path / "config" / "demo" / "demo.apprc.toml"
    monkeypatch.setenv("DEMO_APPRC_TOML", str(apprc_toml_path))
    return apprc_toml_path


def _default_demo_apprc_toml() -> Path:
    """Return the isolated default AppRC TOML path for demo tests."""
    return Path(os.environ["XDG_CONFIG_HOME"]) / "demo" / "demo.apprc.toml"


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_storage_disabled_loads_global_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("STORAGE_FREE_APP_STORAGE", raising=False)
    monkeypatch.delenv("STORAGE_FREE_APP_PROFILE", raising=False)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'STORAGE_FREE_APP_PROFILE="shared-profile"\n',
    )
    spec = _storage_free_spec(package_name)
    paths = spec.ensure_config_home()
    paths.global_env.write_text(
        'STORAGE_FREE_APP_PROFILE="global-profile"\n',
        encoding="utf-8",
    )

    result = bootstrap_env(
        spec=spec,
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.config_home == paths.root
    assert result.global_env == paths.global_env
    assert result.local_env is None
    assert result.storage_root is None
    assert result.storage_selector_source is None
    assert result.apprc_toml_path == paths.apprc_toml
    assert "STORAGE_FREE_APP_STORAGE" not in os.environ
    assert os.environ["STORAGE_FREE_APP_PROFILE"] == "global-profile"
    provenance = StorageFreeExampleEnv().provenance_of("profile")
    assert provenance.origin == "shell_dotenv_global"
    assert provenance.path == paths.global_env


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_uses_storage_without_apprc_toml_env(
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
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.apprc_toml_path == _default_demo_apprc_toml()
    assert _default_demo_apprc_toml().is_file()
    assert result.storage_name is None
    assert result.storage_root == storage_root.resolve()
    assert result.local_env == storage_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_logs_layers_without_env_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("DEMO_STORAGE", str(storage_root))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-secret-value"\n',
    )
    explicit_env = tmp_path / "explicit.env"
    explicit_env.write_text(
        'DEMO_MODEL="explicit-secret-value"\n',
        encoding="utf-8",
    )
    sink = _BootstrapLogSink()

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(explicit_env,),
        env_file_overrides_os_environ=True,
        load_dotenv_layers=True,
        storage=None,
        logger=sink,
    )

    output = "\n".join(sink.messages)
    assert "AppRC bootstrap starting" in output
    assert "selected storage selector" in output
    assert "resolved storage" in output
    assert "loaded dotenv layers" in output
    assert "wrote process env entries" in output
    assert "shared-secret-value" not in output
    assert "explicit-secret-value" not in output
    assert result.local_env == storage_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_bare_storage_without_apprc_toml_is_relative_path(
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
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.apprc_toml_path == _default_demo_apprc_toml()
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
        env_files=(explicit_env,),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.apprc_toml_path == _default_demo_apprc_toml()
    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_root == storage_root.resolve()
    assert os.environ["DEMO_MODEL"] == "explicit-model"
    provenance = _DemoBootstrapEnv().provenance_of("model")
    assert provenance.origin == "shell_dotenv_explicit"
    assert provenance.path == explicit_env


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_explicit_env_file_can_select_registered_storage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    apprc_toml_path = tmp_path / "config" / "demo.apprc.toml"
    storage_root = tmp_path / "registered-storage"
    storage_root.mkdir()
    register_storage(
        name="alpha",
        root=storage_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text(
        f'DEMO_APPRC_TOML="{apprc_toml_path}"\nDEMO_STORAGE="alpha"\n',
        encoding="utf-8",
    )
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(explicit_env,),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.apprc_toml_path == apprc_toml_path.resolve()
    assert result.storage_name == "alpha"
    assert result.storage_root == storage_root.resolve()
    assert os.environ["DEMO_APPRC_TOML"] == str(apprc_toml_path)
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_rejects_missing_explicit_env_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    missing_env = tmp_path / "missing.env"

    with pytest.raises(FileNotFoundError, match="Explicit env file"):
        bootstrap_env(
            spec=_spec(package_name),
            env_files=(missing_env,),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_uses_packaged_shared_storage_default_without_writes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    storage_root = tmp_path / "shared-storage"
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        f'DEMO_STORAGE="{storage_root}"\nDEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_selector_source == "packaged .env.shared"
    assert result.storage_selector_value == str(storage_root)
    assert result.storage_root == storage_root.resolve()
    assert result.local_env == storage_root.resolve() / ".env.demo"
    assert os.environ["DEMO_STORAGE"] == str(storage_root.resolve())
    assert os.environ["DEMO_MODEL"] == "shared-model"
    provenance = _DemoBootstrapEnv().provenance_of("model")
    assert provenance.origin == "shell_dotenv_shared"
    assert provenance.path is not None
    assert provenance.path.name == ".env.shared"
    assert not storage_root.exists()
    assert not (storage_root / ".env.demo").exists()


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_reports_post_bootstrap_process_env_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    monkeypatch.delenv("DEMO_STORAGE", raising=False)
    storage_root = tmp_path / "shared-storage"
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        f'DEMO_STORAGE="{storage_root}"\nDEMO_MODEL="shared-model"\n',
    )
    bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )
    monkeypatch.setenv("DEMO_MODEL", "mutated-model")

    provenance = _DemoBootstrapEnv().provenance_of("model")

    assert provenance.source == "python"
    assert provenance.origin == "python_process_environment_mutation"
    assert provenance.path is None


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_shell_storage_wins_over_packaged_shared_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEMO_APPRC_TOML", raising=False)
    shell_storage = tmp_path / "shell-storage"
    shared_storage = tmp_path / "shared-storage"
    monkeypatch.setenv("DEMO_STORAGE", str(shell_storage))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        f'DEMO_STORAGE="{shared_storage}"\nDEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.storage_selector_source == "DEMO_STORAGE"
    assert result.storage_root == shell_storage.resolve()
    assert os.environ["DEMO_STORAGE"] == str(shell_storage.resolve())


def test_bootstrap_env_configured_apprc_toml_is_created(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_apprc_toml = tmp_path / "missing.toml"
    monkeypatch.setenv("DEMO_APPRC_TOML", str(missing_apprc_toml))
    monkeypatch.setenv("DEMO_STORAGE", str(tmp_path / "storage"))
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.apprc_toml_path == missing_apprc_toml
    assert missing_apprc_toml.is_file()


def test_bootstrap_env_uses_os_environ_over_explicit_env_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
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
        path=apprc_toml_path,
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
        env_files=(explicit_env,),
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
    provenance = _DemoBootstrapEnv().provenance()
    assert provenance["model"].origin == "shell_export_variable"
    assert provenance["retry_count"].origin == "shell_dotenv_shared"


def test_bootstrap_env_uses_explicit_env_over_dotenv_layers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=apprc_toml_path,
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
        env_files=(explicit_env,),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["DEMO_MODEL"] == "explicit-model"
    provenance = _DemoBootstrapEnv().provenance_of("model")
    assert provenance.origin == "shell_dotenv_explicit"
    assert provenance.path == explicit_env


def test_bootstrap_env_records_local_dotenv_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", str(storage_root))
    local_env = storage_root / ".env.demo"
    local_env.write_text('DEMO_MODEL="local-model"\n', encoding="utf-8")

    bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    provenance = _DemoBootstrapEnv().provenance_of("model")
    assert provenance.origin == "shell_dotenv_local"
    assert provenance.path == local_env


def test_bootstrap_env_merges_explicit_env_files_in_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\nDEMO_RETRY_COUNT="1"\n',
    )
    storage_root = tmp_path / "storage"
    register_storage(
        name="alpha",
        root=storage_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    first_env = tmp_path / "first.env"
    first_env.write_text(
        'DEMO_MODEL="first-model"\nDEMO_RETRY_COUNT="2"\n',
        encoding="utf-8",
    )
    second_env = tmp_path / "second.env"
    second_env.write_text(
        'DEMO_MODEL="second-model"\n',
        encoding="utf-8",
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(first_env, second_env),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=True,
        storage=None,
    )

    assert result.env_files == (first_env, second_env)
    assert os.environ["DEMO_MODEL"] == "second-model"
    assert os.environ["DEMO_RETRY_COUNT"] == "2"
    provenance = _DemoBootstrapEnv().provenance()
    assert provenance["model"].origin == "shell_dotenv_explicit"
    assert provenance["model"].path == second_env
    assert provenance["retry_count"].origin == "shell_dotenv_explicit"
    assert provenance["retry_count"].path == first_env


def test_bootstrap_env_can_let_explicit_env_override_os_environ(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
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
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    explicit_env = tmp_path / "override.env"
    explicit_env.write_text('DEMO_MODEL="explicit-model"\n', encoding="utf-8")

    bootstrap_env(
        spec=_spec(package_name),
        env_files=(explicit_env,),
        env_file_overrides_os_environ=True,
        load_dotenv_layers=True,
        storage=None,
    )

    assert os.environ["DEMO_MODEL"] == "explicit-model"
    provenance = _DemoBootstrapEnv().provenance_of("model")
    assert provenance.origin == "shell_dotenv_explicit"
    assert provenance.path == explicit_env


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
        env_files=(),
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
        "apprc.runtime_config.storage.selector.normalize_storage_root_path",
        lambda path: normalized_root,
    )
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
        env_file_overrides_os_environ=False,
        load_dotenv_layers=False,
        storage=None,
    )

    assert result.storage_root == normalized_root


def test_bootstrap_env_storage_selector_selects_active_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
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
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    register_storage(
        name="beta",
        root=beta_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
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
    provenance = _DemoBootstrapEnv().provenance_of("storage")
    assert provenance.origin == "shell_bootstrap_selector"
    assert provenance.path is None


def test_bootstrap_env_storage_option_wins_over_env_selector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
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
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    register_storage(
        name="beta",
        root=beta_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "alpha")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
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
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    beta_root = tmp_path / "beta-storage"
    register_storage(
        name="beta",
        root=beta_root,
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "beta")

    result = bootstrap_env(
        spec=_spec(package_name),
        env_files=(),
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
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
    package_name = _shared_env_package(
        monkeypatch,
        tmp_path,
        'DEMO_MODEL="shared-model"\n',
    )
    register_storage(
        name="alpha",
        root=tmp_path / "alpha-storage",
        path=apprc_toml_path,
        local_env_filename=".env.demo",
    )
    monkeypatch.setenv("DEMO_STORAGE", "beta")

    with pytest.raises(ValueError, match="Use './beta'"):
        bootstrap_env(
            spec=_spec(package_name),
            env_files=(),
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
            env_files=(),
            env_file_overrides_os_environ=False,
            load_dotenv_layers=True,
            storage=None,
        )


@pytest.mark.allow_missing_apprc_env
def test_bootstrap_env_without_dotenv_layers_keeps_explicit_storage_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    apprc_toml_path = _set_demo_apprc_toml(monkeypatch, tmp_path)
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
        path=apprc_toml_path,
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
        env_files=(explicit_env,),
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
