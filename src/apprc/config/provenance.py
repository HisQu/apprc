"""Runtime provenance records for env-backed config values."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass, field
from typing import Any, Literal

type ConfigFieldSourceKey = Literal[
    "python_arg",
    "python_assignment",
    "process_env",
    "owner_default",
]

CONFIG_FIELD_SOURCE_LABELS: dict[ConfigFieldSourceKey, str] = {
    "python_arg": "Python argument",
    "python_assignment": "Python assignment",
    "process_env": "Process environment",
    "owner_default": "Owner default",
}


@dataclass(frozen=True, slots=True, repr=False)
class ConfigFieldSource:
    """Resolved source metadata for one env-backed config field.

    :param field_name: Runtime dataclass field name.
    :param source: Stable source key that explains why the current value won.
    :param label: Human-readable source label.
    :param env_key: Full OS environment variable key owned by the field.
    :param value: Current runtime value stored on the config object.
    :param secret: Whether display surfaces should redact this value.
    :param display_value: Redacted value for UIs, logs, and repr output.
    """

    field_name: str
    source: ConfigFieldSourceKey
    label: str
    env_key: str
    value: Any
    secret: bool = False
    display_value: Any = field(init=False)

    def __post_init__(self) -> None:
        """Store the safe display value for this immutable provenance record."""
        value = "<redacted>" if self.secret else self.value
        object.__setattr__(self, "display_value", value)

    def __repr__(self) -> str:
        """Return a debug representation that never prints secret raw values."""
        return (
            f"{self.__class__.__name__}("
            f"field_name={self.field_name!r}, "
            f"source={self.source!r}, "
            f"label={self.label!r}, "
            f"env_key={self.env_key!r}, "
            f"value={self.display_value!r}, "
            f"secret={self.secret!r}, "
            f"display_value={self.display_value!r})"
        )
