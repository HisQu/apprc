"""Field inspection using the same resolved inputs as runtime construction."""

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from typed_settings.exceptions import InvalidSettingsError

from apprc.definition.env_config._validation import validate_python_field_value
from apprc.definition.env_config.schema import ConfigField, ConfigOwner
from apprc.definition.provenance import ConfigOriginState
from apprc.definition.env_config.conversion import parse_env_field_value
from apprc.runtime.resolution import ResolvedConfig


@dataclass(frozen=True, slots=True)
class FieldInspection:
    """Effective field state, including incomplete or invalid configuration.

    :param owner: Owning section metadata.
    :param field: Field metadata used for validation and editing.
    :param value: Parsed effective value, excluded from debug output.
    :param origin: Winning source, or the Python fallback.
    :param issue: Validation failure without raw input values.
    :param active: Whether this field belongs to the selected runtime.
    """

    owner: ConfigOwner = dataclass_field(repr=False)
    field: ConfigField = dataclass_field(repr=False)
    value: Any = dataclass_field(repr=False)
    origin: ConfigOriginState
    issue: str | None = None
    active: bool = True

    @property
    def display_value(self) -> Any:
        """Return the effective value with declared secrets redacted."""
        if not self.active:
            return None
        return "<redacted>" if self.field.secret else self.value


@dataclass(frozen=True, slots=True)
class ConfigInspection:
    """Read-only readiness and per-field state for an application.

    :param resolved: Captured layers and storage selection.
    :param fields: Effective values and validation findings.
    :param issues: Failures that prevent the inspected runtime from starting.
    """

    resolved: ResolvedConfig
    fields: tuple[FieldInspection, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Return whether storage and declared field requirements are met."""
        return not self.issues


def inspect_resolved(resolved: ResolvedConfig) -> ConfigInspection:
    """Validate fields individually so one missing value cannot hide others.

    :param resolved: Runtime resolution, optionally retaining readiness errors.
    :return: Values and domain findings without prompts or writes.
    """
    fields: list[FieldInspection] = []
    issues = list(resolved.issues)
    for owner in resolved.schema.owners:
        for spec in owner.fields:
            key = owner.env_key(spec.name)
            origin = resolved.source.origins.get(
                key, ConfigOriginState("python_config_default", env_key=key)
            )
            if owner.requires_storage and resolved.selection is None:
                fields.append(
                    FieldInspection(owner, spec, None, origin, active=False)
                )
                continue
            issue = None
            value = None
            try:
                if key in resolved.values:
                    value = parse_env_field_value(spec, resolved.values[key])
                elif spec.has_default():
                    value = spec.resolve_default()
                else:
                    issue = f"Missing required setting: {key}."
                if issue is None:
                    validate_python_field_value(spec, value)
            except (ValueError, TypeError, InvalidSettingsError):
                issue = (
                    f"Invalid value for {key}; expected {spec.python_type!s}."
                )
            fields.append(FieldInspection(owner, spec, value, origin, issue))
            if issue is not None:
                issues.append(issue)
    return ConfigInspection(resolved, tuple(fields), tuple(issues))
