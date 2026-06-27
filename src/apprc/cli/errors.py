"""Shared Typer adapters for AppRC CLI errors."""

from __future__ import annotations

import typer

from apprc.runtime_config.config_home import ConfigHomeError

CONFIG_HOME_PARAM_HINT = "config-home"


def config_home_bad_parameter(
    exc: ConfigHomeError | OSError,
) -> typer.BadParameter:
    """Return Typer's user-facing error for AppRC-managed path failures.

    :param exc: Failure raised while preparing the config home or files inside
        it.
    :return: Typer parameter error with the stable ``config-home`` hint.
    """
    return typer.BadParameter(str(exc), param_hint=CONFIG_HOME_PARAM_HINT)
