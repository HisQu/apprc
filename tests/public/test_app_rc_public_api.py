"""Public AppRC facade behavior tests."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

import pytest
import typer

import apprc as rc


def _env_only_app() -> rc.AppRC:
    """Return a small config-only public AppRC facade for tests."""
    return rc.AppRC(
        app_name="public-demo",
        display_name="Public Demo",
        config_package="apprc",
    )


def test_direct_declaration_accepts_optional_storage() -> None:
    """One constructor expresses config-only and storage applications."""
    MyRC = rc.AppRC(
        app_name="haiu",
        display_name="HAIU",
        config_package="haiu.config",
        storage=rc.Storage(env_key="HAIU_STORAGE"),
    )

    assert MyRC.spec.app_name == "haiu"
    assert MyRC.spec.display_name == "HAIU"
    assert MyRC.spec.storage_selector_env_key == "HAIU_STORAGE"
    assert MyRC.spec.defaults_env_filename == "apprc.defaults.env"
    assert MyRC.spec.app_env_filename == "apprc.app.env"
    assert MyRC.spec.require_storage().env_filename == "apprc.storage.env"
    assert MyRC.spec.apprc_toml_filename == "apprc.toml"


def test_legacy_mode_constructors_warn_and_remain_keyword_only() -> None:
    """The 0.19 constructors retain their call contract through 0.20."""
    with pytest.warns(DeprecationWarning, match="removed in 0.21"):
        MyRC = rc.AppRC.storage_only(
            app_name="haiu",
            display_name="HAIU",
            config_package="haiu.config",
            storage_env_key="HAIU_STORAGE",
        )

    assert MyRC.spec.storage_selector_env_key == "HAIU_STORAGE"
    assert MyRC.spec.defaults_env_filename == ".env.shared"
    assert MyRC.spec.app_env_filename == ".env.apprc-app"
    assert MyRC.spec.storage_env_filename == ".env.apprc-storage"
    assert MyRC.spec.apprc_toml_filename == "haiu.apprc.toml"

    with pytest.raises(TypeError):
        rc.AppRC.storage_only("haiu", config_package="haiu.config")  # type: ignore[misc]

    with pytest.raises(TypeError):
        rc.AppRC.storage_only()  # type: ignore[call-arg]


def test_registers_env_backed_config_with_full_env_keys() -> None:
    """Full public env keys are adapted to owner-local suffixes."""
    MyRC = _env_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_", title="LLM")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.env_prefix == "HAIU_LLM_"
    assert LLMConfig.config_owner.field("provider").env_var == "PROVIDER"
    assert MyRC.spec.envs == (LLMConfig,)


def test_registers_python_only_config_base() -> None:
    """Python-only config classes use normal dataclass defaults."""
    MyRC = _env_only_app()

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
    MyRC = _env_only_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="requires a config key string"):
        MyRC.config(LLMConfig)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        MyRC.config()  # type: ignore[call-arg]


def test_rejects_missing_prefix_for_env_config() -> None:
    """Env-backed config classes require a non-empty prefix."""
    MyRC = _env_only_app()

    with pytest.raises(ValueError, match='requires prefix="..."'):

        @MyRC.config("llm")
        class LLMConfig(rc.Config):
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_prefix_for_config_base() -> None:
    """Python-only config classes cannot receive an env prefix."""
    MyRC = _env_only_app()

    with pytest.raises(ValueError, match="Python-only config"):

        @MyRC.config("resources", prefix="HAIU_RESOURCES_")
        class PackageResources(rc.ConfigBase):
            package: str = "haiu.resources"


def test_rejects_plain_decorator_only_class() -> None:
    """Registered classes must inherit the public config bases."""
    MyRC = _env_only_app()

    with pytest.raises(TypeError, match="must inherit from rc.Config"):

        @MyRC.config("llm", prefix="HAIU_LLM_")  # pyright: ignore[reportArgumentType]
        class LLMConfig:
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_public_fields_on_config_base() -> None:
    """``rc.field`` belongs only to env-backed ``rc.Config`` classes."""
    MyRC = _env_only_app()

    with pytest.raises(TypeError, match="uses rc.field"):

        @MyRC.config("resources")
        class PackageResources(rc.ConfigBase):
            package: str = rc.field("HAIU_PACKAGE")


def test_rejects_env_key_without_required_prefix() -> None:
    """Every public env key must start with the registered prefix."""
    MyRC = _env_only_app()

    with pytest.raises(ValueError, match="requires prefix HAIU_LLM_"):

        @MyRC.config("llm", prefix="HAIU_LLM_")
        class LLMConfig(rc.Config):
            provider: str = rc.field("OPENAI_PROVIDER", default="openai")


def test_rejects_duplicate_config_keys() -> None:
    """Different classes cannot reuse one config key."""
    MyRC = _env_only_app()

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
    MyRC = _env_only_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        token: str = rc.field("HAIU_LLM_TOKEN", secret=True)

    with pytest.raises(ValueError, match="HAIU_LLM_TOKEN"):

        @MyRC.config("rag", prefix="HAIU_")
        class RAGConfig(rc.Config):
            token: str = rc.field("HAIU_LLM_TOKEN", secret=True)


def test_requiredness_inference() -> None:
    """Fields without defaults are required and fields with defaults are not."""
    MyRC = _env_only_app()

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
    MyRC = _env_only_app()
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


def test_bundle_eager_construction_and_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundles eagerly construct registered children and allow object injection."""
    MyRC = _env_only_app()
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
    MyRC = _env_only_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="not registered with this AppRC"):

        @MyRC.bundle
        class HAIUConfig:
            llm: LLMConfig


def test_bundle_supports_post_init_derived_config_fields() -> None:
    """Bundles validate registered init=False fields and call post-init."""
    MyRC = _env_only_app()

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
    MyRC = _env_only_app()
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
    MyRC = _env_only_app()

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
    MyRC = _env_only_app()
    app = typer.Typer()

    mounted = MyRC.mount_cli(app)
    assert isinstance(mounted, typer.Typer)

    with pytest.raises(TypeError, match="typer.Typer instances only"):
        MyRC.mount_cli(object())  # type: ignore[arg-type]


def test_manual_bootstrap_allows_later_config_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual bootstrap prepares env state for direct config construction."""
    MyRC = _env_only_app()
    monkeypatch.setenv("PUBLIC_BOOTSTRAP_VALUE", "from-env")

    @MyRC.config("demo", prefix="PUBLIC_BOOTSTRAP_")
    class DemoConfig(rc.Config):
        value: str = rc.field("PUBLIC_BOOTSTRAP_VALUE")

    result = MyRC.bootstrap(load_dotenv_layers=False)
    config = DemoConfig()

    assert config.value == "from-env"
    assert result is not None


def test_public_config_runtime_assignment_updates_provenance() -> None:
    """Public ``rc.Config`` subclasses stay slotted like the internal engine."""
    MyRC = _env_only_app()

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
