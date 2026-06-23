from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typed_settings.exceptions import InvalidSettingsError

import apprc
import apprc.config as config_api
from apprc.config import (
    BaseConfig,
    EnvConfig,
    ConfigFieldSource,
    config_owner_for,
    env_field,
    env_owner,
)
import apprc.config.base_config as base_config
import apprc.config.env_config as env_config_module


@dataclass(slots=True)
class _NestedConfig:
    visible: str
    secret: str = field(repr=False)


@dataclass(slots=True)
class _RuntimeConfig(BaseConfig):
    name: str
    path: Path
    nested: _NestedConfig


@env_owner(
    key="demo",
    title="Demo",
    env_prefix="DEMO_",
    rc_path=("demo",),
)
class _ChoiceEnv(EnvConfig):
    mode: str = env_field("MODE", default="AUTO", choices=("AUTO", "MANUAL"))


@dataclass(slots=True)
class _OwnerlessEnv(EnvConfig):
    value: str = "fallback"


@env_owner(
    key="demo.runtime",
    title="Demo Runtime",
    env_prefix="DEMO_",
    rc_path=("demo",),
)
class _DemoEnv(EnvConfig):
    mode: str = env_field("MODE", default="AUTO", choices=("AUTO", "MANUAL"))
    retries: int = env_field("RETRIES", default=3)
    enabled: bool = env_field("ENABLED", default=False)
    token: str = env_field("TOKEN", default="demo-token", secret=True)


_factory_counter = 0


def _next_factory_path() -> Path:
    """Return a visibly fresh path for default-factory tests."""
    global _factory_counter
    _factory_counter += 1
    return Path(f"factory-{_factory_counter}")


@env_owner(
    key="demo.factory",
    title="Demo Factory",
    env_prefix="FACTORY_",
    rc_path=("demo", "factory"),
)
class _FactoryEnv(EnvConfig):
    cache_dir: Path = env_field("CACHE_DIR", default_factory=_next_factory_path)


@env_owner(
    key="demo.required",
    title="Demo Required",
    env_prefix="REQUIRED_",
    rc_path=("demo", "required"),
)
class _RequiredEnv(EnvConfig):
    value: str = env_field("VALUE", title="Required value")


@env_owner(
    key="demo.implicit",
    title="Demo Implicit",
    env_prefix="IMPLICIT_",
    rc_path=("demo", "implicit"),
)
class _ImplicitEnv(EnvConfig):
    auto_named_value: str = env_field(default="fallback")


@env_owner(
    key="demo.logged",
    title="Logged Demo",
    env_prefix="LOGGED_",
    rc_path=("demo", "logged"),
)
class _LoggedEnv(EnvConfig):
    value: str = env_field("VALUE", default="logged")


@env_owner(
    key="demo.quiet",
    title="Quiet Demo",
    env_prefix="QUIET_",
    rc_path=("demo", "quiet"),
    log_lifecycle=False,
)
class _QuietEnv(EnvConfig):
    value: str = env_field("VALUE", default="quiet")


class _LogSink:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _clear_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = config_owner_for(_DemoEnv)
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


def test_env_owner_derives_config_owner_from_env_config_class() -> None:
    owner = config_owner_for(_DemoEnv)

    assert owner.key == "demo.runtime"
    assert owner.env_key("mode") == "DEMO_MODE"
    assert owner.config_path("retries") == ("demo", "retries")
    assert owner.field("mode").python_type is str
    assert owner.field("mode").default == "AUTO"
    assert owner.field("mode").choices == ("AUTO", "MANUAL")
    assert owner.field("token").secret is True


def test_config_owner_reuses_generated_settings_class() -> None:
    owner = config_owner_for(_DemoEnv)

    assert owner.settings_class() is owner.settings_class()


def test_env_owner_rejects_non_env_config_class() -> None:
    with pytest.raises(TypeError, match="must inherit EnvConfig"):

        @env_owner(
            key="bad",
            title="Bad",
            env_prefix="BAD_",
            rc_path=("bad",),
        )
        class _BadOwner:
            value: str = env_field("VALUE", default="bad")


def test_env_field_rejects_default_and_default_factory() -> None:
    with pytest.raises(ValueError, match="default and default_factory"):
        env_field("VALUE", default="x", default_factory=lambda: "y")


def test_env_field_default_factory_resolves_fresh_owner_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FACTORY_CACHE_DIR", raising=False)

    first = _FactoryEnv()
    second = _FactoryEnv()

    assert first.cache_dir != second.cache_dir
    assert first.source_of("cache_dir").source == "owner_default"


def test_env_config_is_the_only_public_env_runtime_base() -> None:
    assert apprc.EnvConfig is EnvConfig
    assert config_api.EnvConfig is EnvConfig
    assert not hasattr(apprc, "BaseEnv")
    assert not hasattr(config_api, "BaseEnv")


def test_owner_default_is_not_public_api() -> None:
    assert not hasattr(apprc, "owner_default")
    assert not hasattr(config_api, "owner_default")


def test_schema_types_are_not_public_facade_exports() -> None:
    assert not hasattr(apprc, "ConfigOwner")
    assert not hasattr(apprc, "ConfigField")
    assert not hasattr(config_api, "ConfigOwner")
    assert not hasattr(config_api, "ConfigField")


def test_env_owner_wraps_lifecycle_by_default() -> None:
    assert getattr(_LoggedEnv.__init__, "__init_lifecycle_wrapped__", False)
    assert not getattr(_QuietEnv.__init__, "__init_lifecycle_wrapped__", False)


def test_env_owner_lifecycle_wrapping_is_idempotent() -> None:
    wrapped_init = _LoggedEnv.__init__

    decorated = env_owner(
        key="demo.logged",
        title="Logged Demo",
        env_prefix="LOGGED_",
        rc_path=("demo", "logged"),
    )(_LoggedEnv)

    assert decorated is _LoggedEnv
    assert _LoggedEnv.__init__ is wrapped_init


def test_env_field_derives_env_var_from_python_field_name() -> None:
    owner = config_owner_for(_ImplicitEnv)

    assert owner.env_key("auto_named_value") == "IMPLICIT_AUTO_NAMED_VALUE"


def test_env_config_rejects_invalid_runtime_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "BOGUS")

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _ChoiceEnv()


def test_env_config_ownerless_config_requires_owner() -> None:
    with pytest.raises(RuntimeError, match="decorated with @env_owner"):
        _OwnerlessEnv(bind_from_env_on_init=False)


def test_env_config_python_keyword_arg_overrides_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoEnv(mode="MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.retries == 9
    mode_source = cfg.source_of("mode")
    retries_source = cfg.source_of("retries")
    assert isinstance(mode_source, ConfigFieldSource)
    assert mode_source.source == "python_arg"
    assert mode_source.label == "Python argument"
    assert mode_source.env_key == "DEMO_MODE"
    assert mode_source.value == "MANUAL"
    assert retries_source.source == "process_env"
    assert retries_source.value == 9


def test_env_config_python_arg_ignores_invalid_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    cfg = _DemoEnv(retries=4)

    assert cfg.retries == 4
    assert cfg.source_of("retries").source == "python_arg"


def test_env_config_override_python_values_reads_invalid_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(retries=4)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    with pytest.raises(InvalidSettingsError, match="converting"):
        cfg.reload(override_python_values=True)


def test_env_config_python_arg_override_stays_quiet_during_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoEnv(mode="MANUAL")

    assert cfg.mode == "MANUAL"
    assert sink.warnings == []


def test_env_config_rejects_invalid_python_choice_arg() -> None:
    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _ChoiceEnv(mode="BOGUS")


def test_env_config_rejects_wrong_python_arg_type() -> None:
    with pytest.raises(TypeError, match="DEMO_RETRIES must be int; got str"):
        _DemoEnv(retries="4")  # pyright: ignore[reportArgumentType]


def test_env_config_rejects_invalid_python_choice_assignment() -> None:
    cfg = _ChoiceEnv()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.mode = "BOGUS"

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "owner_default"


def test_env_config_rejects_wrong_python_assignment_type() -> None:
    cfg = _DemoEnv()

    with pytest.raises(TypeError, match="DEMO_ENABLED must be bool; got str"):
        cfg.enabled = "true"  # pyright: ignore[reportAttributeAccessIssue]

    assert cfg.enabled is False
    assert cfg.source_of("enabled").source == "owner_default"


def test_env_owner_rejects_wrong_python_default_type() -> None:
    with pytest.raises(TypeError, match="retries must be int; got str"):

        @env_owner(
            key="demo.bad_default",
            title="Bad Default",
            env_prefix="BAD_DEFAULT_",
            rc_path=("demo", "bad_default"),
        )
        class _BadDefaultEnv(EnvConfig):
            retries: int = env_field("RETRIES", default="3")


def test_env_config_python_positional_arg_overrides_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoEnv("MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.source_of("mode").source == "python_arg"


def test_env_config_absent_env_fields_report_owner_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    cfg = _DemoEnv()

    assert cfg.mode == "AUTO"
    assert cfg.retries == 3
    assert cfg.source_of("mode").source == "owner_default"
    assert cfg.source_of("mode").label == "Owner default"
    assert cfg.source_of("retries").source == "owner_default"


def test_env_config_owner_defaults_resolve_when_env_binding_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoEnv(bind_from_env_on_init=False)

    assert cfg.retries == 3
    assert cfg.source_of("retries").source == "owner_default"


def test_env_config_sources_returns_all_owner_field_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "6")

    cfg = _DemoEnv(mode="MANUAL")

    sources = cfg.sources()
    assert set(sources) == {"mode", "retries", "enabled", "token"}
    assert sources["mode"].source == "python_arg"
    assert sources["retries"].source == "process_env"
    assert sources["enabled"].source == "owner_default"


def test_env_config_secret_source_redacts_repr_and_keeps_raw_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    source = _DemoEnv().source_of("token")

    assert source.secret is True
    assert source.value == "demo-token"
    assert source.display_value == "<redacted>"
    assert "demo-token" not in repr(source)
    assert "<redacted>" in repr(source)


def test_env_config_required_field_can_be_supplied_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRED_VALUE", "from-env")

    cfg = _RequiredEnv()

    assert cfg.value == "from-env"
    assert cfg.source_of("value").source == "process_env"


def test_env_config_required_field_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUIRED_VALUE", raising=False)

    with pytest.raises(RuntimeError, match="REQUIRED_VALUE"):
        _RequiredEnv()


def test_env_config_python_assignment_survives_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(env_config_module, "LOG", sink)
    cfg = _DemoEnv()
    cfg.mode = "MANUAL"
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload()

    assert cfg.mode == "MANUAL"
    assert cfg.source_of("mode").source == "python_assignment"
    assert any("mode" in warning for warning in sink.warnings)
    assert any(
        "override_python_values=True" in warning for warning in sink.warnings
    )


def test_env_config_reload_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "process_env"


def test_env_config_bind_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.bind_from_env(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "process_env"


def test_env_config_copy_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")

    shallow = copy(cfg)
    deep = deepcopy(cfg)

    assert shallow.source_of("mode").source == "python_arg"
    assert deep.source_of("mode").source == "python_arg"
