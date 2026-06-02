from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from apprc.config import BaseConfig


@dataclass(slots=True)
class _NestedConfig:
    visible: str
    secret: str = field(repr=False)


@dataclass(slots=True)
class _RuntimeConfig(BaseConfig):
    name: str
    path: Path
    nested: _NestedConfig


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
