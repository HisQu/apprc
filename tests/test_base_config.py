from __future__ import annotations
from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, cast

import pytest
from typed_settings.exceptions import InvalidSettingsError

import apprc as rc
import apprc.definition.env_config.base as base_config
import apprc.definition.env_config._loading as env_loading
import apprc.public.config as config_runtime_module
from apprc.definition.env_config.base import BaseConfig
from apprc.runtime.provenance import (
    ConfigProvenance,
    PythonProvenanceOrigin,
)


@dataclass(slots=True)
class _NestedConfig:
    visible: str
    secret: str = field(repr=False)


@dataclass(slots=True)
class _RuntimeConfig(BaseConfig):
    name: str
    path: Path
    nested: _NestedConfig


@dataclass(slots=True)
class _DefaultRuntimeConfig(BaseConfig):
    name: str = "demo"
    secret: str = field(default="token", repr=False)
    _private: str = "private"
    internal: str = field(default="internal", metadata={"internal": True})


@dataclass(slots=True)
class _MutableRuntimeConfig(BaseConfig):
    items: list[str] = field(default_factory=list)
    module: ModuleType = base_config


@dataclass(slots=True)
class _ExtendedRuntimeConfig(_DefaultRuntimeConfig):
    extra: str = "extra"


@dataclass(slots=True)
class _RuntimeConfigWithNestedConfig(BaseConfig):
    nested: _DefaultRuntimeConfig = field(default_factory=_DefaultRuntimeConfig)


class _CooperativeAllocationMixin:
    """Record instance allocation reached through the cooperative MRO."""

    __slots__ = ()
    allocation_calls: ClassVar[int] = 0

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        """Count one allocation before delegating to the next MRO class."""
        _CooperativeAllocationMixin.allocation_calls += 1
        return super().__new__(cls)


@dataclass(slots=True)
class _CooperativeRuntimeConfig(BaseConfig, _CooperativeAllocationMixin):
    name: str = "demo"


class _CooperativeAssignmentMixin(BaseConfig):
    """Record assignment-hook dispatch through an intermediate base."""

    __slots__ = ()
    assignment_calls: ClassVar[int] = 0

    def _after_existing_assignment(
        self,
        key: str,
        value: Any,
        *,
        origin: PythonProvenanceOrigin,
    ) -> None:
        """Count one assignment before delegating to the next MRO class."""
        _CooperativeAssignmentMixin.assignment_calls += 1
        super()._after_existing_assignment(key, value, origin=origin)


_CONFIG_TEST_RC = rc.AppRC(
    app_id="config_test",
    display_name="Config Test",
    config_package="config_test.config",
)


@_CONFIG_TEST_RC.config(
    "cooperative",
    title="Cooperative",
    prefix="COOPERATIVE_",
    rc_path=("cooperative",),
)
class _CooperativeConfig(rc.Config, _CooperativeAssignmentMixin):
    value: str = rc.field("COOPERATIVE_VALUE", default="initial")


@dataclass(slots=True)
class _UnregisteredConfig(rc.Config):
    value: str = "fallback"


@_CONFIG_TEST_RC.config(
    "demo_runtime",
    title="Demo Runtime",
    prefix="DEMO_",
    rc_path=("demo",),
)
class _DemoConfig(rc.Config):
    mode: str = rc.field(
        "DEMO_MODE", default="AUTO", choices=("AUTO", "MANUAL")
    )
    retries: int = rc.field("DEMO_RETRIES", default=3)
    enabled: bool = rc.field("DEMO_ENABLED", default=False)
    token: str = rc.field("DEMO_TOKEN", default="demo-token", secret=True)


_factory_counter = 0


def _next_factory_path() -> Path:
    """Return a visibly fresh path for default-factory tests."""
    global _factory_counter
    _factory_counter += 1
    return Path(f"factory-{_factory_counter}")


@_CONFIG_TEST_RC.config(
    "demo_factory",
    title="Demo Factory",
    prefix="FACTORY_",
    rc_path=("demo", "factory"),
)
class _FactoryConfig(rc.Config):
    cache_dir: Path = rc.field(
        "FACTORY_CACHE_DIR", default_factory=_next_factory_path
    )


@_CONFIG_TEST_RC.config(
    "demo_required",
    title="Demo Required",
    prefix="REQUIRED_",
    rc_path=("demo", "required"),
)
class _RequiredConfig(rc.Config):
    value: str = rc.field("REQUIRED_VALUE", title="Required value")


class _LogSink:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _clear_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = rc.schema.owner_for(_DemoConfig)
    for spec in owner.fields:
        monkeypatch.delenv(owner.env_key(spec.name), raising=False)


def test_base_config_to_dict_redacts_private_dataclass_fields(
    tmp_path: Path,
) -> None:
    config = _RuntimeConfig(
        name="demo",
        path=tmp_path / "storage",
        nested=_NestedConfig(visible="ok", secret="token"),
    )

    assert config.to_dict() == {
        "name": "demo",
        "path": str(tmp_path / "storage"),
        "nested": {
            "visible": "ok",
            "secret": "<redacted>",
        },
    }


def test_base_config_new_continues_through_cooperative_mro() -> None:
    _CooperativeAllocationMixin.allocation_calls = 0

    config = _CooperativeRuntimeConfig()

    assert config.name == "demo"
    assert _CooperativeAllocationMixin.allocation_calls == 1


def test_base_config_copy_preserves_resolved_state_without_constructor() -> (
    None
):
    config = _RuntimeConfig(
        name="demo",
        path=Path("storage"),
        nested=_NestedConfig(visible="ok", secret="token"),
    )

    shallow = copy(config)
    deep = deepcopy(config)

    assert shallow == config
    assert shallow is not config
    assert shallow.nested is config.nested
    assert deep == config
    assert deep.nested is not config.nested


def test_base_config_provenance_reports_public_python_origins() -> None:
    config = _DefaultRuntimeConfig(name="manual")

    provenance = config.provenance()

    assert set(provenance) == {"name", "secret"}
    assert provenance["name"].source == "python"
    assert provenance["name"].origin == "python_constructor_argument"
    assert provenance["secret"].source == "python"
    assert provenance["secret"].origin == "python_baseconfig_default"
    assert provenance["secret"].secret is True
    assert provenance["secret"].display_value == "<redacted>"


def test_base_config_assignment_updates_provenance() -> None:
    config = _DefaultRuntimeConfig()

    config.name = "assigned"

    assert config.provenance_of("name").source == "python"
    assert config.provenance_of("name").origin == "python_runtime_assignment"


def test_base_config_copy_preserves_provenance() -> None:
    config = _DefaultRuntimeConfig(name="manual")
    config.secret = "new-token"

    shallow = copy(config)
    deep = deepcopy(config)

    assert shallow.provenance_of("name").origin == "python_constructor_argument"
    assert deep.provenance_of("secret").origin == "python_runtime_assignment"


def test_base_config_create_or_update_constructs_with_overrides() -> None:
    config = _DefaultRuntimeConfig.create_or_update(name="manual")

    assert config.name == "manual"
    assert config.provenance_of("name").origin == "python_constructor_argument"


def test_base_config_create_or_update_persists_on_existing_config() -> None:
    config = _DefaultRuntimeConfig(name="base")

    updated = _DefaultRuntimeConfig.create_or_update(
        cfg=config,
        name="persistent",
        secret=None,
    )

    assert updated is config
    assert config.name == "persistent"
    assert config.secret == "token"
    assert config.provenance_of("name").origin == "python_runtime_assignment"
    assert config.provenance_of("secret").origin == "python_baseconfig_default"


def test_base_config_create_or_update_rejects_unknown_field() -> None:
    config = _DefaultRuntimeConfig()

    with pytest.raises(KeyError, match="unknown"):
        _DefaultRuntimeConfig.create_or_update(cfg=config, unknown=None)

    assert not hasattr(config, "unknown")


def test_base_config_create_or_update_validates_actual_cfg_fields() -> None:
    config = _ExtendedRuntimeConfig()

    updated = BaseConfig.create_or_update(cfg=config, extra="persistent")

    assert updated is config
    assert config.extra == "persistent"
    assert config.provenance_of("extra").origin == "python_runtime_assignment"


def test_base_config_create_or_update_rejects_sibling_config() -> None:
    other = _RuntimeConfig(
        name="demo",
        path=Path("storage"),
        nested=_NestedConfig(visible="ok", secret="token"),
    )

    create_or_update = cast(Any, _DefaultRuntimeConfig.create_or_update)
    with pytest.raises(TypeError, match="cfg must be an instance"):
        create_or_update(cfg=other)


def test_base_config_scoped_returns_clone_and_preserves_original() -> None:
    config = _DefaultRuntimeConfig(name="base")

    scoped = config.scoped(name="request")

    assert scoped is not config
    assert scoped.name == "request"
    assert config.name == "base"
    assert scoped.provenance_of("name").origin == "python_scoped_override"
    assert config.provenance_of("name").origin == "python_constructor_argument"


def test_base_config_scoped_preserves_untouched_provenance() -> None:
    config = _DefaultRuntimeConfig(name="manual")

    scoped = config.scoped(secret="request-token")

    assert scoped.name == "manual"
    assert scoped.secret == "request-token"
    assert scoped.provenance_of("name").origin == "python_constructor_argument"
    assert scoped.provenance_of("secret").origin == "python_scoped_override"
    assert config.secret == "token"


def test_base_config_scoped_rejects_unknown_field() -> None:
    config = _DefaultRuntimeConfig()

    with pytest.raises(KeyError, match="unknown"):
        config.scoped(unknown="value")


def test_base_config_scoped_rejects_unknown_field_before_skipping_none() -> (
    None
):
    config = _DefaultRuntimeConfig()

    with pytest.raises(KeyError, match="unknown"):
        config.scoped(unknown=None)


def test_base_config_scoped_kwargs_win_over_mapping() -> None:
    config = _DefaultRuntimeConfig(name="base")

    scoped = config.scoped({"name": "mapping"}, name="kwarg")

    assert scoped.name == "kwarg"
    assert config.name == "base"


def test_base_config_scoped_without_overrides_still_returns_clone() -> None:
    config = _DefaultRuntimeConfig(name="base")

    scoped = config.scoped()

    assert scoped is not config
    assert scoped == config


def test_base_config_scoped_skips_none_by_default() -> None:
    config = _DefaultRuntimeConfig(name="base")

    scoped = config.scoped(name=None)

    assert scoped is not config
    assert scoped.name == "base"
    assert scoped.provenance_of("name").origin == "python_constructor_argument"


def test_base_config_scoped_can_apply_none_when_requested() -> None:
    config = _DefaultRuntimeConfig(name="base")

    scoped = config.scoped({"name": None}, skip_none=False)

    assert getattr(scoped, "name") is None
    assert scoped.provenance_of("name").origin == "python_scoped_override"
    assert config.name == "base"


def test_base_config_scoped_deep_copies_mutable_state() -> None:
    config = _MutableRuntimeConfig(items=["base"])

    scoped = config.scoped()
    scoped.items.append("request")

    assert scoped.items == ["base", "request"]
    assert config.items == ["base"]
    assert scoped.module is base_config


def test_base_config_scoped_from_filters_non_config_names() -> None:
    config = _DefaultRuntimeConfig(name="base")

    def _build_scoped(name: str, ignored: str) -> _DefaultRuntimeConfig:
        return config.scoped_from(locals())

    scoped = _build_scoped(name="request", ignored="ignored")

    assert scoped.name == "request"
    assert scoped.provenance_of("name").origin == "python_scoped_override"


def test_base_config_scoped_does_not_log_mutation_or_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _DefaultRuntimeConfig()
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)

    scoped = config.scoped(name="request")

    assert scoped.name == "request"
    assert sink.warnings == []


def test_base_config_copy_logs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _DefaultRuntimeConfig()
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)

    copied = copy(config)

    assert copied is not config
    assert sink.warnings == ["Config copied: _DefaultRuntimeConfig (copy)"]


def test_base_config_deepcopy_logs_once_for_nested_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _RuntimeConfigWithNestedConfig()
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)

    copied = deepcopy(config)

    assert copied is not config
    assert copied.nested is not config.nested
    assert sink.warnings == [
        "Config copied: _RuntimeConfigWithNestedConfig (deepcopy)"
    ]


def test_app_rc_registration_derives_config_owner() -> None:
    owner = rc.schema.owner_for(_DemoConfig)

    assert owner.key == "demo_runtime"
    assert owner.env_key("mode") == "DEMO_MODE"
    assert owner.config_path("retries") == ("demo", "retries")
    assert owner.field("mode").python_type is str
    assert owner.field("mode").default == "AUTO"
    assert owner.field("mode").choices == ("AUTO", "MANUAL")
    assert owner.field("token").secret is True


def test_app_rc_registration_preserves_post_init_hook_class_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Config hooks can call super and derive runtime fields."""
    monkeypatch.setenv("HOOK_STORAGE", str(tmp_path))
    hook_rc = rc.AppRC(
        app_id="hook_test",
        display_name="Hook Test",
        config_package="hook_test.config",
    )

    class HookConfig(rc.Config):
        storage_root: Path = rc.field("HOOK_STORAGE")
        cache_dir: Path = field(init=False)

        def __post_init__(self) -> None:
            """Derive paths after Config binds environment values."""
            super().__post_init__()
            self.cache_dir = self.storage_root / "cache"

    RegisteredHookConfig = hook_rc.config(
        "hook",
        title="Hook",
        prefix="HOOK_",
        rc_path=("hook",),
    )(HookConfig)

    config = RegisteredHookConfig()

    assert RegisteredHookConfig is HookConfig
    assert config.storage_root == tmp_path
    assert config.cache_dir == tmp_path / "cache"


def test_config_owner_reuses_generated_settings_class() -> None:
    owner = rc.schema.owner_for(_DemoConfig)

    assert owner.settings_class() is owner.settings_class()


def test_field_rejects_default_and_default_factory() -> None:
    with pytest.raises(ValueError, match="default and default_factory"):
        rc.field("VALUE", default="x", default_factory=lambda: "y")


def test_config_default_factory_resolves_fresh_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FACTORY_CACHE_DIR", raising=False)

    first = _FactoryConfig()
    second = _FactoryConfig()

    assert first.cache_dir != second.cache_dir
    assert first.provenance_of("cache_dir").origin == "python_config_default"


def test_config_rejects_invalid_runtime_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "BOGUS")

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _DemoConfig()


def test_config_requires_app_rc_registration() -> None:
    with pytest.raises(RuntimeError, match="registered with @MyRC.config"):
        _UnregisteredConfig(bind_from_env_on_init=False)


def test_config_python_keyword_argument_overrides_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoConfig(mode="MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.retries == 9
    mode_provenance = cfg.provenance_of("mode")
    retries_provenance = cfg.provenance_of("retries")
    assert isinstance(mode_provenance, ConfigProvenance)
    assert mode_provenance.source == "python"
    assert mode_provenance.origin == "python_constructor_argument"
    assert mode_provenance.env_key == "DEMO_MODE"
    assert mode_provenance.value == "MANUAL"
    assert retries_provenance.source == "shell"
    assert retries_provenance.origin == "shell_export_variable"
    assert retries_provenance.value == 9


def test_config_python_constructor_argument_ignores_invalid_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    cfg = _DemoConfig(retries=4)

    assert cfg.retries == 4
    assert cfg.provenance_of("retries").origin == "python_constructor_argument"


def test_config_override_python_values_reads_invalid_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig(retries=4)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    with pytest.raises(InvalidSettingsError, match="converting"):
        cfg.reload(override_python_values=True)


def test_config_python_constructor_argument_override_stays_quiet_during_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoConfig(mode="MANUAL")

    assert cfg.mode == "MANUAL"
    assert sink.warnings == []


def test_config_rejects_invalid_python_choice_arg() -> None:
    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _DemoConfig(mode="BOGUS")


def test_config_rejects_wrong_python_constructor_argument_type() -> None:
    with pytest.raises(TypeError, match="DEMO_RETRIES must be int; got str"):
        _DemoConfig(retries="4")  # pyright: ignore[reportArgumentType]


def test_config_rejects_invalid_python_choice_assignment() -> None:
    cfg = _DemoConfig()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.mode = "BOGUS"

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "python_config_default"


def test_config_assignment_continues_through_cooperative_mro() -> None:
    _CooperativeAssignmentMixin.assignment_calls = 0
    config = _CooperativeConfig()

    config.value = "changed"

    assert config.value == "changed"
    assert _CooperativeAssignmentMixin.assignment_calls == 1


def test_config_rejects_wrong_python_assignment_type() -> None:
    cfg = _DemoConfig()

    with pytest.raises(TypeError, match="DEMO_ENABLED must be bool; got str"):
        cfg.enabled = "true"  # pyright: ignore[reportAttributeAccessIssue]

    assert cfg.enabled is False
    assert cfg.provenance_of("enabled").origin == "python_config_default"


def test_app_rc_registration_rejects_wrong_python_default_type() -> None:
    bad_default_rc = rc.AppRC(
        app_id="bad_default_test",
        display_name="Bad Default Test",
        config_package="bad_default_test.config",
    )
    with pytest.raises(TypeError, match="retries must be int; got str"):

        @bad_default_rc.config(
            "bad_default",
            title="Bad Default",
            prefix="BAD_DEFAULT_",
            rc_path=("demo", "bad_default"),
        )
        class _BadDefaultConfig(rc.Config):
            retries: int = rc.field("BAD_DEFAULT_RETRIES", default="3")


def test_config_python_positional_argument_overrides_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoConfig("MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.provenance_of("mode").origin == "python_constructor_argument"


def test_config_absent_env_fields_report_config_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    cfg = _DemoConfig()

    assert cfg.mode == "AUTO"
    assert cfg.retries == 3
    assert cfg.provenance_of("mode").source == "python"
    assert cfg.provenance_of("mode").origin == "python_config_default"
    assert cfg.provenance_of("retries").origin == "python_config_default"


def test_config_defaults_resolve_when_env_binding_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoConfig(bind_from_env_on_init=False)

    assert cfg.retries == 3
    assert cfg.provenance_of("retries").origin == "python_config_default"


def test_config_provenance_returns_all_owner_field_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "6")

    cfg = _DemoConfig(mode="MANUAL")

    provenance = cfg.provenance()
    assert set(provenance) == {"mode", "retries", "enabled", "token"}
    assert provenance["mode"].origin == "python_constructor_argument"
    assert provenance["retries"].origin == "shell_export_variable"
    assert provenance["enabled"].origin == "python_config_default"


def test_config_secret_source_redacts_repr_and_keeps_raw_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    source = _DemoConfig().provenance_of("token")

    assert source.secret is True
    assert source.value == "demo-token"
    assert source.display_value == "<redacted>"
    assert "demo-token" not in repr(source)
    assert "<redacted>" in repr(source)


def test_config_required_field_can_be_supplied_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRED_VALUE", "from-env")

    cfg = _RequiredConfig()

    assert cfg.value == "from-env"
    assert cfg.provenance_of("value").origin == "shell_export_variable"


def test_config_required_field_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUIRED_VALUE", raising=False)

    with pytest.raises(RuntimeError, match="REQUIRED_VALUE"):
        _RequiredConfig()


def test_config_synthetic_mapping_loaders_do_not_depend_on_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoCwdPath:
        @staticmethod
        def cwd() -> Path:
            raise AssertionError("synthetic env loaders should not read cwd")

    owner = rc.schema.owner_for(_DemoConfig)
    retries_field = next(
        spec for spec in owner.fields if spec.name == "retries"
    )
    monkeypatch.setattr(env_loading, "Path", _NoCwdPath)

    loaded = env_loading.load_owner_from_env(
        owner,
        {owner.env_key("retries"): "11"},
    )

    assert loaded.retries == 11
    assert env_loading.parse_env_field_value(retries_field, "12") == 12


def test_config_python_assignment_survives_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(config_runtime_module, "LOG", sink)
    cfg = _DemoConfig()
    cfg.mode = "MANUAL"
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload()

    assert cfg.mode == "MANUAL"
    assert cfg.provenance_of("mode").origin == "python_runtime_assignment"
    assert any("mode" in warning for warning in sink.warnings)
    assert any(
        "override_python_values=True" in warning for warning in sink.warnings
    )


def test_config_reload_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_config_bind_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.bind_from_env(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_config_scoped_owner_field_records_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig()

    scoped = cfg.scoped(mode="MANUAL")
    provenance = scoped.provenance_of("mode")

    assert scoped is not cfg
    assert scoped.mode == "MANUAL"
    assert cfg.mode == "AUTO"
    assert provenance.source == "python"
    assert provenance.origin == "python_scoped_override"
    assert provenance.env_key == "DEMO_MODE"


def test_config_scoped_validates_owner_choices_and_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.scoped(mode="BOGUS")
    with pytest.raises(TypeError, match="DEMO_ENABLED must be bool; got str"):
        cfg.scoped(enabled="true")

    assert cfg.mode == "AUTO"
    assert cfg.enabled is False


def test_config_scoped_preserves_owner_default_without_factory_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FACTORY_CACHE_DIR", raising=False)
    cfg = _FactoryConfig()
    factory_count = _factory_counter

    scoped = cfg.scoped()

    assert scoped is not cfg
    assert scoped.cache_dir == cfg.cache_dir
    assert _factory_counter == factory_count


def test_config_reload_preserves_scoped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig().scoped(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload()

    assert cfg.mode == "MANUAL"
    assert cfg.provenance_of("mode").origin == "python_scoped_override"


def test_config_reload_can_replace_scoped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig().scoped(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_config_copy_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoConfig(mode="MANUAL")

    shallow = copy(cfg)
    deep = deepcopy(cfg)

    assert shallow.provenance_of("mode").origin == "python_constructor_argument"
    assert deep.provenance_of("mode").origin == "python_constructor_argument"
