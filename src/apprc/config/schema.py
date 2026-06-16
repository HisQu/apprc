"""Declare application config fields and load them through typed-settings.

This is the inventory module for AppRC configuration. Application packages
describe every env-backed setting with ``ConfigField`` objects, group related
fields into ``ConfigOwner`` sections, and then reuse those declarations in
three places:

* runtime dataclasses inherit :class:`apprc.config.base_config.BaseEnv`;
* storage-local dotenv editors validate user-entered values;
* docs and CLI commands can resolve env keys, dotted config paths, or unique
  field names back to the same declaration.

The module deliberately does not know where dotenv files live. File selection
belongs to :mod:`apprc.config.environment` and
:mod:`apprc.config.local_env`; this module only maps declared keys to typed
runtime values.
"""

from __future__ import annotations

# == Standard Library ========================
import os
from dataclasses import dataclass, field, make_dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

# == 3rd Party ===============================
import typed_settings as ts
from typed_settings.dict_utils import set_path
from typed_settings.types import LoadedSettings, LoaderMeta

CONFIG_MISSING: Final = object()


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
                dataclass_fields.append((spec.name, spec.python_type))
            else:
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


def config_field(
    name: str,
    env_var: str,
    python_type: type[Any],
    *,
    default: Any = CONFIG_MISSING,
    shared_default: Any = CONFIG_MISSING,
    title: str = "",
    explanation_short: str = "",
    explanation_long: str = "",
    secret: bool = False,
    editable: bool = True,
    required: bool = False,
    choices: tuple[str, ...] = (),
) -> ConfigField:
    """Build one config field with compact call sites."""
    return ConfigField(
        name=name,
        env_var=env_var,
        python_type=python_type,
        default=default,
        shared_default=shared_default,
        title=title,
        explanation_short=explanation_short,
        explanation_long=explanation_long,
        secret=secret,
        editable=editable,
        required=required,
        choices=choices,
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


def load_owner_from_env(owner: ConfigOwner) -> Any:
    """Load one owner from the current process env only."""
    return load_owner_from_sources(
        owner,
        (
            OwnerMappingLoader(
                owner,
                os.environ,
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
