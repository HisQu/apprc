"""Owned global command links and copies for installed runtimes."""

from __future__ import annotations

import apprc.utils as ut

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    OwnedOutput,
)
from apprc.distribution.runtime._install_progress import report
from apprc.user_files.app_home.locations import assert_no_links


def _link_digest(target: str) -> str:
    return hashlib.sha256(os.fsencode(target)).hexdigest()


def validate_command_directory(
    directory: Path,
    *,
    forbidden: tuple[Path, ...],
    path_entries: tuple[Path, ...],
) -> None:
    """Require an existing absolute command directory on PATH and outside owned trees."""
    if not directory.is_absolute():
        raise InstallationError("Global command directory must be absolute.")
    assert_no_links(directory)
    resolved = directory.resolve(strict=True)
    if not resolved.is_dir():
        raise InstallationError(
            "Global command destination is not a directory."
        )
    if not any(
        resolved == entry.resolve(strict=False) for entry in path_entries
    ):
        raise InstallationError(
            f"Add {directory} to PATH before registering the global command."
        )
    if any(
        resolved == root.resolve(strict=False)
        or resolved.is_relative_to(root.resolve(strict=False))
        for root in forbidden
    ):
        raise InstallationError(
            "Global command directory must be outside the checkout and environment."
        )


def command_is_owned(
    destination: Path,
    previous: tuple[OwnedOutput, ...],
    digest: str,
) -> bool:
    """Match either prior or pending exact command bytes or link identity."""
    return any(
        item.kind == "command"
        and item.path == str(destination)
        and item.digest == digest
        for item in previous
    )


def _authorized_existing(
    destination: Path,
    previous: tuple[OwnedOutput, ...],
) -> bool:
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return False
    if not any(
        item.kind == "command" and item.path == str(destination)
        for item in previous
    ):
        raise InstallationError(
            f"Refusing to replace an unowned command: {destination}."
        )
    if stat.S_ISLNK(metadata.st_mode):
        actual = _link_digest(os.readlink(destination))
    elif stat.S_ISREG(metadata.st_mode):
        actual = ut.sha256_file(destination)
    else:
        raise InstallationError(
            "Recorded global command has an unsafe file type."
        )
    if not command_is_owned(destination, previous, actual):
        raise InstallationError(
            "Recorded global command changed outside AppRC ownership."
        )
    return True


def publish_global_command(
    command: Path,
    source: Path,
    *,
    previous: tuple[OwnedOutput, ...] = (),
) -> OwnedOutput:
    """Publish a POSIX symlink or Windows byte copy after checking exact ownership."""
    if (
        not command.is_absolute()
        or not source.is_absolute()
        or not source.is_file()
    ):
        raise InstallationError(
            "Global command source and destination must be absolute files."
        )
    parent = command.parent
    assert_no_links(parent)
    if not parent.is_dir():
        raise InstallationError("Global command directory is unavailable.")
    _authorized_existing(command, previous)
    if os.name != "nt":
        target = str(source)
        digest = _link_digest(target)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{command.name}.", suffix=".apprc-tmp", dir=parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        temporary.unlink()
        created_link = False
        try:
            temporary.symlink_to(target)
            created_link = True
            os.replace(temporary, command)
        finally:
            if created_link:
                temporary.unlink(missing_ok=True)
    else:
        content_digest = ut.sha256_file(source)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{command.name}.", suffix=".apprc-tmp", dir=parent
        )
        temporary = Path(temporary_name)
        try:
            with (
                os.fdopen(descriptor, "wb") as stream,
                source.open("rb") as origin,
            ):
                shutil.copyfileobj(origin, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, command)
            except PermissionError as error:
                if getattr(error, "winerror", None) == 5:
                    error.add_note(
                        f"Could not replace global command {command}. Stop any "
                        "running application processes, including servers, and retry. "
                        "If the error persists, check permissions."
                    )
                raise
        finally:
            temporary.unlink(missing_ok=True)
        digest = content_digest
    return OwnedOutput("command", str(command), digest)


def remove_owned_command(output: OwnedOutput) -> bool:
    """Remove a global command only while its exact link target or bytes still match."""
    if output.kind not in {"command", "shortcut"} or output.digest is None:
        raise InstallationError(
            "Owned command or shortcut declaration is malformed."
        )
    destination = Path(output.path)
    assert_no_links(destination.parent)
    try:
        metadata = destination.lstat()
    except FileNotFoundError:
        return True
    if stat.S_ISLNK(metadata.st_mode):
        actual = _link_digest(os.readlink(destination))
    elif stat.S_ISREG(metadata.st_mode):
        actual = ut.sha256_file(destination)
    else:
        raise InstallationError("Owned global command has an unsafe file type.")
    if actual != output.digest:
        raise InstallationError("Refusing to remove a modified global command.")
    destination.unlink()
    return True


def validate_global_command(
    command: Path,
    *,
    previous: tuple[OwnedOutput, ...] = (),
) -> None:
    """Check an existing command collision before lifecycle resource mutation."""
    if not command.is_absolute():
        raise InstallationError("Global command path must be absolute.")
    assert_no_links(command.parent)
    if not command.parent.is_dir():
        raise InstallationError("Global command directory is unavailable.")
    _authorized_existing(command, previous)


def windows_registration_intent(
    directory: Path,
    identity: InstallationIdentity,
    command: Path,
    *,
    maintenance_group_name: str = "app",
) -> OwnedOutput:
    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{identity.app_id}"
    expected = (
        ("DisplayName", identity.app_id),
        ("UninstallString", f'"{command}" {maintenance_group_name} uninstall'),
        ("InstallLocation", str(directory)),
    )
    return OwnedOutput("hkcu", rf"HKCU\{subkey}", None, expected)


@dataclass(frozen=True, slots=True)
class WindowsRegistrationSnapshot:
    """Exact prepublication registration; ``None`` values mean key absence."""

    intent: OwnedOutput
    values: tuple[tuple[str, str, int], ...] | None


def _validate_windows_registration(
    intent: OwnedOutput,
    subkeys: int,
    values: Mapping[str, tuple[object, int]],
) -> None:
    """Require an unchanged full or partial recorded registration recipe."""
    import winreg

    if subkeys:
        raise InstallationError(
            "Windows uninstall key contains unknown subkeys."
        )
    expected = dict(intent.values)
    if any(
        name not in expected or pair != (expected[name], winreg.REG_SZ)
        for name, pair in values.items()
    ):
        raise InstallationError(
            "Windows uninstall registration changed outside AppRC ownership."
        )


def capture_windows_registration(
    intent: OwnedOutput,
) -> WindowsRegistrationSnapshot | None:
    """Capture exact recipe values before publication, without claiming ownership.

    The caller must separately authenticate the recorded publication intent.
    Only its expected string values are accepted, including a partial recipe
    retained by an interrupted attempt.

    :param intent: Authenticated intended current-user registration recipe.
    :return: Prior typed values or key absence, or ``None`` outside Windows.
    """
    if os.name != "nt":
        return None
    if intent.kind != "hkcu" or intent.digest is not None:
        raise InstallationError(
            "Registry capture requires exact HKCU ownership."
        )
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            intent.path.removeprefix("HKCU\\"),
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            subkeys, count, _ = winreg.QueryInfoKey(key)
            values = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
            _validate_windows_registration(intent, subkeys, values)
            expected = dict(intent.values)
            previous = tuple(
                (name, expected[name], winreg.REG_SZ) for name in values
            )
    except FileNotFoundError:
        previous = None
    return WindowsRegistrationSnapshot(intent, previous)


def restore_windows_registration(snapshot: WindowsRegistrationSnapshot) -> None:
    """Undo recipe publication while refusing changed values or foreign subkeys.

    :param snapshot: Exact state captured before this attempt published values.
    """
    if os.name != "nt":
        return
    import winreg

    current = capture_windows_registration(snapshot.intent)
    assert current is not None
    if current.values is None and snapshot.values is None:
        return
    subkey = snapshot.intent.path.removeprefix("HKCU\\")
    previous = {
        name: (value, kind) for name, value, kind in snapshot.values or ()
    }
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        subkey,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        subkeys, count, _ = winreg.QueryInfoKey(key)
        values = {
            name: (value, kind)
            for name, value, kind in (
                winreg.EnumValue(key, index) for index in range(count)
            )
        }
        _validate_windows_registration(snapshot.intent, subkeys, values)
        for name in values.keys() - previous.keys():
            winreg.DeleteValue(key, name)
        for name, (value, kind) in previous.items():
            if name not in values:
                winreg.SetValueEx(key, name, 0, kind, value)
        if snapshot.values is None:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)


def publish_windows_registration(
    directory: Path,
    identity: InstallationIdentity,
    command: Path,
    *,
    previous: tuple[OwnedOutput, ...] = (),
    maintenance_group_name: str = "app",
) -> OwnedOutput | None:
    """Create only the exact registration recipe recorded as owned."""
    if os.name != "nt":
        return None
    import winreg

    output = windows_registration_intent(
        directory,
        identity,
        command,
        maintenance_group_name=maintenance_group_name,
    )
    if output not in previous:
        raise InstallationError(
            "Refusing to claim an unowned Windows uninstall key."
        )
    subkey = output.path.removeprefix("HKCU\\")
    expected = dict(output.values)
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            subkey_count, value_count, _ = winreg.QueryInfoKey(key)
            values = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(value_count)
                )
            }
            _validate_windows_registration(output, subkey_count, values)
            for name, value in expected.items():
                if name not in values:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except FileNotFoundError:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            subkey_count, value_count, _ = winreg.QueryInfoKey(key)
            values = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(value_count)
                )
            }
            _validate_windows_registration(output, subkey_count, values)
            for name, value in expected.items():
                if name not in values:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    return output


def remove_windows_registration(output: OwnedOutput) -> bool:
    """Delete only the exact owned HKCU value recipe without unknown subkeys."""
    if os.name != "nt":
        return True
    if output.kind != "hkcu" or output.digest is not None:
        raise InstallationError(
            "Registry removal requires exact HKCU ownership."
        )
    import winreg

    key_path = output.path.removeprefix("HKCU\\")
    expected = dict(output.values)
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        subkey_count, value_count, _ = winreg.QueryInfoKey(key)
        values = {
            name: (value, kind)
            for name, value, kind in (
                winreg.EnumValue(key, index) for index in range(value_count)
            )
        }
        if (
            subkey_count
            or set(values) != set(expected)
            or any(
                values[name] != (value, winreg.REG_SZ)
                for name, value in expected.items()
            )
        ):
            raise InstallationError(
                "Refusing to delete a modified Windows uninstall registration."
            )
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    return True


def _desktop_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def _desktop_path(value: Path) -> str:
    return (
        _desktop_escape(str(value))
        .replace("%", "%%")
        .replace(" ", "\\ ")
        .replace("\t", "\\t")
    )


def _shortcut_destination(
    identity: InstallationIdentity,
    *,
    start_menu: bool,
    desktop: bool,
) -> tuple[Path | None, ...]:
    destinations: list[Path | None] = []
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        shell = ctypes.WinDLL("shell32", use_last_error=True)
        get_folder = shell.SHGetFolderPathW
        get_folder.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
        ]
        get_folder.restype = ctypes.c_long

        def known_folder(csidl: int) -> Path:
            output = ctypes.create_unicode_buffer(32768)
            result = get_folder(None, csidl, None, 0, output)
            if result != 0:
                raise OSError(
                    result, "Windows shortcut directory is unavailable."
                )
            return Path(output.value)

        if start_menu:
            destinations.append(known_folder(0x0002) / f"{identity.app_id}.lnk")
        if desktop:
            destinations.append(known_folder(0x0010) / f"{identity.app_id}.lnk")
    else:
        data_home = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")
        )
        if start_menu:
            destinations.append(
                data_home / "applications" / f"{identity.app_id}.desktop"
            )
        if desktop:
            desktop_value = os.environ.get("XDG_DESKTOP_DIR")
            if desktop_value is None:
                user_dirs = (
                    Path(
                        os.environ.get(
                            "XDG_CONFIG_HOME", Path.home() / ".config"
                        )
                    )
                    / "user-dirs.dirs"
                )
                if user_dirs.is_file():
                    for line in user_dirs.read_text(
                        encoding="utf-8"
                    ).splitlines():
                        if line.startswith("XDG_DESKTOP_DIR="):
                            desktop_value = (
                                line.partition("=")[2].strip().strip('"')
                            )
                            desktop_value = desktop_value.replace(
                                "$HOME", str(Path.home())
                            )
                            break
            if not desktop_value:
                raise InstallationError(
                    "Desktop shortcut location is not configured."
                )
            destinations.append(
                Path(desktop_value).expanduser() / f"{identity.app_id}.desktop"
            )
    return tuple(destinations)


def desktop_shortcut_available(identity: InstallationIdentity) -> bool:
    """Return whether a desktop location is available for an optional prompt."""
    try:
        return any(
            path is not None and path.parent.is_dir()
            for path in _shortcut_destination(
                identity, start_menu=False, desktop=True
            )
        )
    except (OSError, InstallationError):
        return False


def publish_shortcuts(
    command: Path,
    identity: InstallationIdentity,
    *,
    display_name: str,
    start_menu: bool,
    desktop: bool,
    launch_enabled: bool,
    previous: tuple[OwnedOutput, ...] = (),
) -> tuple[OwnedOutput, ...]:
    """Publish requested OS shortcuts and return exact output ownership."""
    outputs: list[OwnedOutput] = []
    try:
        for destination in _shortcut_destination(
            identity, start_menu=start_menu, desktop=desktop
        ):
            assert destination is not None
            destination.parent.mkdir(parents=True, exist_ok=True)
            assert_no_links(destination.parent)
            old = next(
                (
                    item
                    for item in previous
                    if item.kind == "shortcut" and item.path == str(destination)
                ),
                None,
            )
            if destination.exists() or destination.is_symlink():
                metadata = destination.lstat()
                actual = (
                    ut.sha256_file(destination)
                    if stat.S_ISREG(metadata.st_mode)
                    else None
                )
                if old is None or old.digest != actual:
                    raise InstallationError(
                        f"Refusing to replace an unowned shortcut: {destination}."
                    )
                report("result", "Shortcut", "EXISTING", destination)
                continue
            with tempfile.TemporaryDirectory(
                prefix=f".{destination.name}.", dir=destination.parent
            ) as staging:
                temporary = Path(staging) / destination.name
                if os.name == "nt":
                    from win32com.client import Dispatch

                    shortcut = Dispatch("WScript.Shell").CreateShortcut(
                        str(temporary)
                    )
                    shortcut.TargetPath = str(command)
                    shortcut.Arguments = "launch" if launch_enabled else ""
                    shortcut.WorkingDirectory = str(command.parent)
                    shortcut.Description = display_name
                    shortcut.Save()
                else:
                    command_line = _desktop_path(command)
                    if launch_enabled:
                        command_line += " launch"
                    content = (
                        "[Desktop Entry]\nType=Application\n"
                        f"Name={_desktop_escape(display_name)}\n"
                        f"Exec={command_line}\nTerminal=false\n"
                    )
                    temporary.write_text(content, encoding="utf-8")
                    temporary.chmod(
                        0o755 if destination.parent.name == "Desktop" else 0o644
                    )
                digest = ut.sha256_file(temporary)
                os.replace(temporary, destination)
                outputs.append(
                    OwnedOutput("shortcut", str(destination), digest)
                )
    except BaseException:
        for output in reversed(outputs):
            try:
                remove_owned_command(output)
            except InstallationError:
                pass
        raise
    return tuple(outputs)
