"""Shared Typer adapters for AppRC CLI errors."""

from __future__ import annotations

import typer

from apprc.user_files.app_home.locations import AppRCDirectoryError

APPRC_DIR_PARAM_HINT = "AppRC directory"


def apprc_dir_bad_parameter(
    exc: AppRCDirectoryError | OSError,
) -> typer.BadParameter:
    """Return Typer's user-facing error for AppRC-managed path failures.

    :param exc: Failure raised while preparing the AppRC directory or its files.
    :return: Typer parameter error with a stable directory hint.
    """
    return typer.BadParameter(str(exc), param_hint=APPRC_DIR_PARAM_HINT)
