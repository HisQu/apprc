"""Human-readable ``config doctor`` output."""

from __future__ import annotations

# == 3rd Party ===============================
from rich.console import Console
from rich.text import Text

# == Internal ================================
from apprc.runtime_config.doctor.payload import ConfigDoctorPayload
from apprc.runtime_config.doctor.status import ConfigDoctorStatus
from apprc.runtime_config.kit import AppConfigKit
from apprc.runtime_config.terminal_styles import (
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
    console.print(
        label_value_text(
            "config_home",
            path_text(payload["config_home"]),
        )
    )
    console.print(
        label_value_text(
            "config_home_exists",
            _bool_text(payload["config_home_exists"]),
        )
    )
    console.print(
        label_value_text(
            "global_env",
            path_text(payload["global_env"]),
        )
    )
    console.print(
        label_value_text(
            "global_env_exists",
            _bool_text(payload["global_env_exists"]),
        )
    )
    console.print(
        label_value_text(
            "apprc_toml_env_key",
            env_key_text(payload["apprc_toml_env_key"]),
        )
    )
    console.print(
        label_value_text(
            "apprc_toml_env_value",
            _path_or_none_text(payload["apprc_toml_env_value"]),
        )
    )
    console.print(
        label_value_text(
            "apprc_toml_path",
            _path_or_none_text(payload["apprc_toml_path"]),
        )
    )
    console.print(
        label_value_text(
            "apprc_toml_exists",
            _bool_text(payload["apprc_toml_exists"]),
        )
    )
    console.print(
        label_value_text(
            "apprc_toml_parse_ok",
            _bool_text(payload["apprc_toml_parse_ok"]),
        )
    )
    console.print(
        label_value_text("storage_count", str(payload["storage_count"]))
    )
    console.print(
        label_value_text(
            "selected_storage",
            _optional_text(payload["selected_storage"]),
        )
    )
    console.print(
        label_value_text(
            "selected_storage_source",
            _optional_text(payload["selected_storage_source"]),
        )
    )
    console.print(
        label_value_text(
            "selected_storage_root",
            _path_or_none_text(payload["selected_storage_root"]),
        )
    )
    console.print(
        label_value_text(
            "selected_local_env",
            _path_or_none_text(payload["selected_local_env"]),
        )
    )
    if payload["missing_env_keys"]:
        console.print(
            label_value_text(
                "missing_env_keys",
                _env_key_list_text(payload["missing_env_keys"]),
            )
        )

    issues = payload["issues"]
    if issues:
        console.print("")
        console.print(Text("Issues:", style="bold"))
        for issue in issues:
            console.print(_styled_issue_text(kit, payload, issue))

    warnings = payload["warnings"]
    if warnings:
        console.print("")
        console.print(Text("Warnings:", style="bold"))
        for warning in warnings:
            console.print(_styled_issue_text(kit, payload, warning))

    next_steps = payload["next_steps"]
    if next_steps:
        console.print("")
        console.print(Text("Next steps:", style="bold"))
        for step in next_steps:
            console.print(Text(f"  {step}"))


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
        ConfigDoctorStatus.CONFIG_NOT_READY.value: (
            "config not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.ENV_NOT_SET.value: ("env not set", MISSING_STYLE),
        ConfigDoctorStatus.MULTI_STORAGE_NOT_READY.value: (
            "multi-storage not ready",
            MISSING_STYLE,
        ),
        ConfigDoctorStatus.STORAGE_NOT_READY.value: (
            "storage not ready",
            ERROR_STYLE,
        ),
        ConfigDoctorStatus.RUNNABLE.value: (
            "runnable",
            DEFAULT_STYLE,
        ),
    }
    label, style = status_labels[str(payload["status"])]
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


def _bool_text(value: bool) -> Text:
    """Return a styled boolean value for doctor output."""
    style = DEFAULT_STYLE if value else ERROR_STYLE
    return Text(str(value).lower(), style=style)


def _env_key_list_text(env_keys: list[str]) -> Text:
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
        kit.spec.apprc_toml_env_key: ENV_KEY_STYLE,
        "env_not_set": MISSING_STYLE,
        "config_not_ready": ERROR_STYLE,
    }
    if kit.spec.storage_env_key is not None:
        styles[kit.spec.storage_env_key] = ENV_KEY_STYLE
    styles.update(
        {
            str(value): PATH_STYLE
            for value in (
                payload["config_home"],
                payload["global_env"],
                payload["apprc_toml_env_value"],
                payload["apprc_toml_path"],
                payload["selected_storage_root"],
                payload["selected_local_env"],
            )
            if value
        }
    )
    styled = style_literals(issue, styles)
    return Text.assemble("- ", styled)
