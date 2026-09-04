"""Public AppRC facade behavior tests."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from time import sleep

import pytest
import typer
from typer.testing import CliRunner

import apprc as rc
from apprc.runtime.result import EnvBootstrapResult


def _config_only_app() -> rc.AppRC:
    """Return a small config-only public AppRC facade for tests."""
    return rc.AppRC(
        app_id="public-demo",
        display_name="Public Demo",
        config_package="apprc",
    )


def _bootstrap_result(*, storage_count: int = 0) -> EnvBootstrapResult:
    """Return small bootstrap metadata for state-management tests.

    :param storage_count: Distinguishing value for repeated bootstrap results.
    :return: Bootstrap result without filesystem paths.
    """
    return EnvBootstrapResult(
        defaults_dotenv=None,
        storage_dotenv=None,
        env_files=(),
        apprc_toml=None,
        storage_selector_source=None,
        storage_selector_value=None,
        storage_name=None,
        storage_root=None,
        storage_count=storage_count,
    )


def test_direct_declaration_accepts_optional_storage() -> None:
    """One constructor expresses config-only and storage applications."""
    MyRC = rc.AppRC(
        app_id="haiu",
        display_name="HAIU",
        config_package="haiu.config",
        storage=rc.Storage(selector_env_key="HAIU_STORAGE"),
    )

    assert MyRC.spec.app_id == "haiu"
    assert MyRC.spec.display_name == "HAIU"
    assert MyRC.spec.storage_selector_env_key == "HAIU_STORAGE"
    assert MyRC.spec.defaults_dotenv_filename == "apprc.defaults.env"
    assert MyRC.spec.user_dotenv_filename == "apprc.user.env"
    assert MyRC.spec.storage_dotenv_filename == "apprc.storage.env"
    assert MyRC.spec.apprc_toml_filename == "apprc.toml"


def test_legacy_mode_constructors_are_removed() -> None:
    assert not hasattr(rc.AppRC, "env_only")
    assert not hasattr(rc.AppRC, "storage_only")
    assert not hasattr(rc.AppRC, "app_wide_config")
    assert not hasattr(rc.AppRC, "app_wide_storage")


def test_registers_env_backed_config_with_full_env_keys() -> None:
    """Full public env keys are adapted to owner-local suffixes."""
    MyRC = _config_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_", title="LLM")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.env_prefix == "HAIU_LLM_"
    assert LLMConfig.config_owner.field("provider").env_var == "PROVIDER"
    assert MyRC.spec.envs == (LLMConfig,)


def test_registers_python_only_config_base() -> None:
    """Python-only config classes use normal dataclass defaults."""
    MyRC = _config_only_app()

    @MyRC.config("resources", title="Resources")
    class PackageResources(rc.ConfigBase):
        package: str = "haiu.resources"
        templates: str = "templates"

    resources = PackageResources()
    assert resources.package == "haiu.resources"
    assert resources.templates == "templates"
    assert MyRC.spec.envs == ()


def test_rejects_missing_key_decorator_forms() -> None:
    """The registration decorator always requires an explicit key."""
    MyRC = _config_only_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="requires a config key string"):
        MyRC.config(LLMConfig)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        MyRC.config()  # type: ignore[call-arg]


def test_rejects_missing_prefix_for_env_config() -> None:
    """Env-backed config classes require a non-empty prefix."""
    MyRC = _config_only_app()

    with pytest.raises(ValueError, match='requires prefix="..."'):

        @MyRC.config("llm")
        class LLMConfig(rc.Config):
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_prefix_for_config_base() -> None:
    """Python-only config classes cannot receive an env prefix."""
    MyRC = _config_only_app()

    with pytest.raises(ValueError, match="Python-only config"):

        @MyRC.config("resources", prefix="HAIU_RESOURCES_")
        class PackageResources(rc.ConfigBase):
            package: str = "haiu.resources"


def test_rejects_plain_decorator_only_class() -> None:
    """Registered classes must inherit the public config bases."""
    MyRC = _config_only_app()

    with pytest.raises(TypeError, match="must inherit from rc.Config"):

        @MyRC.config("llm", prefix="HAIU_LLM_")  # pyright: ignore[reportArgumentType]
        class LLMConfig:
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_public_fields_on_config_base() -> None:
    """``rc.field`` belongs only to env-backed ``rc.Config`` classes."""
    MyRC = _config_only_app()

    with pytest.raises(TypeError, match="uses rc.field"):

        @MyRC.config("resources")
        class PackageResources(rc.ConfigBase):
            package: str = rc.field("HAIU_PACKAGE")


def test_rejects_env_key_without_required_prefix() -> None:
    """Every public env key must start with the registered prefix."""
    MyRC = _config_only_app()

    with pytest.raises(ValueError, match="requires prefix HAIU_LLM_"):

        @MyRC.config("llm", prefix="HAIU_LLM_")
        class LLMConfig(rc.Config):
            provider: str = rc.field("OPENAI_PROVIDER", default="openai")


def test_rejects_duplicate_config_keys() -> None:
    """Different classes cannot reuse one config key."""
    MyRC = _config_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(ValueError, match='config key "llm"'):

        @MyRC.config("llm", prefix="HAIU_OTHER_LLM_")
        class OtherLLMConfig(rc.Config):
            provider: str = rc.field(
                "HAIU_OTHER_LLM_PROVIDER",
                default="openai",
            )


def test_rejects_duplicate_env_keys() -> None:
    """One AppRC instance cannot have two fields using the same env key."""
    MyRC = _config_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        token: str = rc.field("HAIU_LLM_TOKEN", secret=True)

    with pytest.raises(ValueError, match="HAIU_LLM_TOKEN"):

        @MyRC.config("rag", prefix="HAIU_")
        class RAGConfig(rc.Config):
            token: str = rc.field("HAIU_LLM_TOKEN", secret=True)


def test_requiredness_inference() -> None:
    """Fields without defaults are required and fields with defaults are not."""
    MyRC = _config_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        required: str = rc.field("HAIU_LLM_REQUIRED")
        optional: str = rc.field("HAIU_LLM_OPTIONAL", default="x")
        factory: Path = rc.field(
            "HAIU_LLM_FACTORY",
            default_factory=lambda: Path("cache"),
        )

    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.field("required").required is True
    assert LLMConfig.config_owner.field("optional").required is False
    assert LLMConfig.config_owner.field("factory").required is False


def test_config_preserves_post_init_hook_class_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Registered config hooks can call super and derive runtime fields."""
    MyRC = _config_only_app()
    monkeypatch.setenv("HAIU_STORAGE", str(tmp_path))

    class StoragePaths(rc.Config):
        storage_root: Path = rc.field("HAIU_STORAGE")
        d_retrieved: Path = dataclass_field(init=False)

        def __post_init__(self) -> None:
            """Derive paths after AppRC resolves env-backed values."""
            super().__post_init__()
            self.d_retrieved = self.storage_root / "retrieved"

    RegisteredStoragePaths = MyRC.config("storage", prefix="HAIU_")(
        StoragePaths
    )

    config = RegisteredStoragePaths()

    assert RegisteredStoragePaths is StoragePaths
    assert config.storage_root == tmp_path
    assert config.d_retrieved == tmp_path / "retrieved"


def test_rejects_optional_missing_field_without_fallback() -> None:
    """Missing optional env values must have a safe fallback representation."""
    with pytest.raises(ValueError, match="required=False"):
        rc.field("HAIU_LLM_OPTIONAL", required=False)


def test_rejects_required_field_with_python_fallback() -> None:
    """Required fields cannot silently fall back to Python values."""
    with pytest.raises(ValueError, match="required=True"):
        rc.field("HAIU_LLM_REQUIRED", required=True, default="fallback")
    with pytest.raises(ValueError, match="required=True"):
        rc.field(
            "HAIU_LLM_REQUIRED",
            required=True,
            default_factory=lambda: "fallback",
        )


def test_required_field_allows_packaged_default_and_constructor_value() -> None:
    """Packaged and explicit runtime values remain valid for required fields."""
    MyRC = _config_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field(
            "HAIU_LLM_PROVIDER",
            required=True,
            packaged_default="openai",
        )

    config = LLMConfig(provider="mock")  # pyright: ignore[reportCallIssue]

    assert config.provider == "mock"
    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.field("provider").required is True


def test_bundle_eager_construction_and_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundles eagerly construct registered children and allow object injection."""
    MyRC = _config_only_app()
    monkeypatch.setenv("HAIU_LLM_API_KEY", "secret-value")

    @MyRC.config("llm", prefix="HAIU_LLM_", title="LLM")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")
        api_key: str = rc.field("HAIU_LLM_API_KEY", secret=True)

    @MyRC.config("resources", title="Resources")
    class PackageResources(rc.ConfigBase):
        package: str = "haiu.resources"

    @MyRC.bundle
    class HAIUConfig:
        llm: LLMConfig
        resources: PackageResources

    config = HAIUConfig()
    assert isinstance(config.llm, LLMConfig)
    assert isinstance(config.resources, PackageResources)
    assert config.llm.api_key == "secret-value"
    assert "secret-value" not in repr(config)

    injected = LLMConfig(provider="mock")  # pyright: ignore[reportCallIssue]
    injected_bundle = HAIUConfig(llm=injected)  # pyright: ignore[reportCallIssue]
    assert injected_bundle.llm is injected

    with pytest.raises(TypeError, match="unexpected config argument"):
        HAIUConfig(other=object())  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="expected LLMConfig, got object"):
        HAIUConfig(llm=object())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected LLMConfig, got dict"):
        HAIUConfig(llm={"provider": "mock"})  # type: ignore[arg-type]


def test_bundle_rejects_unregistered_config_class() -> None:
    """Bundle entries must be registered with the same AppRC instance."""
    MyRC = _config_only_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="not registered with this AppRC"):

        @MyRC.bundle
        class HAIUConfig:
            llm: LLMConfig


def test_bundle_supports_post_init_derived_config_fields() -> None:
    """Bundles validate registered init=False fields and call post-init."""
    MyRC = _config_only_app()

    @MyRC.config("storage", title="Storage")
    @dataclass
    class StorageConfig(rc.ConfigBase):
        root: str = "storage"

    @MyRC.config("rag", title="RAG")
    @dataclass
    class RagConfig(rc.ConfigBase):
        storage: StorageConfig

    @MyRC.bundle
    class HAIUConfig:
        storage: StorageConfig
        rag: RagConfig = dataclass_field(init=False)

        def __post_init__(self) -> None:
            """Compose RAG from the already-resolved storage config."""
            self.rag = RagConfig(storage=self.storage)

    config = HAIUConfig()
    assert isinstance(config.rag, RagConfig)
    assert config.rag.storage is config.storage
    assert (
        repr(config) == "HAIUConfig(storage=<StorageConfig>, rag=<RagConfig>)"
    )

    injected_storage = StorageConfig(root="other")
    injected = HAIUConfig(storage=injected_storage)  # pyright: ignore[reportCallIssue]
    assert injected.storage is injected_storage
    assert injected.rag.storage is injected_storage

    with pytest.raises(TypeError, match="unexpected config argument"):
        HAIUConfig(rag=RagConfig(storage=injected_storage))  # type: ignore[call-arg]


def test_bundle_preserves_post_init_hook_class_identity() -> None:
    """Bundle hooks can call super and derive registered children."""
    MyRC = _config_only_app()
    base_calls: list[str] = []

    @MyRC.config("storage", title="Storage")
    @dataclass
    class StorageConfig(rc.ConfigBase):
        root: str = "storage"

    @MyRC.config("rag", title="RAG")
    @dataclass
    class RagConfig(rc.ConfigBase):
        storage: StorageConfig

    class BundlePostInitBase:
        def __post_init__(self) -> None:
            """Record cooperative post-init dispatch."""
            base_calls.append(type(self).__name__)

    class HAIUConfig(BundlePostInitBase):
        storage: StorageConfig
        rag: RagConfig = dataclass_field(init=False)

        def __post_init__(self) -> None:
            """Compose RAG from the already-resolved storage config."""
            super().__post_init__()
            self.rag = RagConfig(storage=self.storage)

    RegisteredHAIUConfig = MyRC.bundle(HAIUConfig)

    config = RegisteredHAIUConfig()

    assert RegisteredHAIUConfig is HAIUConfig
    assert base_calls == ["HAIUConfig"]
    assert isinstance(config.rag, RagConfig)
    assert config.rag.storage is config.storage


def test_bundle_ignores_config_base_internal_fields() -> None:
    """Bundles can inherit ``rc.ConfigBase`` without registering internals."""
    MyRC = _config_only_app()

    @MyRC.config("storage", title="Storage")
    class StorageConfig(rc.ConfigBase):
        root: str = "storage"

    @MyRC.bundle
    class HAIUConfig(rc.ConfigBase):
        storage: StorageConfig

    config = HAIUConfig()
    assert isinstance(config.storage, StorageConfig)


def test_mount_cli_accepts_only_typer() -> None:
    """The public mount method is Typer-specific."""
    MyRC = _config_only_app()
    app = typer.Typer()

    mounted = MyRC.mount_cli(app)
    assert isinstance(mounted, typer.Typer)

    with pytest.raises(TypeError, match="typer.Typer instances only"):
        MyRC.mount_cli(object())  # type: ignore[arg-type]


def test_manual_bootstrap_allows_later_config_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual bootstrap prepares env state for direct config construction."""
    MyRC = _config_only_app()
    monkeypatch.setenv("PUBLIC_BOOTSTRAP_VALUE", "from-env")

    @MyRC.config("demo", prefix="PUBLIC_BOOTSTRAP_")
    class DemoConfig(rc.Config):
        value: str = rc.field("PUBLIC_BOOTSTRAP_VALUE")

    result = MyRC.bootstrap(load_dotenv_layers=False)
    config = DemoConfig()

    assert config.value == "from-env"
    assert MyRC.bootstrap_result is result


def test_ensure_bootstrapped_runs_once_and_reuses_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On-demand setup never reloads an already bootstrapped declaration."""
    MyRC = _config_only_app()
    expected = _bootstrap_result()
    calls = 0

    def fake_bootstrap_env(**_: object) -> EnvBootstrapResult:
        """Record one low-level bootstrap call."""
        nonlocal calls
        calls += 1
        return expected

    monkeypatch.setattr(
        "apprc.definition.app_config.kit.bootstrap_env",
        fake_bootstrap_env,
    )

    first = MyRC.ensure_bootstrapped()
    second = MyRC.ensure_bootstrapped()

    assert first is expected
    assert second is expected
    assert MyRC.bootstrap_result is expected
    assert calls == 1


def test_ensure_bootstrapped_serializes_concurrent_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent convenience callers share one initial bootstrap."""
    MyRC = _config_only_app()
    expected = _bootstrap_result()
    calls = 0

    def fake_bootstrap_env(**_: object) -> EnvBootstrapResult:
        """Leave enough time for competing callers to reach the state lock."""
        nonlocal calls
        calls += 1
        sleep(0.01)
        return expected

    monkeypatch.setattr(
        "apprc.definition.app_config.kit.bootstrap_env",
        fake_bootstrap_env,
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(
            executor.map(lambda _: MyRC.ensure_bootstrapped(), range(8))
        )

    assert all(result is expected for result in results)
    assert calls == 1


def test_explicit_rebootstrap_warns_and_keeps_latest_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Explicit reloads stay allowed and failed reloads retain good metadata."""
    MyRC = _config_only_app()
    first = _bootstrap_result(storage_count=1)
    second = _bootstrap_result(storage_count=2)
    results = iter((first, second))

    def fake_bootstrap_env(**_: object) -> EnvBootstrapResult:
        """Return two successes and then fail the next explicit reload."""
        try:
            return next(results)
        except StopIteration as exc:
            raise RuntimeError("reload failed") from exc

    monkeypatch.setattr(
        "apprc.definition.app_config.kit.bootstrap_env",
        fake_bootstrap_env,
    )

    assert MyRC.bootstrap(load_dotenv_layers=False) is first
    assert MyRC.bootstrap(load_dotenv_layers=False) is second
    with pytest.raises(RuntimeError, match="reload failed"):
        MyRC.bootstrap(load_dotenv_layers=False)

    assert MyRC.bootstrap_result is second
    assert caplog.text.count("AppRC bootstrap is running again") == 2


def test_late_config_registration_warns_and_preserves_bootstrap_state(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Late schema additions remain possible but report incomplete provenance."""
    MyRC = _config_only_app()
    expected = _bootstrap_result()
    monkeypatch.setattr(
        "apprc.definition.app_config.kit.bootstrap_env",
        lambda **_: expected,
    )
    MyRC.bootstrap(load_dotenv_layers=False)

    @MyRC.config("late", prefix="LATE_")
    class LateConfig(rc.Config):
        value: str = rc.field("LATE_VALUE", default="fallback")

    assert LateConfig().value == "fallback"
    assert MyRC.bootstrap_result is expected
    assert "Registering config LateConfig after AppRC bootstrap" in caplog.text


def test_mounted_cli_bootstrap_updates_public_app_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typer bootstrap and direct Python calls share one result."""
    MyRC = _config_only_app()
    expected = _bootstrap_result()
    monkeypatch.setattr(
        "apprc.definition.app_config.kit.bootstrap_env",
        lambda **_: expected,
    )
    app = typer.Typer()
    MyRC.mount_cli(app)

    @app.command()
    def run() -> None:
        """Exercise the mounted runtime callback."""

    result = CliRunner().invoke(app, ["run"])

    assert result.exit_code == 0
    assert MyRC.bootstrap_result is expected


def test_public_config_runtime_assignment_updates_provenance() -> None:
    """Public ``rc.Config`` subclasses stay slotted like the internal engine."""
    MyRC = _config_only_app()
    assert MyRC.bootstrap_result is None

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    config = LLMConfig(provider="constructor")  # pyright: ignore[reportCallIssue]
    assert config.provenance()["provider"].origin == (
        "python_constructor_argument"
    )

    config.provider = "runtime"

    assert config.provenance()["provider"].origin == (
        "python_runtime_assignment"
    )
