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
        ("storage_layer", payload.capabilities["storage"]),
        ("app_wide_layer", payload.capabilities["app_wide"]),
        ("named_storage_layer", payload.capabilities["named_storage"]),
        ("writes", "none"),
    ):
        console.print(label_value_text(label, Text(value)))
    console.print("")
    for label, value in (
        ("config_home", path_text(payload.config_home)),
        ("config_home_exists", _bool_text(payload.config_home_exists)),
        ("app_wide_env", path_text(payload.app_wide_env)),
        ("app_wide_env_exists", _bool_text(payload.app_wide_env_exists)),
        ("app_wide_active", _bool_text(payload.app_wide_active)),
        ("storage_env_key", _env_key_or_none_text(payload.storage_env_key)),
        ("index_env_key", env_key_text(payload.index_env_key)),
        ("index_env_value", _path_or_none_text(payload.index_env_value)),
        ("index_path", _path_or_none_text(payload.index_path)),
        ("index_exists", _bool_text(payload.index_exists)),
        ("index_parse_ok", _bool_text(payload.index_parse_ok)),
        ("storage_count", Text(str(payload.storage_count))),
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
            "selected_storage_root",
            _path_or_none_text(payload.selected_storage_root),
        ),
        (
            "selected_storage_root_exists",
            _bool_or_none_text(payload.selected_storage_root_exists),
        ),
        (
            "selected_storage_env",
            _path_or_none_text(payload.selected_storage_env),
        ),
        (
            "selected_storage_env_exists",
            _bool_or_none_text(payload.selected_storage_env_exists),
        ),
    ):
        console.print(label_value_text(label, value))
    if payload.missing_env_keys:
        console.print(
            label_value_text(
                "missing_env_keys",
                _env_key_list_text(payload.missing_env_keys),
            )
        )

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
        ("storage_layer", payload.capabilities["storage"]),
        ("app_wide_layer", payload.capabilities["app_wide"]),
        ("named_storage_layer", payload.capabilities["named_storage"]),
        ("writes", payload.writes),
    ):
        console.print(label_value_text(label, Text(value)))
    console.print("")
    for label, value in (
        ("config_home", path_text(payload.config_home)),
        ("config_home_exists", _bool_text(payload.config_home_exists)),
        ("app_wide_env", path_text(payload.app_wide_env)),
        ("app_wide_env_exists", _bool_text(payload.app_wide_env_exists)),
        ("app_wide_active", _bool_text(payload.app_wide_active)),
        ("storage_env_key", _env_key_or_none_text(payload.storage_env_key)),
        ("index_env_key", env_key_text(payload.index_env_key)),
        ("index_env_value", _path_or_none_text(payload.index_env_value)),
        ("index_path", _path_or_none_text(payload.index_path)),
        ("index_exists", _bool_text(payload.index_exists)),
        ("index_parse_ok", _bool_text(payload.index_parse_ok)),
        ("storage_count", Text(str(payload.storage_count))),
        (
            "selected_storage_source",
            _optional_text(payload.selected_storage_source),
        ),
        (
            "selected_storage_selector",
            _optional_text(payload.selected_storage_selector),
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
            "selected_storage_env",
            _path_or_none_text(payload.selected_storage_env),
        ),
        (
            "selected_storage_env_exists",
            _bool_or_none_text(payload.selected_storage_env_exists),
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
        ConfigDoctorStatus.ENV_NOT_SET.value: ("env not set", MISSING_STYLE),
        ConfigDoctorStatus.STORAGE_NOT_READY.value: (
            "storage not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.APP_CONFIG_NOT_READY.value: (
            "app config not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.NAMED_STORAGE_NOT_READY.value: (
            "named storage not ready",
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


def _env_key_list_text(env_keys: tuple[str, ...]) -> Text:
    """Return a comma-delimited env key list with semantic styling.

    :param env_keys: Missing env keys from the doctor payload.
    :return: Rich text list.
    """
    rendered = Text()
    for index, env_key in enumerate(env_keys):
        if index:
            rendered.append(", ")
        rendered.append_text(env_key_text(env_key))
    return rendered


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
        kit.spec.index_env_key: ENV_KEY_STYLE,
        "env_not_set": MISSING_STYLE,
        "app_config_not_ready": ERROR_STYLE,
        "named_storage_not_ready": MISSING_STYLE,
    }
    if kit.spec.storage_env_key is not None:
        styles[kit.spec.storage_env_key] = ENV_KEY_STYLE
    styles.update(
        {
            str(value): PATH_STYLE
            for value in (
                payload.config_home,
                payload.app_wide_env,
                payload.index_env_value,
                payload.index_path,
                payload.selected_storage_root,
                payload.selected_storage_env,
            )
            if value
        }
    )
    styled = style_literals(issue, styles)
    return Text.assemble("- ", styled)
