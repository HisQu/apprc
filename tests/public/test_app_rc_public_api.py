"""Public AppRC facade behavior tests."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

import pytest
import typer

import apprc as rc


def _process_env_app() -> rc.AppRC:
    """Return a process-environment-only public AppRC facade for tests."""
    return rc.AppRC(
        app_id="public-demo",
        display_name="Public Demo",
        config_package="apprc",
    )


def test_direct_declaration_accepts_optional_storage() -> None:
    """One constructor expresses process-only and storage applications."""
    MyRC = rc.AppRC(
        app_id="haiu",
        display_name="HAIU",
        config_package="haiu.config",
        storage=rc.Storage(selector_env_key="HAIU_STORAGE"),
    )

    assert MyRC.schema.app_id == "haiu"
    assert MyRC.schema.display_name == "HAIU"
    assert MyRC.schema.storage_selector_env_key == "HAIU_STORAGE"
    assert MyRC.schema.defaults_dotenv_filename == "apprc.defaults.env"
    assert MyRC.schema.user_dotenv_filename == "apprc.user.env"
    assert MyRC.schema.storage_dotenv_filename == "apprc.storage.env"
    assert MyRC.schema.apprc_toml_filename == "apprc.toml"


def test_direct_declaration_accepts_independent_user_dotenv() -> None:
    MyRC = rc.AppRC(
        app_id="demo",
        config_package="demo.config",
        user_dotenv=rc.UserDotenv(),
    )

    assert MyRC.schema.uses_user_dotenv() is True
    assert MyRC.schema.uses_storage() is False


def test_legacy_mode_constructors_are_removed() -> None:
    assert not hasattr(rc.AppRC, "env_only")
    assert not hasattr(rc.AppRC, "storage_only")
    assert not hasattr(rc.AppRC, "app_wide_config")
    assert not hasattr(rc.AppRC, "app_wide_storage")


def test_registers_env_backed_config_with_full_env_keys() -> None:
    """Full public env keys are adapted to owner-local suffixes."""
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_", title="LLM")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.env_prefix == "HAIU_LLM_"
    assert LLMConfig.config_owner.field("provider").env_var == "PROVIDER"
    assert rc.schema.owner_for(LLMConfig) is LLMConfig.config_owner
    assert MyRC.schema.envs == (LLMConfig,)


def test_schema_owner_for_rejects_unregistered_config() -> None:
    """Schema inspection requires prior AppRC registration."""

    class UnregisteredConfig(rc.Config):
        value: str = rc.field("UNREGISTERED_VALUE", default="value")

    with pytest.raises(TypeError, match="registered with @AppRC.config"):
        rc.schema.owner_for(UnregisteredConfig)


def test_registers_python_only_config_base() -> None:
    """Python-only config classes use normal dataclass defaults."""
    MyRC = _process_env_app()

    @MyRC.config("resources", title="Resources")
    class PackageResources(rc.ConfigBase):
        package: str = "haiu.resources"
        templates: str = "templates"

    resources = PackageResources()
    assert resources.package == "haiu.resources"
    assert resources.templates == "templates"
    assert MyRC.schema.envs == ()


def test_rejects_missing_key_decorator_forms() -> None:
    """The registration decorator always requires an explicit key."""
    MyRC = _process_env_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="requires a config key string"):
        MyRC.config(LLMConfig)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        MyRC.config()  # type: ignore[call-arg]


def test_rejects_missing_prefix_for_env_config() -> None:
    """Env-backed config classes require a non-empty prefix."""
    MyRC = _process_env_app()

    with pytest.raises(ValueError, match='requires prefix="..."'):

        @MyRC.config("llm")
        class LLMConfig(rc.Config):
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_prefix_for_config_base() -> None:
    """Python-only config classes cannot receive an env prefix."""
    MyRC = _process_env_app()

    with pytest.raises(ValueError, match="Python-only config"):

        @MyRC.config("resources", prefix="HAIU_RESOURCES_")
        class PackageResources(rc.ConfigBase):
            package: str = "haiu.resources"


def test_rejects_plain_decorator_only_class() -> None:
    """Registered classes must inherit the public config bases."""
    MyRC = _process_env_app()

    with pytest.raises(TypeError, match="must inherit from rc.Config"):

        @MyRC.config("llm", prefix="HAIU_LLM_")  # pyright: ignore[reportArgumentType]
        class LLMConfig:
            provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")


def test_rejects_public_fields_on_config_base() -> None:
    """``rc.field`` belongs only to env-backed ``rc.Config`` classes."""
    MyRC = _process_env_app()

    with pytest.raises(TypeError, match="uses rc.field"):

        @MyRC.config("resources")
        class PackageResources(rc.ConfigBase):
            package: str = rc.field("HAIU_PACKAGE")


def test_rejects_env_key_without_required_prefix() -> None:
    """Every public env key must start with the registered prefix."""
    MyRC = _process_env_app()

    with pytest.raises(ValueError, match="requires prefix HAIU_LLM_"):

        @MyRC.config("llm", prefix="HAIU_LLM_")
        class LLMConfig(rc.Config):
            provider: str = rc.field("OPENAI_PROVIDER", default="openai")


def test_rejects_duplicate_config_keys() -> None:
    """Different classes cannot reuse one config key."""
    MyRC = _process_env_app()

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
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        token: str = rc.field("HAIU_LLM_TOKEN", secret=True)

    with pytest.raises(ValueError, match="HAIU_LLM_TOKEN"):

        @MyRC.config("rag", prefix="HAIU_")
        class RAGConfig(rc.Config):
            token: str = rc.field("HAIU_LLM_TOKEN", secret=True)


def test_requiredness_inference() -> None:
    """Fields without defaults are required and fields with defaults are not."""
    MyRC = _process_env_app()

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
    MyRC = _process_env_app()
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


def test_field_rejects_unknown_keyword_options() -> None:
    """Misspelled field options fail instead of becoming unused metadata."""
    with pytest.raises(TypeError, match="secrte"):
        rc.field("HAIU_LLM_TOKEN", secrte=True)  # type: ignore[call-arg]


def test_field_accepts_explicit_compatibility_options() -> None:
    """Supported legacy and advanced options remain visible in the signature."""
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field(
            "HAIU_LLM_PROVIDER",
            shared_default="openai",
            python_type=str,
            explanation_short="Provider name.",
            explanation_long="Provider name used for model calls.",
        )

    assert LLMConfig.config_owner is not None
    spec = LLMConfig.config_owner.field("provider")
    assert spec.packaged_default == "openai"
    assert spec.explanation_short == "Provider name."


def test_required_field_allows_packaged_default_and_constructor_value() -> None:
    """Packaged and explicit runtime values remain valid for required fields."""
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field(
            "HAIU_LLM_PROVIDER",
            required=True,
            packaged_default="openai",
        )

    config = LLMConfig(provider="mock")

    assert config.provider == "mock"
    assert LLMConfig.config_owner is not None
    assert LLMConfig.config_owner.field("provider").required is True


def test_bundle_eager_construction_and_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundles eagerly construct registered children and allow object injection."""
    MyRC = _process_env_app()
    monkeypatch.setenv("HAIU_LLM_API_KEY", "secret-value")

    @MyRC.config("llm", prefix="HAIU_LLM_", title="LLM")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")
        api_key: str = rc.field("HAIU_LLM_API_KEY", secret=True)

    @MyRC.config("resources", title="Resources")
    class PackageResources(rc.ConfigBase):
        package: str = "haiu.resources"

    @MyRC.bundle
    @dataclass(kw_only=True)
    class HAIUConfig:
        llm: LLMConfig = dataclass_field(default_factory=LLMConfig)
        resources: PackageResources = dataclass_field(
            default_factory=PackageResources
        )

    config = HAIUConfig()
    assert isinstance(config.llm, LLMConfig)
    assert isinstance(config.resources, PackageResources)
    assert config.llm.api_key == "secret-value"
    assert "secret-value" not in repr(config)

    injected = LLMConfig(provider="mock")
    injected_bundle = HAIUConfig(llm=injected)
    assert injected_bundle.llm is injected

    with pytest.raises(TypeError, match="unexpected config argument"):
        HAIUConfig(other=object())  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="expected LLMConfig, got object"):
        HAIUConfig(llm=object())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected LLMConfig, got dict"):
        HAIUConfig(llm={"provider": "mock"})  # type: ignore[arg-type]


def test_bundle_rejects_unregistered_config_class() -> None:
    """Bundle entries must be registered with the same AppRC instance."""
    MyRC = _process_env_app()

    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="not registered with this AppRC"):

        @MyRC.bundle
        @dataclass(kw_only=True)
        class HAIUConfig:
            llm: LLMConfig = dataclass_field(default_factory=LLMConfig)


def test_bundle_rejects_annotation_only_class() -> None:
    """Bundles require a constructor that static analyzers can inspect."""
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    with pytest.raises(TypeError, match="explicit keyword-only dataclass"):

        @MyRC.bundle
        class HAIUConfig:
            llm: LLMConfig


def test_bundle_rejects_non_keyword_and_missing_factory_fields() -> None:
    """Bundle dataclasses must describe their real optional keyword API."""
    MyRC = _process_env_app()

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    @dataclass
    class PositionalBundle:
        llm: LLMConfig = dataclass_field(default_factory=LLMConfig)

    with pytest.raises(TypeError, match="must be keyword-only"):
        MyRC.bundle(PositionalBundle)

    @dataclass(kw_only=True)
    class MissingFactoryBundle:
        llm: LLMConfig

    with pytest.raises(TypeError, match="default_factory=LLMConfig"):
        MyRC.bundle(MissingFactoryBundle)


def test_bundle_supports_post_init_derived_config_fields() -> None:
    """Bundles validate registered init=False fields and call post-init."""
    MyRC = _process_env_app()

    @MyRC.config("storage", title="Storage")
    @dataclass
    class StorageConfig(rc.ConfigBase):
        root: str = "storage"

    @MyRC.config("rag", title="RAG")
    @dataclass
    class RagConfig(rc.ConfigBase):
        storage: StorageConfig

    @MyRC.bundle
    @dataclass(kw_only=True)
    class HAIUConfig:
        storage: StorageConfig = dataclass_field(default_factory=StorageConfig)
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
    injected = HAIUConfig(storage=injected_storage)
    assert injected.storage is injected_storage
    assert injected.rag.storage is injected_storage

    with pytest.raises(TypeError, match="unexpected config argument"):
        HAIUConfig(rag=RagConfig(storage=injected_storage))  # type: ignore[call-arg]


def test_bundle_preserves_post_init_hook_class_identity() -> None:
    """Bundle hooks can call super and derive registered children."""
    MyRC = _process_env_app()
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

    @dataclass(kw_only=True)
    class HAIUConfig(BundlePostInitBase):
        storage: StorageConfig = dataclass_field(default_factory=StorageConfig)
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
    MyRC = _process_env_app()

    @MyRC.config("storage", title="Storage")
    class StorageConfig(rc.ConfigBase):
        root: str = "storage"

    @MyRC.bundle
    @dataclass(kw_only=True)
    class HAIUConfig(rc.ConfigBase):
        storage: StorageConfig = dataclass_field(default_factory=StorageConfig)

    config = HAIUConfig()
    assert isinstance(config.storage, StorageConfig)


def test_mount_cli_accepts_only_typer() -> None:
    """The public mount method is Typer-specific."""
    MyRC = _process_env_app()
    app = typer.Typer()

    mounted = rc.cli.mount_config_cli(app, MyRC)
    assert isinstance(mounted, typer.Typer)

    with pytest.raises(TypeError, match="typer.Typer instances only"):
        rc.cli.mount_config_cli(object(), MyRC)  # type: ignore[arg-type]


def test_explicit_resolution_constructs_registered_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual resolution supplies captured values to config construction."""
    MyRC = _process_env_app()
    monkeypatch.setenv("PUBLIC_BOOTSTRAP_VALUE", "from-env")

    @MyRC.config("demo", prefix="PUBLIC_BOOTSTRAP_")
    class DemoConfig(rc.Config):
        value: str = rc.field("PUBLIC_BOOTSTRAP_VALUE")

    result = MyRC.resolve(rc.ResolveOptions(load_dotenv_layers=False))
    config = result.build(DemoConfig)

    assert config.value == "from-env"
    assert not hasattr(MyRC, "bootstrap_result")


def test_public_config_runtime_assignment_updates_provenance() -> None:
    """Public ``rc.Config`` subclasses stay slotted like the internal engine."""
    MyRC = _process_env_app()
    assert not hasattr(MyRC, "bootstrap_result")

    @MyRC.config("llm", prefix="HAIU_LLM_")
    class LLMConfig(rc.Config):
        provider: str = rc.field("HAIU_LLM_PROVIDER", default="openai")

    config = LLMConfig(provider="constructor")
    assert config.provenance()["provider"].origin == (
        "python_constructor_argument"
    )

    config.provider = "runtime"

    assert config.provenance()["provider"].origin == (
        "python_runtime_assignment"
    )
