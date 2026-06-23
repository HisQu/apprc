from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typed_settings.exceptions import InvalidSettingsError

from apprc.config import (
    BaseConfig,
    BaseEnv,
    ConfigField,
    ConfigFieldSource,
    ConfigOwner,
    owner_default,
)
import apprc.config.base_config as base_config


@dataclass(slots=True)
class _NestedConfig:
    visible: str
    secret: str = field(repr=False)


@dataclass(slots=True)
class _RuntimeConfig(BaseConfig):
    name: str
    path: Path
    nested: _NestedConfig


_CHOICE_OWNER = ConfigOwner(
    key="demo",
    title="Demo",
    env_prefix="DEMO_",
    rc_path=("demo",),
    fields=(
        ConfigField(
            "mode",
            "MODE",
            str,
            default="AUTO",
            choices=("AUTO", "MANUAL"),
        ),
    ),
)


@dataclass(slots=True)
class _ChoiceEnv(BaseEnv):
    config_owner = _CHOICE_OWNER

    mode: str = owner_default()


@dataclass(slots=True)
class _OwnerlessEnv(BaseEnv):
    value: str = "fallback"


_DEMO_OWNER = ConfigOwner(
    key="demo.runtime",
    title="Demo Runtime",
    env_prefix="DEMO_",
    rc_path=("demo",),
    fields=(
        ConfigField(
            "mode",
            "MODE",
            str,
            default="AUTO",
            choices=("AUTO", "MANUAL"),
        ),
        ConfigField("retries", "RETRIES", int, default=3),
        ConfigField("enabled", "ENABLED", bool, default=False),
        ConfigField("token", "TOKEN", str, default="demo-token", secret=True),
    ),
)


@dataclass(slots=True)
class _DemoEnv(BaseEnv):
    config_owner = _DEMO_OWNER

    mode: str = owner_default()
    retries: int = owner_default()
    enabled: bool = owner_default()
    token: str = owner_default(repr=False)


_DRIFT_OWNER = ConfigOwner(
    key="demo.drift",
    title="Demo Drift",
    env_prefix="DRIFT_",
    rc_path=("demo", "drift"),
    fields=(ConfigField("value", "VALUE", str, default="owner-default"),),
)


@dataclass(slots=True)
class _LegacyDefaultEnv(BaseEnv):
    config_owner = _DRIFT_OWNER

    value: str = "dataclass-default"


class _LogSink:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _clear_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for spec in _DEMO_OWNER.fields:
        monkeypatch.delenv(_DEMO_OWNER.env_key(spec.name), raising=False)


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


def test_base_env_rejects_invalid_runtime_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "BOGUS")

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _ChoiceEnv()


def test_base_env_ownerless_config_requires_owner() -> None:
    with pytest.raises(RuntimeError, match="must declare a ConfigOwner"):
        _OwnerlessEnv(bind_from_env_on_init=False)


def test_base_env_python_keyword_arg_overrides_process_env(
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


def test_base_env_python_arg_ignores_invalid_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    cfg = _DemoEnv(retries=4)

    assert cfg.retries == 4
    assert cfg.source_of("retries").source == "python_arg"


def test_base_env_override_python_values_reads_invalid_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(retries=4)
    monkeypatch.setenv("DEMO_RETRIES", "not-an-int")

    with pytest.raises(InvalidSettingsError, match="converting"):
        cfg.reload(override_python_values=True)


def test_base_env_python_arg_override_stays_quiet_during_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoEnv(mode="MANUAL")

    assert cfg.mode == "MANUAL"
    assert sink.warnings == []


def test_base_env_rejects_invalid_python_choice_arg() -> None:
    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        _ChoiceEnv(mode="BOGUS")


def test_base_env_rejects_invalid_python_choice_assignment() -> None:
    cfg = _ChoiceEnv()

    with pytest.raises(ValueError, match="DEMO_MODE='BOGUS' is invalid"):
        cfg.mode = "BOGUS"

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "owner_default"


def test_base_env_python_positional_arg_overrides_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg = _DemoEnv("MANUAL")

    assert cfg.mode == "MANUAL"
    assert cfg.source_of("mode").source == "python_arg"


def test_base_env_absent_env_fields_report_owner_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    cfg = _DemoEnv()

    assert cfg.mode == "AUTO"
    assert cfg.retries == 3
    assert cfg.source_of("mode").source == "owner_default"
    assert cfg.source_of("mode").label == "Owner default"
    assert cfg.source_of("retries").source == "owner_default"


def test_base_env_owner_defaults_resolve_when_env_binding_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    monkeypatch.setenv("DEMO_RETRIES", "9")

    cfg = _DemoEnv(bind_from_env_on_init=False)

    assert cfg.retries == 3
    assert cfg.source_of("retries").source == "owner_default"


def test_base_env_sources_returns_all_owner_field_sources(
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


def test_base_env_secret_source_redacts_repr_and_keeps_raw_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)

    source = _DemoEnv().source_of("token")

    assert source.secret is True
    assert source.value == "demo-token"
    assert source.display_value == "<redacted>"
    assert "demo-token" not in repr(source)
    assert "<redacted>" in repr(source)


def test_base_env_legacy_dataclass_default_warns_and_owner_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)
    monkeypatch.delenv("DRIFT_VALUE", raising=False)

    cfg = _LegacyDefaultEnv()

    assert cfg.value == "owner-default"
    assert cfg.source_of("value").source == "owner_default"
    assert any("dataclass default is obsolete" in msg for msg in sink.warnings)
    assert any("differs from owner default" in msg for msg in sink.warnings)


def test_base_env_python_assignment_survives_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    sink = _LogSink()
    monkeypatch.setattr(base_config, "LOG", sink)
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


def test_base_env_reload_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.reload(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "process_env"


def test_base_env_bind_can_override_python_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")
    monkeypatch.setenv("DEMO_MODE", "AUTO")

    cfg.bind_from_env(override_python_values=True)

    assert cfg.mode == "AUTO"
    assert cfg.source_of("mode").source == "process_env"


def test_base_env_copy_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_demo_env(monkeypatch)
    cfg = _DemoEnv(mode="MANUAL")

    shallow = copy(cfg)
    deep = deepcopy(cfg)

    assert shallow.source_of("mode").source == "python_arg"
    assert deep.source_of("mode").source == "python_arg"
