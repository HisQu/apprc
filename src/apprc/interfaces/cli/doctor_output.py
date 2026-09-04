"""Human-readable ``config doctor`` output."""

from __future__ import annotations

# == 3rd Party ===============================
from rich.console import Console
from rich.text import Text

# == Internal ================================
from apprc.runtime.diagnostics.payload import ConfigDoctorPayload
from apprc.runtime.diagnostics.status import ConfigDoctorStatus
from apprc.definition.app_config.kit import AppConfigKit
from apprc.interfaces._terminal_styles import (
    DEFAULT_STYLE,
    ENV_KEY_STYLE,
    ERROR_STYLE,
    LABEL_STYLE,
    MISSING_STYLE,
    PATH_STYLE,
    env_key_text,
    label_value_text,
    path_text,
    style_literals,
)


def print_config_doctor(
    kit: AppConfigKit,
    payload: ConfigDoctorPayload,
) -> None:
    """Print a human-readable ``config doctor`` report."""
    console = Console(soft_wrap=True)
    console.print(_doctor_status_text(kit, payload))
    console.print("")
    for label, value in (
        ("storage_enabled", _bool_text(payload.storage_enabled)),
        ("writes", "none"),
    ):
        rendered = value if isinstance(value, Text) else Text(value)
        console.print(label_value_text(label, rendered))
    console.print("")
    for label, value in (
        ("apprc_dir", path_text(payload.apprc_dir)),
        ("apprc_dir_exists", _bool_text(payload.apprc_dir_exists)),
        ("user_dotenv", path_text(payload.user_dotenv)),
        ("user_dotenv_exists", _bool_text(payload.user_dotenv_exists)),
        (
            "storage_selector_env_key",
            _env_key_or_none_text(payload.storage_selector_env_key),
        ),
        ("apprc_dir_env_key", env_key_text(payload.apprc_dir_env_key)),
        (
            "apprc_dir_env_value",
            _path_or_none_text(payload.apprc_dir_env_value),
        ),
        ("apprc_toml", _path_or_none_text(payload.apprc_toml)),
        ("apprc_toml_exists", _bool_text(payload.apprc_toml_exists)),
        ("apprc_toml_parse_ok", _bool_text(payload.apprc_toml_parse_ok)),
        ("storage_count", Text(str(payload.storage_count))),
        (
            "configured_selected_storage",
            _optional_text(payload.configured_selected_storage),
        ),
        ("selected_storage", _optional_text(payload.selected_storage)),
        (
            "selected_storage_source",
            _optional_text(payload.selected_storage_source),
        ),
        (
            "selected_storage_selector",
            _optional_text(payload.selected_storage_selector),
        ),
        (
            "selected_storage_selector_kind",
            _optional_text(payload.selected_storage_selector_kind),
        ),
        (
            "selected_storage_root",
            _path_or_none_text(payload.selected_storage_root),
        ),
        (
            "selected_storage_root_exists",
            _bool_or_none_text(payload.selected_storage_root_exists),
        ),
        (
            "selected_storage_dotenv",
            _path_or_none_text(payload.selected_storage_dotenv),
        ),
        (
            "selected_storage_dotenv_exists",
            _bool_or_none_text(payload.selected_storage_dotenv_exists),
        ),
    ):
        console.print(label_value_text(label, value))
    issues = payload.issues
    if issues:
        console.print("")
        console.print(Text("Issues:", style="bold"))
        for issue in issues:
            console.print(_styled_issue_text(kit, payload, issue))

    warnings = payload.warnings
    if warnings:
        console.print("")
        console.print(Text("Warnings:", style="bold"))
        for warning in warnings:
            console.print(_styled_issue_text(kit, payload, warning))

    next_steps = payload.next_steps
    if next_steps:
        console.print("")
        console.print(Text("Next steps:", style="bold"))
        for step in next_steps:
            console.print(Text(f"  {step}"))


def print_config_paths(
    kit: AppConfigKit,
    payload: ConfigDoctorPayload,
) -> None:
    """Print the zero-write ``config paths`` report."""
    console = Console(soft_wrap=True)
    console.print(Text(f"{kit.spec.display_name} config paths", style="bold"))
    console.print("")
    for label, value in (
        ("storage_enabled", _bool_text(payload.storage_enabled)),
        ("writes", payload.writes),
    ):
        rendered = value if isinstance(value, Text) else Text(value)
        console.print(label_value_text(label, rendered))
    console.print("")
    for label, value in (
        ("apprc_dir", path_text(payload.apprc_dir)),
        ("apprc_dir_exists", _bool_text(payload.apprc_dir_exists)),
        ("user_dotenv", path_text(payload.user_dotenv)),
        ("user_dotenv_exists", _bool_text(payload.user_dotenv_exists)),
        (
            "storage_selector_env_key",
            _env_key_or_none_text(payload.storage_selector_env_key),
        ),
        ("apprc_dir_env_key", env_key_text(payload.apprc_dir_env_key)),
        (
            "apprc_dir_env_value",
            _path_or_none_text(payload.apprc_dir_env_value),
        ),
        ("apprc_toml", _path_or_none_text(payload.apprc_toml)),
        ("apprc_toml_exists", _bool_text(payload.apprc_toml_exists)),
        ("apprc_toml_parse_ok", _bool_text(payload.apprc_toml_parse_ok)),
        ("storage_count", Text(str(payload.storage_count))),
        (
            "configured_selected_storage",
            _optional_text(payload.configured_selected_storage),
        ),
        (
            "selected_storage_source",
            _optional_text(payload.selected_storage_source),
        ),
        (
            "selected_storage_selector",
            _optional_text(payload.selected_storage_selector),
        ),
        (
            "selected_storage_selector_kind",
            _optional_text(payload.selected_storage_selector_kind),
        ),
        (
            "selected_storage_root",
            _path_or_none_text(payload.selected_storage_root),
        ),
        (
            "selected_storage_root_exists",
            _bool_or_none_text(payload.selected_storage_root_exists),
        ),
        (
            "selected_storage_dotenv",
            _path_or_none_text(payload.selected_storage_dotenv),
        ),
        (
            "selected_storage_dotenv_exists",
            _bool_or_none_text(payload.selected_storage_dotenv_exists),
        ),
    ):
        console.print(label_value_text(label, value))


def _doctor_status_text(
    kit: AppConfigKit,
    payload: ConfigDoctorPayload,
) -> Text:
    """Return the styled headline for one doctor payload.

    :param kit: Application config facade.
    :param payload: Doctor payload to summarize.
    :return: Rich text status line.
    """
    status_labels = {
        ConfigDoctorStatus.STORAGE_NOT_SELECTED.value: (
            "storage not selected",
            MISSING_STYLE,
        ),
        ConfigDoctorStatus.STORAGE_NOT_READY.value: (
            "storage not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.USER_DOTENV_NOT_READY.value: (
            "user dotenv not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.STORAGE_REGISTRY_NOT_READY.value: (
            "storage registry not ready",
            MISSING_STYLE,
        ),
        ConfigDoctorStatus.RUNNABLE.value: (
            "runnable",
            DEFAULT_STYLE,
        ),
    }
    label, style = status_labels[str(payload.status)]
    return Text.assemble(
        (f"{kit.spec.display_name} config doctor", "bold"),
        ": ",
        (label, style),
    )


def _optional_text(value: object | None) -> Text:
    """Return a displayed optional scalar value."""
    if value is None:
        return Text("<none>", style=LABEL_STYLE)
    return Text(str(value))


def _path_or_none_text(value: str | None) -> Text:
    """Return a styled path value or a dim unset marker.

    :param value: Optional path-like string.
    :return: Rich text path or ``<none>`` marker.
    """
    if value is None:
        return Text("<none>", style=LABEL_STYLE)
    return path_text(value)


def _env_key_or_none_text(value: str | None) -> Text:
    """Return a styled env key or a dim unset marker."""
    if value is None:
        return Text("<none>", style=LABEL_STYLE)
    return env_key_text(value)


def _bool_text(value: bool) -> Text:
    """Return a styled boolean value for doctor output."""
    style = DEFAULT_STYLE if value else ERROR_STYLE
    return Text(str(value).lower(), style=style)


def _bool_or_none_text(value: bool | None) -> Text:
    """Return a styled optional boolean value for doctor output."""
    if value is None:
        return Text("<none>", style=LABEL_STYLE)
    return _bool_text(value)


def _styled_issue_text(
    kit: AppConfigKit,
    payload: ConfigDoctorPayload,
    issue: str,
) -> Text:
    """Return one issue line with known env keys and paths styled.

    :param kit: Application config facade.
    :param payload: Doctor payload containing known literals.
    :param issue: Plain issue text.
    :return: Rich issue text.
    """
    styles = {
        kit.spec.apprc_dir_env_key: ENV_KEY_STYLE,
        "storage_not_selected": MISSING_STYLE,
        "user_dotenv_not_ready": ERROR_STYLE,
        "storage_registry_not_ready": MISSING_STYLE,
    }
    if kit.spec.storage_selector_env_key is not None:
        styles[kit.spec.storage_selector_env_key] = ENV_KEY_STYLE
    styles.update(
        {
            str(value): PATH_STYLE
            for value in (
                payload.apprc_dir,
                payload.user_dotenv,
                payload.apprc_dir_env_value,
                payload.apprc_toml,
                payload.selected_storage_root,
                payload.selected_storage_dotenv,
            )
            if value
        }
    )
    styled = style_literals(issue, styles)
    return Text.assemble("- ", styled)
