"""Shared Typer adapters for AppRC CLI errors."""

from __future__ import annotations

import typer

from apprc.user_files.app_home.locations import AppRCDirectoryError

APP_PATH_PARAM_HINT = "AppRC path"


def app_path_bad_parameter(
    exc: AppRCDirectoryError | OSError,
) -> typer.BadParameter:
    """Return Typer's user-facing error for AppRC-managed path failures.

    :param exc: Failure raised while preparing an AppRC-managed path or its files.
    :return: Typer parameter error with a stable path hint.
    """
    return typer.BadParameter(str(exc), param_hint=APP_PATH_PARAM_HINT)
