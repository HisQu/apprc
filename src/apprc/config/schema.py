"""Declare env-backed runtime config fields and normalize their schema.

Applications normally author configuration once as a
:class:`apprc.config.base_config.BaseEnv` subclass decorated with
:func:`env_owner`. Individual attributes use :func:`env_field` to declare env
keys, defaults, docs metadata, and editor metadata. AppRC derives
``ConfigOwner`` and ``ConfigField`` objects from those typed classes so docs,
dotenv editors, terminal UIs, and typed loading share one normalized schema.

The module deliberately does not know where dotenv files live. File selection
belongs to :mod:`apprc.config.environment` and
:mod:`apprc.config.local_env`; this module only maps declared keys to typed
runtime values.
"""

from __future__ import annotations

# == Standard Library ========================
import os
import re
from dataclasses import dataclass, field, fields, make_dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, TypeVar, get_type_hints

# == 3rd Party ===============================
import typed_settings as ts
from typed_settings.dict_utils import set_path
from typed_settings.types import LoadedSettings, LoaderMeta

CONFIG_MISSING: Final = object()
OWNER_DEFAULT_METADATA_KEY: Final = "apprc.owner_default"
ENV_FIELD_METADATA_KEY: Final = "apprc.env_field"

EnvClsT = TypeVar("EnvClsT", bound=type[Any])


class _EnvFieldMissingSentinel:
    """Placeholder used until Python args, env, or owner defaults resolve."""

    def __repr__(self) -> str:
        return "env_field()"


ENV_FIELD_MISSING: Final = _EnvFieldMissingSentinel()


class _OwnerDefaultSentinel:
    """Placeholder assigned before ``BaseEnv`` resolves owner defaults."""

    def __repr__(self) -> str:
        return "owner_default()"


OWNER_DEFAULT: Final = _OwnerDefaultSentinel()


def owner_default(*, repr: bool = True) -> Any:
    """Declare that an owner-backed dataclass field uses ``ConfigField.default``.

    ``BaseEnv`` resolves this placeholder during ``__post_init__``. It keeps
    runtime defaults in the ``ConfigOwner`` inventory while still giving
    dataclasses an optional constructor argument.

    :param repr: Whether dataclass ``repr`` should include this field.
    :return: Dataclass field placeholder resolved by ``BaseEnv``.
    """
    return field(
        default=OWNER_DEFAULT,
        repr=repr,
        metadata={OWNER_DEFAULT_METADATA_KEY: True},
    )


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    """Author-facing metadata attached to one ``BaseEnv`` dataclass field.

    :param env_var: Env variable name without the owner prefix. When omitted,
        AppRC derives the key from the Python attribute name.
    :param default: Runtime fallback when no Python value or env value wins.
    :param shared_default: Packaged shared dotenv value when intentionally
        different from the runtime fallback.
    :param title: Short display label for docs and terminal UIs.
    :param explanation_short: Compact table-facing description.
    :param explanation_long: Full editor-facing description.
    :param secret: Whether UIs and provenance reprs should redact the value.
    :param editable: Whether config editors should allow direct editing.
    :param required: Whether a value must come from Python or env.
    :param choices: Optional string choices.
    :param python_type: Optional override for the annotation-derived type.
    """

    env_var: str | None = None
    default: Any = CONFIG_MISSING
    shared_default: Any = CONFIG_MISSING
    title: str = ""
    explanation_short: str = ""
    explanation_long: str = ""
    secret: bool = False
    editable: bool = True
    required: bool = False
    choices: tuple[str, ...] = ()
    python_type: type[Any] | None = None


def env_field(
    env_var: str | None = None,
    *,
    default: Any = CONFIG_MISSING,
    shared_default: Any = CONFIG_MISSING,
    title: str = "",
    explanation_short: str = "",
    explanation_long: str = "",
    secret: bool = False,
    editable: bool = True,
    required: bool = False,
    choices: Iterable[str] = (),
    repr: bool | None = None,
    python_type: type[Any] | None = None,
) -> Any:
    """Declare one env-backed ``BaseEnv`` attribute.

    ``env_field`` stores AppRC metadata in a normal dataclass field. The
    surrounding :func:`env_owner` decorator derives the normalized
    :class:`ConfigField` inventory from that metadata and the attribute type
    annotation.

    :param env_var: Env variable name without the owner prefix. When omitted,
        the Python field name is converted to upper snake case.
    :param default: Runtime fallback when Python and env do not provide a
        value. Omit this for required env-backed settings.
    :param shared_default: Packaged shared dotenv value when intentionally
        different from ``default``.
    :param title: Short display label for docs and terminal UIs.
    :param explanation_short: Compact table-facing description.
    :param explanation_long: Full editor-facing description.
    :param secret: Whether display surfaces should redact the value.
    :param editable: Whether config editors should allow direct editing.
    :param required: Whether Python or env must provide a value.
    :param choices: Optional accepted string values.
    :param repr: Whether dataclass ``repr`` should include this value. Defaults
        to hiding secret fields and showing non-secret fields.
    :param python_type: Optional override for the annotation-derived type.
    :return: Dataclass field consumed by ``BaseEnv`` and AppRC tooling.
    """
    spec = EnvFieldSpec(
        env_var=env_var,
        default=default,
        shared_default=shared_default,
        title=title,
        explanation_short=explanation_short,
        explanation_long=explanation_long,
        secret=secret,
        editable=editable,
        required=required,
        choices=tuple(choices),
        python_type=python_type,
    )
    dataclass_default = (
        ENV_FIELD_MISSING if default is CONFIG_MISSING else default
    )
    return field(
        default=dataclass_default,
        repr=(not secret if repr is None else repr),
        metadata={ENV_FIELD_METADATA_KEY: spec},
    )


@dataclass(frozen=True, slots=True)
class ConfigField:
    """Metadata for one env-backed runtime setting.

    :param name: Runtime dataclass attribute name.
    :param env_var: Env variable name without the owner prefix.
    :param python_type: Python type used for typed-settings conversion.
    :param default: Runtime fallback value when no source provides a value.
    :param shared_default: Packaged ``.env.shared`` value when intentionally
        different from ``default``.
    :param title: Short display label for docs and terminal UIs.
    :param explanation_short: Compact table-facing description.
    :param explanation_long: Full editor-facing description.
    :param secret: Whether UIs and serializers should redact the value.
    :param editable: Whether config editors should allow direct editing.
    :param required: Whether the field has no fallback.
    :param choices: Optional string choices.
    """

    name: str
    env_var: str
    python_type: type[Any]
    default: Any = CONFIG_MISSING
    shared_default: Any = CONFIG_MISSING
    title: str = ""
    explanation_short: str = ""
    explanation_long: str = ""
    secret: bool = False
    editable: bool = True
    required: bool = False
    choices: tuple[str, ...] = ()

    def shared_env_value(self) -> Any:
        """Return the expected packaged shared-env value."""
        if self.shared_default is not CONFIG_MISSING:
            return self.shared_default
        return self.default


@dataclass(frozen=True, slots=True)
class ConfigOwner:
    """Architecture-aware group of related settings.

    :param key: Stable owner key such as ``"app.runtime_settings"``.
    :param title: Short display label for docs and terminal UIs.
    :param env_prefix: Env key prefix for all owned fields.
    :param rc_path: Runtime config path components from the application root
        config object.
    :param fields: Owner-local field specs.
    """

    key: str
    title: str
    env_prefix: str
    rc_path: tuple[str, ...]
    fields: tuple[ConfigField, ...] = ()

    def field(self, name: str) -> ConfigField:
        """Return one owner-local field spec."""
        for spec in self.fields:
            if spec.name == name:
                return spec
        raise KeyError(name)

    def env_key(self, field_name: str) -> str:
        """Return the full env key for ``field_name``."""
        return f"{self.env_prefix}{self.field(field_name).env_var}"

    def config_path(self, field_name: str) -> tuple[str, ...]:
        """Return the structured runtime config path for ``field_name``."""
        return (*self.rc_path, field_name)

    def config_path_text(self, field_name: str) -> str:
        """Return the dotted runtime config path for ``field_name``."""
        return ".".join(self.config_path(field_name))

    def settings_class(self) -> type[Any]:
        """Build a lightweight dataclass consumed by ``typed-settings``."""
        dataclass_fields: list[
            tuple[str, type[Any]] | tuple[str, type[Any], Any]
        ] = []
        for spec in self.fields:
            if spec.default is CONFIG_MISSING:
                dataclass_fields.append(
                    (
                        spec.name,
                        spec.python_type,
                        field(default=ENV_FIELD_MISSING),
                    )
                )
                continue
            dataclass_fields.append(
                (
                    spec.name,
                    spec.python_type,
                    field(default=spec.default),
                )
            )
        class_name = "".join(part.title() for part in self.key.split("."))
        return make_dataclass(
            f"{class_name}Settings",
            dataclass_fields,
            slots=True,
        )


def _default_env_var(field_name: str) -> str:
    """Return the conventional owner-local env key for ``field_name``."""
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", field_name).replace("-", "_")
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


def _field_spec_from_metadata(
    metadata: Mapping[str, Any],
) -> EnvFieldSpec | None:
    """Return the AppRC field spec stored in dataclass metadata."""
    spec = metadata.get(ENV_FIELD_METADATA_KEY)
    if spec is None:
        return None
    if not isinstance(spec, EnvFieldSpec):
        raise TypeError(
            f"{ENV_FIELD_METADATA_KEY!r} metadata must contain EnvFieldSpec, "
            f"got {type(spec).__name__}."
        )
    return spec


def _derive_owner_fields(env_cls: type[Any]) -> tuple[ConfigField, ...]:
    """Derive normalized fields from one decorated ``BaseEnv`` class."""
    type_hints = get_type_hints(env_cls, include_extras=True)
    owner_fields: list[ConfigField] = []
    seen_env_vars: set[str] = set()
    for item in fields(env_cls):
        spec = _field_spec_from_metadata(item.metadata)
        if spec is None:
            continue
        env_var = spec.env_var or _default_env_var(item.name)
        if env_var in seen_env_vars:
            raise ValueError(
                f"{env_cls.__name__} declares duplicate env var {env_var!r}."
            )
        seen_env_vars.add(env_var)
        python_type = spec.python_type or type_hints.get(item.name, Any)
        if python_type is Any:
            raise TypeError(
                f"{env_cls.__name__}.{item.name} must have a type annotation "
                "or env_field(python_type=...)."
            )
        owner_fields.append(
            ConfigField(
                name=item.name,
                env_var=env_var,
                python_type=python_type,
                default=spec.default,
                shared_default=spec.shared_default,
                title=spec.title,
                explanation_short=spec.explanation_short,
                explanation_long=spec.explanation_long,
                secret=spec.secret,
                editable=spec.editable,
                required=spec.required or spec.default is CONFIG_MISSING,
                choices=spec.choices,
            )
        )
    return tuple(owner_fields)


def env_owner(
    *,
    key: str,
    title: str,
    env_prefix: str,
    rc_path: tuple[str, ...],
    slots: bool = True,
    kw_only: bool = False,
) -> Any:
    """Decorate a ``BaseEnv`` class and derive its normalized owner schema.

    The decorated class becomes a dataclass by default. ``ConfigOwner`` remains
    AppRC's internal normalized inventory, but application authors define the
    fields only once on the typed runtime config class.

    :param key: Stable owner key such as ``"app.runtime_settings"``.
    :param title: Short display label for docs and terminal UIs.
    :param env_prefix: Env key prefix for all owned fields.
    :param rc_path: Runtime config path components from the application root.
    :param slots: Whether to apply slotted dataclass generation.
    :param kw_only: Whether generated dataclass fields are keyword-only.
    :return: Class decorator for a ``BaseEnv`` subclass.
    """

    def _decorate(cls: EnvClsT) -> EnvClsT:
        # > Dataclass subclasses inherit is_dataclass(cls)=True before their
        # > own annotations are processed, so inspect the class dictionary.
        env_cls = (
            cls
            if "__dataclass_fields__" in cls.__dict__
            else dataclass(
                slots=slots,
                kw_only=kw_only,
            )(cls)
        )
        owner = ConfigOwner(
            key=key,
            title=title,
            env_prefix=env_prefix,
            rc_path=rc_path,
            fields=_derive_owner_fields(env_cls),
        )
        setattr(env_cls, "config_owner", owner)
        return env_cls

    return _decorate


def config_owner_for(env_cls: type[Any]) -> ConfigOwner:
    """Return the owner schema derived for one ``BaseEnv`` class.

    :param env_cls: Class decorated with :func:`env_owner`.
    :return: Normalized owner inventory used by AppRC internals.
    :raises TypeError: If the class has not been decorated.
    """
    owner = getattr(env_cls, "config_owner", None)
    if isinstance(owner, ConfigOwner):
        return owner
    raise TypeError(f"{env_cls.__name__} is not decorated with @env_owner.")


class OwnerMappingLoader:
    """Load one owner from an env-like mapping using explicit field env names."""

    def __init__(
        self,
        owner: ConfigOwner,
        values: Mapping[str, str],
        *,
        source_name: str,
        base_dir: Path | None = None,
    ) -> None:
        """Store one low-level source.

        :param owner: Owner whose field names should be mapped.
        :param values: Full env-key to string value mapping.
        :param source_name: Human-readable source name for diagnostics.
        :param base_dir: Base directory passed to typed-settings metadata.
        """
        self.owner = owner
        self.values = values
        self.source_name = source_name
        self.base_dir = base_dir

    def __call__(self, settings_cls: type[Any], options: Any) -> LoadedSettings:
        """Return values for options known to this owner."""
        loaded: dict[str, Any] = {}
        for option in options:
            env_key = self.owner.env_key(option.name)
            if env_key in self.values:
                set_path(loaded, option.path, self.values[env_key])
        return LoadedSettings(
            loaded,
            LoaderMeta(self.source_name, base_dir=self.base_dir),
        )


def load_owner_from_sources(
    owner: ConfigOwner,
    sources: tuple[OwnerMappingLoader, ...],
) -> Any:
    """Load one owner with ``typed-settings``.

    :param owner: Owner spec to load.
    :param sources: Ordered sources from low to high precedence.
    :return: A generated settings dataclass instance.
    """
    return ts.load_settings(
        owner.settings_class(),
        sources,
        converter=ts.default_converter(resolve_paths=False),
    )


def load_owner_from_env(
    owner: ConfigOwner,
    values: Mapping[str, str] | None = None,
) -> Any:
    """Load one owner from current process OS env variables only.

    Reads values from ``os.environ`` by default. Passing ``values`` is for
    internals that need an env-like current-process snapshot with some keys
    deliberately filtered. This does not load dotenv files or application
    config layers; call the application bootstrap helper at the entrypoint when
    those layers should populate the current process environment.

    :param owner: Owner spec to load.
    :param values: Optional env-like mapping. Defaults to ``os.environ``.
    :return: A generated settings dataclass instance.
    """
    env_values = os.environ if values is None else values
    return load_owner_from_sources(
        owner,
        (
            OwnerMappingLoader(
                owner,
                env_values,
                source_name="process-env",
                base_dir=Path.cwd(),
            ),
        ),
    )


def provided_owner_field_names(
    owner: ConfigOwner,
    values: Mapping[str, str],
) -> set[str]:
    """Return owner-local field names present in an env-like mapping."""
    return {
        spec.name for spec in owner.fields if owner.env_key(spec.name) in values
    }


def owner_env_mapping(
    owner: ConfigOwner,
    values: object,
    *,
    prefixed: bool = True,
    include_empty: bool = False,
) -> dict[str, str]:
    """Serialize owner-backed values as env key/value strings."""

    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    env: dict[str, str] = {}
    for spec in owner.fields:
        value = getattr(values, spec.name)
        if value is None and not include_empty:
            continue
        key = owner.env_key(spec.name) if prefixed else spec.env_var
        env[key] = _stringify(value)
    return env


def iter_config_fields(
    owners: Iterable[ConfigOwner],
) -> Iterable[tuple[ConfigOwner, ConfigField]]:
    """Yield every ``(owner, field)`` pair in declaration order."""
    for owner in owners:
        for spec in owner.fields:
            yield owner, spec


def find_field_by_env_key(
    owners: Iterable[ConfigOwner],
    env_key: str,
) -> tuple[ConfigOwner, ConfigField] | None:
    """Return the owner field addressed by a full env key."""
    normalized = env_key.strip()
    for owner, spec in iter_config_fields(owners):
        if owner.env_key(spec.name) == normalized:
            return owner, spec
    return None


def find_field_by_config_path(
    owners: Iterable[ConfigOwner],
    config_path: str,
) -> tuple[ConfigOwner, ConfigField] | None:
    """Return the owner field addressed by a dotted config path."""
    normalized = config_path.strip()
    for owner, spec in iter_config_fields(owners):
        if owner.config_path_text(spec.name) == normalized:
            return owner, spec
    return None


def resolve_config_field_reference(
    owners: Iterable[ConfigOwner],
    reference: str,
) -> tuple[ConfigOwner, ConfigField]:
    """Resolve an env key, dotted config path, or unique field name.

    :param owners: Owner specs to search.
    :param reference: User input such as ``APP_MODEL_LLM`` or
        ``app.runtime_settings.model``.
    :return: Matching owner and field spec.
    :raises ValueError: If the reference is unknown or ambiguous.
    """
    ref = reference.strip()
    by_env = find_field_by_env_key(owners, ref)
    if by_env is not None:
        return by_env
    by_path = find_field_by_config_path(owners, ref)
    if by_path is not None:
        return by_path

    matches = [
        (owner, spec)
        for owner, spec in iter_config_fields(owners)
        if spec.name == ref
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(
            owner.config_path_text(spec.name) for owner, spec in matches
        )
        raise ValueError(
            f"Config field name {ref!r} is ambiguous. Use one of: {choices}."
        )
    raise ValueError(f"Unknown config key or path: {ref!r}.")
