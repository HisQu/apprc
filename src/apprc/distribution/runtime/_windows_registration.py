"""Optional Windows app-list publication with an owned recovery journal."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from apprc.definition.installation import InstallationInspection, OwnedOutput
from apprc.distribution.runtime._install_progress import report, warn
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import record_owned_outputs

LOG = logging.getLogger(__name__)
_JOURNAL = ".windows-registration.json"


def _record(
    inspection: InstallationInspection, outputs: tuple[OwnedOutput, ...]
) -> InstallationInspection:
    record = inspection.require_usable()
    if record is None or inspection.revision is None:
        raise ValueError(
            "Windows metadata requires ready installation authority"
        )
    return record_owned_outputs(
        inspection.directory,
        app_id=record.identity.app_id,
        expected_revision=inspection.revision,
        generation_id=record.generation_id,
        owned_outputs=outputs,
    )


def recover_registration(
    inspection: InstallationInspection,
) -> InstallationInspection:
    """Finish an owned optional registry update before install/uninstall.

    :param inspection: Ready installation while its lifecycle lock is held.
    :return: Updated authority, with exact registry ownership recorded.
    """
    import winreg

    record = inspection.require_usable()
    if record is None:
        return inspection
    journal = next(
        (
            item
            for item in record.owned_outputs
            if item.kind == "support" and item.path == _JOURNAL
        ),
        None,
    )
    if journal is None:
        return inspection
    path = inspection.directory / _JOURNAL
    assert_no_links(path)
    if not path.exists():
        previous = next(
            (item for item in record.owned_outputs if item.kind == "hkcu"), None
        )
        from apprc.distribution.runtime._os_integration import (
            capture_windows_registration,
        )

        if previous is not None:
            captured = capture_windows_registration(previous)
            assert captured is not None
        else:
            subkey = (
                "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
                + record.identity.app_id
            )
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_QUERY_VALUE
                ):
                    raise ValueError(
                        "Unrecorded Windows uninstall entry requires recovery"
                    )
            except FileNotFoundError:
                pass
        return _record(
            inspection,
            tuple(
                item for item in record.owned_outputs if item.path != _JOURNAL
            ),
        )
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != journal.digest:
        raise ValueError("Windows registration recovery journal changed")
    transition = json.loads(data)
    expected_path = (
        "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
        + record.identity.app_id
    )
    if transition["path"] != expected_path:
        raise ValueError("Windows registration recovery path differs")
    old, desired = transition["old"], transition["desired"]
    subkey = expected_path.removeprefix("HKCU\\")
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        )
    with key:
        children, count, _ = winreg.QueryInfoKey(key)
        current = {
            name: (value, kind)
            for name, value, kind in (
                winreg.EnumValue(key, index) for index in range(count)
            )
        }
        allowed = set(old) | set(desired)
        if children or any(
            name not in allowed
            or kind != winreg.REG_SZ
            or value not in (old.get(name), desired.get(name))
            for name, (value, kind) in current.items()
        ):
            raise ValueError(
                "Windows uninstall entry changed outside AppRC ownership"
            )
        for name, value in desired.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        if (
            "DisplayIcon" in old
            and "DisplayIcon" in current
            and "DisplayIcon" not in desired
        ):
            winreg.DeleteValue(key, "DisplayIcon")
    output = OwnedOutput("hkcu", expected_path, None, tuple(desired.items()))
    # > Retain the journal as owned support until all filesystem cleanup succeeds.
    result = _record(
        inspection,
        tuple(
            item for item in record.owned_outputs if item.path != expected_path
        )
        + (output,),
    )
    latest = result.record
    assert latest is not None
    path.unlink()
    result = _record(
        result,
        tuple(item for item in latest.owned_outputs if item.path != _JOURNAL),
    )
    return result


def publish_registration(
    inspection: InstallationInspection,
    version: str,
    command: Path,
    group: str,
    *,
    icon: Path | None = None,
    preserve_icon: bool = False,
) -> InstallationInspection:
    """Best-effort publication after the application has activated.

    :param inspection: Successful application activation.
    :param version: Full validated application version.
    :param command: Installed command used for interactive uninstall.
    :param group: Application maintenance command group.
    :param icon: Installed app-owned icon for the Windows entry, if configured.
    :param preserve_icon: Retain the previous icon after an optional icon failure.
    :return: Latest usable installation authority, even when metadata fails.
    """
    if os.name != "nt":
        return inspection
    report("stage", "Registering with Windows")
    try:
        import winreg

        with installation_lock(inspection.directory):
            record = inspection.require_usable()
            if record is None:
                return inspection
            inspection = inspect_installation(
                inspection.directory, app_id=record.identity.app_id
            )
            inspection = recover_registration(inspection)
            record = inspection.require_usable()
            assert record is not None
            registry_path = (
                "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
                + record.identity.app_id
            )
            previous = next(
                (
                    item
                    for item in record.owned_outputs
                    if item.kind == "hkcu" and item.path == registry_path
                ),
                None,
            )
            old = dict(previous.values) if previous is not None else {}
            status = "UPDATED"
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    registry_path.removeprefix("HKCU\\"),
                    0,
                    winreg.KEY_QUERY_VALUE,
                ) as key:
                    children, count, _ = winreg.QueryInfoKey(key)
                    actual = {
                        name: (value, kind)
                        for name, value, kind in (
                            winreg.EnumValue(key, index)
                            for index in range(count)
                        )
                    }
                    if (
                        children
                        or previous is None
                        or any(
                            name not in old
                            or pair != (old[name], winreg.REG_SZ)
                            for name, pair in actual.items()
                        )
                    ):
                        raise ValueError(
                            "Refusing to replace an unowned Windows uninstall entry"
                        )
                    old = {name: value for name, (value, _) in actual.items()}
            except FileNotFoundError:
                old = {}
                status = "REGISTERED"
            desired = {
                "DisplayName": record.identity.app_id,
                "DisplayVersion": version,
                "InstallLocation": str(inspection.directory),
                "UninstallString": f'"{command}" {group} uninstall --wait',
            }
            if icon is not None:
                from apprc.distribution.runtime._icons import (
                    windows_icon_location,
                )

                desired["DisplayIcon"] = windows_icon_location(icon)
            elif preserve_icon and "DisplayIcon" in old:
                desired["DisplayIcon"] = old["DisplayIcon"]
            path = inspection.directory / _JOURNAL
            assert_no_links(path)
            data = json.dumps(
                {"path": registry_path, "old": old, "desired": desired},
                sort_keys=True,
            ).encode()
            if path.exists():
                raise ValueError("Unowned Windows registration journal exists")
            output = OwnedOutput(
                "support", _JOURNAL, hashlib.sha256(data).hexdigest()
            )
            inspection = _record(inspection, (*record.owned_outputs, output))
            import tempfile

            fd, temporary = tempfile.mkstemp(
                prefix=".windows-registration-", dir=inspection.directory
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            result = recover_registration(inspection)
            report("result", "Windows Installed apps", status)
            return result
    except Exception as error:
        warn(
            LOG,
            "Windows Installed apps information was not updated; application installation succeeded",
            error,
        )
        return inspection


def pending_registry_output(directory: Path, record) -> OwnedOutput | None:
    """Read exact ownership of a partially published entry for uninstall.

    :param directory: Saved installation directory.
    :param record: Captured uninstall authority, including owned journal digest.
    :return: Actual owned registry values or no pending entry.
    """
    import winreg

    journal = next(
        (
            item
            for item in record.owned_outputs
            if item.kind == "support" and item.path == _JOURNAL
        ),
        None,
    )
    if journal is None:
        return None
    path = directory / _JOURNAL
    assert_no_links(path)
    if not path.exists():
        return None
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != journal.digest:
        raise ValueError("Windows registration recovery journal changed")
    transition = json.loads(data)
    expected = (
        "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
        + record.identity.app_id
    )
    if transition["path"] != expected:
        raise ValueError(
            "Windows registration journal addresses another application"
        )
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            expected.removeprefix("HKCU\\"),
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            children, count, _ = winreg.QueryInfoKey(key)
            current = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
    except FileNotFoundError:
        return None
    old, desired = transition["old"], transition["desired"]
    if desired.get("InstallLocation") != str(directory):
        raise ValueError(
            "Windows registration journal has another install location"
        )
    if children or any(
        name not in set(old) | set(desired)
        or kind != winreg.REG_SZ
        or value not in (old.get(name), desired.get(name))
        for name, (value, kind) in current.items()
    ):
        raise ValueError(
            "Windows uninstall entry changed outside AppRC ownership"
        )
    return (
        OwnedOutput(
            "hkcu",
            expected,
            None,
            tuple((name, value) for name, (value, _) in current.items()),
        )
        if current
        else OwnedOutput("hkcu", expected, None, tuple(desired.items()))
    )
