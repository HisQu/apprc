"""Render value-editor modal metadata and source rows."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path

# == 3rd Party ===============================
from rich.text import Text

# == Internal ================================
from apprc.runtime_config.contract.schema import ConfigField
from apprc.runtime_config.tui.field_state import (
    ConfigResolvedSourceKey,
    ConfigWriteScope,
    EditableConfigValueSource,
    EditableConfigValueSourceKey,
)
from apprc.runtime_config.tui.rendering import (
    field_type_label,
    field_type_style,
    possible_values_label,
    possible_values_style,
    value_style,
)
from apprc.runtime_config.tui.styles import (
    DEFAULT_STYLE,
    EFFECTIVE_SOURCE_STYLE,
    LABEL_STYLE,
    PATH_INPUT_CLASS,
    SECRET_STYLE,
)

EDIT_TARGET_INPUT_CLASS = "edit-target-input"
SOURCE_LABELS: dict[EditableConfigValueSourceKey, str] = {
    "effective": "Effective",
    "shell": "Shell",
    "app": "App-wide",
    "storage": "Storage",
    "shared": "Shared default",
}
SOURCE_ORIGIN_LABELS: dict[ConfigResolvedSourceKey, str] = {
    "shell": SOURCE_LABELS["shell"],
    "app": SOURCE_LABELS["app"],
    "storage": SOURCE_LABELS["storage"],
    "shared": SOURCE_LABELS["shared"],
}


def config_value_source_key(value: str) -> EditableConfigValueSourceKey | None:
    """Return a stable source key parsed from a widget identifier fragment.

    :param value: Candidate source key text.
    :return: Known source key, or ``None`` for unknown text.
    """
    match value:
        case "effective" | "shell" | "app" | "storage" | "shared":
            return value
        case _:
            return None


def source_label(source: EditableConfigValueSource) -> str:
    """Return the reader-facing label for one source row.

    :param source: Source row model.
    :return: Display label used in rows and copy notifications.
    """
    return SOURCE_LABELS[source.key]


def source_label_text(source: EditableConfigValueSource) -> Text:
    """Return the source label with Effective emphasized.

    :param source: Source row model.
    :return: Styled Rich text for the source label cell.
    """
    if source.key == "effective":
        return Text(source_label(source), style=EFFECTIVE_SOURCE_STYLE)
    return Text(source_label(source), style=LABEL_STYLE)


def source_origin_text(source: EditableConfigValueSource) -> Text:
    """Return the concrete origin for the effective source row.

    :param source: Source row model.
    :return: Styled origin text, or empty text when no origin is shown.
    """
    if source.key != "effective" or source.origin_key is None:
        return Text("")
    return Text(
        f"from {SOURCE_ORIGIN_LABELS[source.origin_key]}",
        style=LABEL_STYLE,
    )


def source_value_text(
    spec: ConfigField, source: EditableConfigValueSource
) -> Text:
    """Return redacted or styled text for one source value cell.

    :param spec: Field declaration that governs value rendering.
    :param source: Source row model.
    :return: Styled visible text for the source value.
    """
    if source.raw_value is None:
        return Text(_missing_source_label(source), style=_source_style(source))
    if source.raw_value == "":
        return Text("<empty>", style=_source_style(source))
    if spec.secret:
        return Text(
            "<secret>",
            style=(
                EFFECTIVE_SOURCE_STYLE
                if source.key == "effective"
                else SECRET_STYLE
            ),
        )
    return Text(source.raw_value, style=_source_style(source, spec=spec))


def field_type_text(spec: ConfigField) -> Text:
    """Return field type metadata with type-specific color.

    :param spec: Field declaration whose Python type is shown.
    :return: Styled type label.
    """
    return Text(field_type_label(spec), style=field_type_style(spec))


def possible_values_text(spec: ConfigField) -> Text:
    """Return accepted-value metadata with literal or choice styling.

    :param spec: Field declaration whose accepted values are shown.
    :return: Styled possible-values label.
    """
    return Text(possible_values_label(spec), style=possible_values_style(spec))


def shell_status_text(shell_source: EditableConfigValueSource | None) -> Text:
    """Return current shell status with quiet or active styling.

    :param shell_source: Shell source row when available.
    :return: Styled set/unset status text.
    """
    if shell_source is not None and shell_source.is_available:
        return Text("set", style=DEFAULT_STYLE)
    return Text("unset", style=LABEL_STYLE)


def target_input_classes(spec: ConfigField) -> str:
    """Return CSS classes for the embedded write-target input.

    :param spec: Field declaration that determines path-specific styling.
    :return: Space-separated Textual CSS classes.
    """
    classes = [EDIT_TARGET_INPUT_CLASS]
    if spec.python_type is Path:
        classes.append(PATH_INPUT_CLASS)
    return " ".join(classes)


def source_copy_is_disabled(
    source: EditableConfigValueSource,
    *,
    target_input_value: str,
) -> bool:
    """Return whether a source copy button should be disabled.

    :param source: Source row model.
    :param target_input_value: Current visible target override input text.
    :return: Whether the copy action has no value to copy.
    """
    if source.key in {"app", "storage"}:
        return not source.is_available and target_input_value == ""
    return not source.is_available


def _missing_source_label(source: EditableConfigValueSource) -> str:
    """Return the absent-value label for one source row."""
    if source.key in {"effective", "shared"}:
        return "missing"
    return "unset"


def scope_label(scope: ConfigWriteScope) -> str:
    """Return the button label fragment for one writable scope."""
    if scope == "app":
        return "App-wide"
    return "Storage"


def _source_style(
    source: EditableConfigValueSource,
    *,
    spec: ConfigField | None = None,
) -> str:
    """Return the style used for one source cell."""
    if source.key == "effective":
        return EFFECTIVE_SOURCE_STYLE
    if spec is None:
        return LABEL_STYLE
    return value_style(spec)
