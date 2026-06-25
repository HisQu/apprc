from __future__ import annotations
from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typed_settings.exceptions import InvalidSettingsError

from apprc.runtime_config import (
    BaseConfig,
    ConfigProvenance,
    EnvConfig,
    config_owner_for,
    env_field,
    env_owner,
)
import apprc.runtime_config.fields.base_config as base_config
import apprc.runtime_config.fields.env_config as env_config_module


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


def test_env_field_default_factory_resolves_fresh_envconfig_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FACTORY_CACHE_DIR", raising=False)

    first = _FactoryEnv()
    second = _FactoryEnv()

    assert first.cache_dir != second.cache_dir
    assert first.provenance_of("cache_dir").origin == "python_envconfig_default"


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


def test_env_config_python_keyword_argument_overrides_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoEnv(mode="MANUAL")

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


def test_env_config_python_constructor_argument_ignores_invalid_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    cfg = _DemoEnv(retries=4)

    assert cfg.retries == 4
    assert cfg.provenance_of("retries").origin == "python_constructor_argument"


def test_env_config_override_python_values_reads_invalid_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(retries=4)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    with pytest.raises(InvalidSettingsError, match="converting"):
        cfg.reload(override_python_values=True)


def test_env_config_python_constructor_argument_override_stays_quiet_during_init(
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


def test_env_config_rejects_wrong_python_constructor_argument_type() -> None:
    with pytest.raises(TypeError, match="DEMO_RETRIES must be int; got str"):
        _DemoEnv(retries="4")  # pyright: ignore[reportArgumentType]


def test_env_config_rejects_invalid_python_choice_assignment() -> None:
    cfg = _ChoiceEnv()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.mode = "BOGUS"

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "python_envconfig_default"


def test_env_config_rejects_wrong_python_assignment_type() -> None:
    cfg = _DemoEnv()

    with pytest.raises(TypeError, match="DEMO_ENABLED must be bool; got str"):
        cfg.enabled = "true"  # pyright: ignore[reportAttributeAccessIssue]

    assert cfg.enabled is False
    assert cfg.provenance_of("enabled").origin == "python_envconfig_default"


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


def test_env_config_python_positional_argument_overrides_shell_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoEnv("MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.provenance_of("mode").origin == "python_constructor_argument"


def test_env_config_absent_env_fields_report_envconfig_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    cfg = _DemoEnv()

    assert cfg.mode == "AUTO"
    assert cfg.retries == 3
    assert cfg.provenance_of("mode").source == "python"
    assert cfg.provenance_of("mode").origin == "python_envconfig_default"
    assert cfg.provenance_of("retries").origin == "python_envconfig_default"


def test_env_config_envconfig_defaults_resolve_when_env_binding_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoEnv(bind_from_env_on_init=False)

    assert cfg.retries == 3
    assert cfg.provenance_of("retries").origin == "python_envconfig_default"


def test_env_config_provenance_returns_all_owner_field_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "6")

    cfg = _DemoEnv(mode="MANUAL")

    provenance = cfg.provenance()
    assert set(provenance) == {"mode", "retries", "enabled", "token"}
    assert provenance["mode"].origin == "python_constructor_argument"
    assert provenance["retries"].origin == "shell_export_variable"
    assert provenance["enabled"].origin == "python_envconfig_default"


def test_env_config_secret_source_redacts_repr_and_keeps_raw_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    source = _DemoEnv().provenance_of("token")

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
    assert cfg.provenance_of("value").origin == "shell_export_variable"


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
    assert cfg.provenance_of("mode").origin == "python_runtime_assignment"
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
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_env_config_bind_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.bind_from_env(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_env_config_scoped_owner_field_records_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv()

    scoped = cfg.scoped(mode="MANUAL")
    provenance = scoped.provenance_of("mode")

    assert scoped is not cfg
    assert scoped.mode == "MANUAL"
    assert cfg.mode == "AUTO"
    assert provenance.source == "python"
    assert provenance.origin == "python_scoped_override"
    assert provenance.env_key == "DEMO_MODE"


def test_env_config_scoped_validates_owner_choices_and_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.scoped(mode="BOGUS")
    with pytest.raises(TypeError, match="DEMO_ENABLED must be bool; got str"):
        cfg.scoped(enabled="true")

    assert cfg.mode == "AUTO"
    assert cfg.enabled is False


def test_env_config_reload_preserves_scoped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv().scoped(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload()

    assert cfg.mode == "MANUAL"
    assert cfg.provenance_of("mode").origin == "python_scoped_override"


def test_env_config_reload_can_replace_scoped_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv().scoped(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.provenance_of("mode").origin == "shell_export_variable"


def test_env_config_copy_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")

    shallow = copy(cfg)
    deep = deepcopy(cfg)

    assert shallow.provenance_of("mode").origin == "python_constructor_argument"
    assert deep.provenance_of("mode").origin == "python_constructor_argument"
