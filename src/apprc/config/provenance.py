"""Runtime provenance records for AppRC config values."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import Field, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

type ConfigProvenanceSource = Literal["python", "shell"]
type PythonProvenanceOrigin = Literal[
    "python_constructor_argument",
    "python_runtime_assignment",
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


_ENV_VALUE_ORIGINS: dict[str, EnvValueOrigin] = {}


def provenance_origin_label(origin: ConfigProvenanceOrigin) -> str:
    """Return a display label derived from a provenance origin literal.

    :param origin: Exact provenance origin literal.
    :return: Human-readable label derived without storing duplicate state.
    """
    return origin.replace("_", " ").capitalize()


def source_for_origin(origin: ConfigProvenanceOrigin) -> ConfigProvenanceSource:
    """Return the broad boundary for one exact provenance origin.

    :param origin: Exact provenance origin literal.
    :return: ``"python"`` for Python-owned origins, otherwise ``"shell"``.
    """
    return "python" if origin in _PYTHON_ORIGINS else "shell"


def public_config_fields(instance: Any) -> tuple[Field[Any], ...]:
    """Return public dataclass fields included in config provenance.

    :param instance: Runtime config object to inspect.
    :return: Public fields, excluding private and AppRC-internal fields.
    """
    if not is_dataclass(instance):
        return ()
    return tuple(
        item
        for item in fields(instance)
        if not item.name.startswith("_") and not item.metadata.get("internal")
    )


def constructor_field_origins(
    config_cls: type[Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> dict[str, ConfigOriginState]:
    """Return provenance origins for public constructor-provided fields.

    :param config_cls: Config class being constructed.
    :param args: Positional constructor arguments passed to ``__new__``.
    :param kwargs: Keyword constructor arguments passed to ``__new__``.
    :return: Field-origin mapping for values supplied by Python callers.
    """
    if not is_dataclass(config_cls):
        return {}
    public_fields = {
        item.name: item
        for item in fields(config_cls)
        if not item.name.startswith("_") and not item.metadata.get("internal")
    }
    positional_init_fields = [
        item.name
        for item in public_fields.values()
        if item.init and not item.kw_only
    ]
    provided_names = set(positional_init_fields[: len(args)]) | set(kwargs)
    return {
        field_name: ConfigOriginState("python_constructor_argument")
        for field_name in provided_names & set(public_fields)
    }


def with_field_origin(
    origins: Mapping[str, ConfigOriginState],
    field_name: str,
    origin: ConfigOriginState,
) -> dict[str, ConfigOriginState]:
    """Return a copied origin map with one updated field.

    :param origins: Existing immutable-by-convention origin map.
    :param field_name: Runtime dataclass field name.
    :param origin: Replacement origin state.
    :return: Copied field-origin mapping.
    """
    next_origins = dict(origins)
    next_origins[field_name] = origin
    return next_origins


def set_field_origin(
    instance: Any,
    field_name: str,
    origin: ConfigOriginState,
) -> None:
    """Record BaseConfig-level provenance for one field.

    :param instance: Config object whose internal origin map should be updated.
    :param field_name: Runtime dataclass field name.
    :param origin: Replacement origin state.
    """
    origins = getattr(instance, "_apprc_provenance_origins", {})
    object.__setattr__(
        instance,
        "_apprc_provenance_origins",
        with_field_origin(origins, field_name, origin),
    )


def base_config_provenance_of(
    instance: Any, field_name: str
) -> ConfigProvenance:
    """Build provenance for one public BaseConfig dataclass field.

    :param instance: Runtime config object.
    :param field_name: Public dataclass field name.
    :return: Resolved provenance metadata.
    :raises KeyError: If ``field_name`` is not public config state.
    """
    field_by_name = {item.name: item for item in public_config_fields(instance)}
    if field_name not in field_by_name:
        raise KeyError(field_name)
    field_def = field_by_name[field_name]
    origins = getattr(instance, "_apprc_provenance_origins", {})
    state = origins.get(
        field_name,
        ConfigOriginState("python_baseconfig_default"),
    )
    return ConfigProvenance(
        field_name=field_name,
        source=source_for_origin(state.origin),
        origin=state.origin,
        value=getattr(instance, field_name),
        secret=not field_def.repr,
        env_key=state.env_key,
        path=state.path,
    )


def provenance_of(instance: Any, field_name: str) -> ConfigProvenance:
    """Return provenance for one config field via the instance resolver hook.

    :param instance: Runtime config object.
    :param field_name: Public dataclass field name.
    :return: Resolved provenance metadata.
    """
    return instance._build_config_provenance(field_name)


def provenance(instance: Any) -> dict[str, ConfigProvenance]:
    """Return provenance for every public config field.

    :param instance: Runtime config object.
    :return: Field-name keyed provenance records.
    """
    return {
        item.name: provenance_of(instance, item.name)
        for item in public_config_fields(instance)
    }


def register_env_value_origins(
    origins: Mapping[str, EnvValueOrigin],
    *,
    clear_keys: set[str],
) -> None:
    """Replace bootstrap provenance for one app-owned env-key inventory.

    :param origins: New env-value origin records keyed by env key.
    :param clear_keys: App-owned env keys whose previous records are stale.
    """
    for key in clear_keys:
        _ENV_VALUE_ORIGINS.pop(key, None)
    _ENV_VALUE_ORIGINS.update(origins)


def env_value_origin(env_key: str) -> EnvValueOrigin | None:
    """Return bootstrap provenance for one env key when AppRC knows it.

    :param env_key: Full environment variable name.
    :return: Bootstrap origin metadata, or ``None``.
    """
    return _ENV_VALUE_ORIGINS.get(env_key)


def shell_origin_for_env_value(
    env_key: str,
    value: str,
) -> ConfigOriginState:
    """Return the provenance state for one env value bound by EnvConfig.

    :param env_key: Full environment variable name.
    :param value: Raw string value read by the runtime binder.
    :return: Field origin state with dotenv path when known.
    """
    recorded = env_value_origin(env_key)
    if recorded is None:
        return ConfigOriginState("shell_export_variable", env_key=env_key)
    if recorded.value != value:
        return ConfigOriginState(
            "python_process_environment_mutation",
            env_key=env_key,
        )
    return ConfigOriginState(
        recorded.origin,
        env_key=env_key,
        path=recorded.path,
    )
