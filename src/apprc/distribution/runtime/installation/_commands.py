"""Select command destinations and expose committed commands on Windows."""

from __future__ import annotations

import apprc.utils as ut

import logging
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from apprc.definition.installation import (
    InstallationError,
    InstallationInspection,
    InstallationRecord,
    OwnedOutput,
)
from apprc.distribution.runtime._install_progress import report, warn
from apprc.distribution.runtime._os_integration import (
    command_is_owned,
    validate_command_directory,
)
from apprc.user_files.app_home.locations import assert_no_links


if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager

LOG = logging.getLogger(__name__)


def command_filename(command_name: str) -> str:
    if (
        not command_name
        or command_name in {".", ".."}
        or any(character in command_name for character in "/\\\x00")
    ):
        raise InstallationError("Primary command must be a single filename.")
    return command_name + (".exe" if os.name == "nt" else "")


def _path_entries(environment: Mapping[str, str]) -> tuple[Path, ...]:
    return tuple(
        Path(item).expanduser().absolute()
        for item in environment.get("PATH", "").split(os.pathsep)
        if item
    )


def uv_command_directory(uv: Path, environment: Mapping[str, str]) -> Path:
    """Resolve the shared user bin the same way for both install modes."""
    result = subprocess.run(
        [str(uv), "tool", "dir", "--bin", "--no-config"],
        env=dict(environment),
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def select_command_directory(
    uv: Path,
    selected: Path | None,
    environment: Mapping[str, str],
    forbidden: tuple[Path, ...],
) -> Path:
    if selected is None:
        selected = uv_command_directory(uv, environment)
    validate_command_directory(
        selected,
        forbidden=forbidden,
        path_entries=_path_entries(environment),
    )
    return selected


def recorded_command_directory(
    record: InstallationRecord, directory: Path
) -> Path | None:
    """Read the single recorded global command location without consulting PATH."""
    name = command_filename(record.command_name)
    stable = directory / name
    parents = {
        path.parent
        for item in record.owned_outputs
        if item.kind == "command"
        and os.path.normcase((path := Path(item.path)).name)
        == os.path.normcase(name)
        and os.path.normcase(str(path)) != os.path.normcase(str(stable))
    }
    if len(parents) > 1:
        raise InstallationError(
            "Multiple recorded command locations. Use the publisher's manual update procedure."
        )
    return next(iter(parents), None)


def select_windows_global_command(
    uv: Path,
    environment: Mapping[str, str],
    stable: Path,
    prior_outputs: tuple[OwnedOutput, ...],
) -> Path:
    """Reuse a recorded user bin on PATH or select uv's standard user bin."""
    from apprc.distribution.runtime import _windows_command_path

    name = stable.name
    candidates = (
        path.parent
        for item in prior_outputs
        if item.kind == "command"
        and (path := Path(item.path)).name.casefold() == name.casefold()
        and path != stable
    )
    directory = next(
        (
            candidate
            for candidate in candidates
            if _windows_command_path.is_user_directory(candidate, environment)
            and _windows_command_path.is_on_path(candidate, environment)
        ),
        None,
    )
    if directory is None:
        directory = uv_command_directory(uv, environment)
    return directory / name


def update_windows_user_path(
    manager: InstallationManager,
    inspection: InstallationInspection,
    command: Path,
    environment: Mapping[str, str],
) -> None:
    """Expose an owned command only after its installation has activated."""
    from apprc.distribution.runtime import _windows_command_path

    record = inspection.record
    if (
        inspection.status != "ready"
        or record is None
        or record.operation is not None
    ):
        return
    try:
        current = manager.inspect()
        if (
            current.status != "ready"
            or current.revision != inspection.revision
            or current.record != record
        ):
            raise InstallationError(
                "Installation authority changed before updating user PATH."
            )
        assert_no_links(command)
        if not _windows_command_path.is_user_directory(
            command.parent, environment
        ):
            raise InstallationError(
                "The published command is outside the current user's directories."
            )
        if not command.is_file() or not command_is_owned(
            command, record.owned_outputs, ut.sha256_file(command)
        ):
            raise InstallationError(
                "The published command could not be verified."
            )
        if not _windows_command_path.ensure_user_path(
            command.parent, environment
        ):
            if not _windows_command_path.is_on_current_path(
                command.parent, environment
            ):
                report(
                    "detail",
                    "Open a new PowerShell window to use the global command.",
                )
            return
    except Exception as error:
        warn(
            LOG,
            "Unable to update the user PATH; run the installed command by its full path",
            error,
            path=command,
        )
        return
    report("result", "User PATH", "UPDATED", command.parent)
    try:
        _windows_command_path.notify_path_change()
    except OSError as error:
        warn(
            LOG,
            "User PATH was saved but Windows could not refresh existing shells",
            error,
        )
    report("detail", "Open a new PowerShell window to use the global command.")
