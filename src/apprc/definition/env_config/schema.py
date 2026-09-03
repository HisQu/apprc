"""Normalized schema objects for env-backed AppRC config."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Callable
from dataclasses import dataclass, field, make_dataclass
from typing import Any, cast

# == Internal ================================
from apprc.definition.env_config.sentinels import (
    CONFIG_MISSING,
    ENV_FIELD_MISSING,
)


@dataclass(frozen=True, slots=True)
class ConfigField:
    """Metadata for one env-backed runtime setting.

    :param name: Runtime dataclass attribute name.
    :param env_var: Env variable name without the owner prefix.
    :param python_type: Python type used for typed-settings conversion.
    :param default: Runtime fallback value when no source provides a value.
    :param default_factory: Runtime fallback factory when no source provides a
        value. The factory is called for each config instance.
    :param packaged_default: Value documented in ``apprc.defaults.env`` when a
        required field has a shipped value or the shipped value intentionally
        differs from ``default``.
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
    default_factory: Callable[[], Any] | object = CONFIG_MISSING
    packaged_default: Any = CONFIG_MISSING
    title: str = ""
    explanation_short: str = ""
    explanation_long: str = ""
    secret: bool = False
    editable: bool = True
    required: bool = False
    choices: tuple[str, ...] = ()

    def has_default(self) -> bool:
        """Return whether this field has an owner-provided fallback."""
        return (
            self.default is not CONFIG_MISSING
            or self.default_factory is not CONFIG_MISSING
        )

    def resolve_default(self) -> Any:
        """Return a fresh runtime default value or ``CONFIG_MISSING``."""
        if self.default_factory is not CONFIG_MISSING:
            default_factory = cast(Callable[[], Any], self.default_factory)
            return default_factory()
        return self.default

    def packaged_env_value(self) -> Any:
        """Return the expected packaged defaults value."""
        if self.packaged_default is not CONFIG_MISSING:
            return self.packaged_default
        if self.default_factory is not CONFIG_MISSING:
            return CONFIG_MISSING
        return self.default

    @property
    def shared_default(self) -> Any:
        """Return ``packaged_default`` through the deprecated 0.19 name."""
        return self.packaged_default

    def shared_env_value(self) -> Any:
        """Return the packaged value through the deprecated 0.19 name."""
        return self.packaged_env_value()


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
    _settings_class_cache: type[Any] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

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
        if self._settings_class_cache is not None:
            return self._settings_class_cache
        dataclass_fields: list[
            tuple[str, type[Any]] | tuple[str, type[Any], Any]
        ] = []
        for spec in self.fields:
            if not spec.has_default():
                dataclass_fields.append(
                    (
                        spec.name,
                        spec.python_type,
                        field(default=ENV_FIELD_MISSING),
                    )
                )
                continue
            if spec.default_factory is not CONFIG_MISSING:
                default_factory = cast(
                    Callable[[], Any],
                    spec.default_factory,
                )
                dataclass_fields.append(
                    (
                        spec.name,
                        spec.python_type,
                        field(default_factory=default_factory),
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
        settings_cls = make_dataclass(
            f"{class_name}Settings",
            dataclass_fields,
            slots=True,
        )
        object.__setattr__(self, "_settings_class_cache", settings_cls)
        return settings_cls
