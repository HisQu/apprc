"""Public provenance records and literal vocabulary."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

type ConfigProvenanceSource = Literal["python", "shell"]
type PythonProvenanceOrigin = Literal[
    "python_constructor_argument",
    "python_runtime_assignment",
    "python_scoped_override",
    "python_baseconfig_default",
    "python_envconfig_default",
    "python_process_environment_mutation",
]
type ShellProvenanceOrigin = Literal[
    "shell_export_variable",
    "shell_dotenv_shared",
    "shell_dotenv_local",
    "shell_dotenv_explicit",
    "shell_bootstrap_selector",
]
type ConfigProvenanceOrigin = PythonProvenanceOrigin | ShellProvenanceOrigin

_PYTHON_ORIGINS: frozenset[PythonProvenanceOrigin] = frozenset(
    (
        "python_constructor_argument",
        "python_runtime_assignment",
        "python_scoped_override",
        "python_baseconfig_default",
        "python_envconfig_default",
        "python_process_environment_mutation",
    )
)


@dataclass(frozen=True, slots=True)
class ConfigOriginState:
    """Internal winning-origin metadata for one config field.

    :param origin: Exact lifecycle event that owns the effective value.
    :param env_key: Full env key when the value is env-backed.
    :param path: Dotenv file path when a file-backed env value won.
    """

    origin: ConfigProvenanceOrigin
    env_key: str | None = None
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class EnvValueOrigin:
    """Bootstrap-time origin metadata for one environment value.

    :param env_key: Full env key populated or observed by AppRC.
    :param origin: Shell-side lifecycle event that produced the env value.
    :param value: Raw string value stored in ``os.environ`` after bootstrap.
    :param path: Dotenv file path when the origin came from a file.
    """

    env_key: str
    origin: ShellProvenanceOrigin
    value: str
    path: Path | None = None


@dataclass(frozen=True, slots=True, repr=False)
class ConfigProvenance:
    """Resolved provenance metadata for one config field.

    :param field_name: Runtime dataclass field name.
    :param source: Broad provenance boundary: Python code or shell/env state.
    :param origin: Exact lifecycle event that explains why this value won.
    :param value: Current runtime value stored on the config object.
    :param secret: Whether display surfaces should redact this value.
    :param env_key: Full OS environment variable key for env-backed fields.
    :param path: Dotenv file path when a file-backed env value won.
    :param display_value: Redacted value for UIs, logs, and repr output.
    """

    field_name: str
    source: ConfigProvenanceSource
    origin: ConfigProvenanceOrigin
    value: Any
    secret: bool = False
    env_key: str | None = None
    path: Path | None = None
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
            f"origin={self.origin!r}, "
            f"value={self.display_value!r}, "
            f"secret={self.secret!r}, "
            f"display_value={self.display_value!r}, "
            f"env_key={self.env_key!r}, "
            f"path={self.path!r})"
        )


def source_for_origin(origin: ConfigProvenanceOrigin) -> ConfigProvenanceSource:
    """Return the broad boundary for one exact provenance origin.

    :param origin: Exact provenance origin literal.
    :return: ``"python"`` for Python-owned origins, otherwise ``"shell"``.
    """
    return "python" if origin in _PYTHON_ORIGINS else "shell"
