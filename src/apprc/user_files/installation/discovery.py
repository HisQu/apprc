"""Fixed native discovery and non-throwing read-only authority inspection."""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
)
from apprc.user_files.installation.codec import decode_record


def native_user_directories(
    app_id: str, *, environment: Mapping[str, str]
) -> tuple[Path, Path, Path, Path, Path]:
    """Resolve platformdirs-compatible native paths from detached inputs.

    :param app_id: One validated filename component.
    :param environment: Captured native base inputs; never mutate process state.
    :return: Config, appdata container, cache, state and logs addresses.
    """
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None:
        raise InstallationError(
            "app_id must be one safe nonempty filename segment."
        )
    home_value = environment.get(
        "USERPROFILE" if sys.platform == "win32" else "HOME"
    )
    home = Path(home_value) if home_value else Path.home()
    if not home.is_absolute():
        raise InstallationError("Native home directory must be absolute.")
    if sys.platform == "win32":
        local = (
            Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
            / app_id
        )
        result = (
            local / "config",
            local,
            local / "Cache",
            local / "state",
            local / "Logs",
        )
    elif sys.platform == "darwin":
        data = home / "Library" / "Application Support" / app_id
        cache = home / "Library" / "Caches" / app_id
        result = (
            data / "config",
            data,
            cache,
            data / "state",
            home / "Library" / "Logs" / app_id,
        )
    else:

        def base(key: str, fallback: Path) -> Path:
            value = environment.get(key)
            path = Path(value) if value else fallback
            return path if path.is_absolute() else fallback

        config = base("XDG_CONFIG_HOME", home / ".config") / app_id
        data = base("XDG_DATA_HOME", home / ".local" / "share") / app_id
        cache = base("XDG_CACHE_HOME", home / ".cache") / app_id
        state = base("XDG_STATE_HOME", home / ".local" / "state") / app_id
        result = (config, data, cache, state, state / "log")
    if any(not path.is_absolute() for path in result):
        raise InstallationError("Native directory bases must be absolute.")
    return result


def installation_directory(
    app_id: str, *, environment: Mapping[str, str] | None = None
) -> Path:
    """Return the fixed native address without reading settings or creating it.

    :param app_id: Safe host application identity.
    :param environment: Detached input mapping, or a copy of current environment.
    :return: Native application data container's installation child.
    """
    captured = dict(os.environ if environment is None else environment)
    return (
        native_user_directories(app_id, environment=captured)[1]
        / "installation"
    )


def inspect_installation(
    directory: Path, *, app_id: str
) -> InstallationInspection:
    """Inspect only the explicitly addressed authority without creating files.

    :param directory: Fixed discovery address or saved helper's adjacent directory.
    :param app_id: Expected application identity.
    :return: Missing, valid lifecycle status, or invalid with structured diagnostics.
    """
    revision: str | None = None
    try:
        for parent in (directory, *directory.parents):
            try:
                info = parent.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0):
                raise InstallationError(
                    "Installation address contains a link or reparse point."
                )
        path = directory / "installation.json"
        try:
            info = path.lstat()
        except FileNotFoundError:
            return InstallationInspection("missing", directory, None, app_id)
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_reparse_tag", 0):
            raise InstallationError(
                "Installation authority must be a regular file."
            )
        content = path.read_bytes()
        revision = sha256(content).hexdigest()
        record = decode_record(content, app_id=app_id)
        diagnostics = (
            ()
            if record.status in {"ready", "removed-retained"}
            else (
                InstallationDiagnostic(
                    "pending-operation",
                    f"Installation is {record.status}.",
                    "Inspect installation and resume its matching installer or repair.",
                ),
            )
        )
        return InstallationInspection(
            record.status, directory, revision, app_id, record, diagnostics
        )
    except (OSError, InstallationError) as error:
        return InstallationInspection(
            "invalid",
            directory,
            revision,
            app_id,
            diagnostics=(
                InstallationDiagnostic(
                    "invalid-authority",
                    str(error),
                    "Preserve installation.json and run installation doctor/repair.",
                ),
            ),
        )
