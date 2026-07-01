"""Value normalization for AppRC dotenv edit surfaces."""

from __future__ import annotations

# == 3rd Party ===============================
from typed_settings.exceptions import InvalidSettingsError

# == Internal ================================
from apprc.definition.env_config._loading import parse_env_field_value
from apprc.definition.env_config._validation import validate_python_field_value
from apprc.definition.env_config.schema import ConfigField


def normalize_env_value(spec: ConfigField, raw_value: str) -> str:
    """Validate and normalize one user-entered dotenv value.

    :param spec: Field declaration that owns type and choice validation.
    :param raw_value: Raw text entered through CLI, TUI, or another edit path.
    :return: Deterministic dotenv text for the parsed Python value.
    :raises ValueError: If the value is empty for a required field or cannot
        be parsed as the declared type.
    """
    value = raw_value.strip()
    if value == "" and (spec.required or not spec.has_default()):
        raise ValueError(f"{spec.name} is required and cannot be empty.")
    try:
        parsed = parse_env_field_value(spec, value)
    except InvalidSettingsError as exc:
        raise ValueError(str(exc)) from exc
    validate_python_field_value(spec, parsed)
    return stringify_env_value(parsed)


def stringify_env_value(value: object) -> str:
    """Return a deterministic dotenv string for a parsed runtime value.

    :param value: Parsed Python value.
    :return: Text representation AppRC writes to dotenv files.
    """
    if isinstance(value, bool):
        if value:
            return "true"
        return "false"
    return str(value)
