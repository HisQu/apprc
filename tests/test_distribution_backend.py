"""Managed runtime backend snapshot and rollback safety."""

from __future__ import annotations

import contextlib
import hashlib
import io
import stat
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationTarget,
    OwnedOutput,
    ProjectSnapshot,
    PublicationImage,
    PublicationOutput,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime.backend import runtime_environment
from apprc.distribution.runtime import _os_integration


from apprc.distribution.runtime._os_integration import (
    capture_windows_registration,
    publish_windows_registration,
    remove_windows_registration,
    restore_windows_registration,
    windows_registration_intent,
)
from apprc.distribution.runtime.installation import (
    _persist_publication_image,
    _restore_pending_publication,
    _snapshot_metadata,
    offer_configuration_setup,
)
from apprc.services.installation import InstallationManager
from apprc.user_files.installation.codec import decode_record, encode_record
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)


class _RegistryKey:
    def __init__(self) -> None:
        self.values: dict[str, tuple[object, int]] = {}
        self.subkeys = 0

    def __enter__(self) -> _RegistryKey:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class _WindowsRegistry(ModuleType):
    HKEY_CURRENT_USER = 1
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        super().__init__("winreg")
        self.keys: dict[str, _RegistryKey] = {}
        self.writes = 0
        self.fail_after: int | None = None

    def OpenKey(
        self, _root: int, path: str, _reserved: int, _access: int
    ) -> _RegistryKey:
        try:
            return self.keys[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def CreateKeyEx(
        self, _root: int, path: str, _reserved: int, _access: int
    ) -> _RegistryKey:
        return self.keys.setdefault(path, _RegistryKey())

    def QueryInfoKey(self, key: _RegistryKey) -> tuple[int, int, int]:
        return key.subkeys, len(key.values), 0

    def EnumValue(
        self, key: _RegistryKey, index: int
    ) -> tuple[str, object, int]:
        name, (value, kind) = tuple(key.values.items())[index]
        return name, value, kind

    def SetValueEx(
        self,
        key: _RegistryKey,
        name: str,
        _reserved: int,
        kind: int,
        value: str,
    ) -> None:
        key.values[name] = (value, kind)
        self.writes += 1
        if self.writes == self.fail_after:
            raise OSError("registry write failed after mutation")

    def DeleteValue(self, key: _RegistryKey, name: str) -> None:
        del key.values[name]

    def DeleteKey(self, _root: int, path: str) -> None:
        if self.keys[path].subkeys:
            raise OSError("registry key has subkeys")
        del self.keys[path]


@pytest.fixture
def windows_registry(monkeypatch: pytest.MonkeyPatch) -> _WindowsRegistry:
    registry = _WindowsRegistry()
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(_os_integration, "os", SimpleNamespace(name="nt"))
    return registry


@pytest.mark.parametrize("existing_values", (-1, 0, 1, 3))
@pytest.mark.parametrize("fail_after", (1, 2, 3))
def test_registry_rollback_restores_absence_empty_partial_or_full_recipe(
    tmp_path: Path,
    windows_registry: _WindowsRegistry,
    existing_values: int,
    fail_after: int,
) -> None:
    identity = InstallationIdentity("fixture", "fixture", "app", None, ("app",))
    command = tmp_path / "app.exe"
    intent = windows_registration_intent(tmp_path, identity, command)
    subkey = intent.path.removeprefix("HKCU\\")
    previous = {
        name: (value, windows_registry.REG_SZ)
        for name, value in intent.values[: max(existing_values, 0)]
    }
    if existing_values >= 0:
        key = windows_registry.CreateKeyEx(1, subkey, 0, 3)
        key.values.update(previous)
    snapshot = capture_windows_registration(intent)
    assert snapshot is not None
    windows_registry.fail_after = fail_after

    if len(intent.values) - max(existing_values, 0) >= fail_after:
        with pytest.raises(OSError, match="after mutation"):
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
    else:
        assert (
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
            == intent
        )
    restore_windows_registration(snapshot)

    if existing_values < 0:
        assert subkey not in windows_registry.keys
    else:
        assert windows_registry.keys[subkey].values == previous


@pytest.mark.parametrize("foreign_change", ("value", "type", "extra", "subkey"))
def test_registry_capture_and_rollback_preserve_foreign_changes(
    tmp_path: Path,
    windows_registry: _WindowsRegistry,
    foreign_change: str,
) -> None:
    identity = InstallationIdentity("fixture", "fixture", "app", None, ("app",))
    command = tmp_path / "app.exe"
    intent = windows_registration_intent(tmp_path, identity, command)
    snapshot = capture_windows_registration(intent)
    assert snapshot is not None
    publish_windows_registration(
        tmp_path, identity, command, previous=(intent,)
    )
    subkey = intent.path.removeprefix("HKCU\\")
    key = windows_registry.keys[subkey]
    if foreign_change == "value":
        key.values["DisplayName"] = (
            "foreign application",
            windows_registry.REG_SZ,
        )
    elif foreign_change == "type":
        key.values["DisplayName"] = (identity.app_id, 4)
    elif foreign_change == "extra":
        key.values["ForeignValue"] = ("keep", windows_registry.REG_SZ)
    else:
        key.subkeys = 1
    before = dict(key.values)

    with pytest.raises(InstallationError):
        capture_windows_registration(intent)
    with pytest.raises(InstallationError):
        restore_windows_registration(snapshot)
    assert windows_registry.keys[subkey].values == before
    assert key.subkeys == (foreign_change == "subkey")


@pytest.mark.parametrize("missing", ("value", "key"))
def test_registry_rollback_restores_missing_preexisting_values(
    tmp_path: Path,
    windows_registry: _WindowsRegistry,
    missing: str,
) -> None:
    identity = InstallationIdentity("fixture", "fixture", "app", None, ("app",))
    command = tmp_path / "app.exe"
    intent = windows_registration_intent(tmp_path, identity, command)
    publish_windows_registration(
        tmp_path, identity, command, previous=(intent,)
    )
    snapshot = capture_windows_registration(intent)
    assert snapshot is not None
    subkey = intent.path.removeprefix("HKCU\\")
    if missing == "key":
        del windows_registry.keys[subkey]
    else:
        del windows_registry.keys[subkey].values["DisplayName"]

    restore_windows_registration(snapshot)

    assert windows_registry.keys[subkey].values == {
        name: (value, windows_registry.REG_SZ) for name, value in intent.values
    }


def test_runtime_environment_removes_manager_and_python_injection_only() -> (
    None
):
    captured = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/injected",
        "PYTHONHOME": "/injected-home",
        "PYTHONWARNINGS": "ignore",
        "PYAPP": "unexpected-binary",
        "PYAPP_ARGS": "unexpected-options",
        "_APPRC_RUNTIME_LEASE_HANDLE": "1234",
        "_APPRC_NATIVE_MANAGER": "unexpected-manager",
        "_APPRC_NATIVE_EXECUTABLE": "/unexpected",
        "_APPRC_APPLICATION_DIAGNOSTICS": "unexpected",
        "UV_INDEX_URL": "https://index.example/simple",
        "API_TOKEN": "preserve-me",
    }

    cleaned = runtime_environment(captured)

    assert cleaned == {
        "PATH": "/usr/bin",
        "UV_INDEX_URL": "https://index.example/simple",
        "API_TOKEN": "preserve-me",
    }


def test_publication_intent_roundtrips_authenticated_old_and_new_images(
    tmp_path: Path,
) -> None:
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    placement = InstallationPlacement(Layout.native())
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.12"),
    )
    operation_id = uuid4()
    old_bytes = b"old editable launcher"
    new_bytes = b"new editable launcher"
    output = PublicationOutput(
        tmp_path / "commands" / "fixture",
        PublicationImage(
            hashlib.sha256(old_bytes).hexdigest(), ".publication-old"
        ),
        PublicationImage(
            hashlib.sha256(new_bytes).hexdigest(), ".publication-new"
        ),
    )
    operation = InstallationOperation(
        operation_id,
        "replace",
        "running",
        InstallationTarget(identity, placement, runtime),
        placement,
        publication=(output,),
    )
    record = InstallationRecord(
        3,
        identity,
        "fixture",
        uuid4(),
        "0.31.0",
        placement,
        "incomplete",
        operation=operation,
    )

    encoded = encode_record(record)
    decoded = decode_record(encoded, app_id=identity.app_id)

    assert decoded.operation is not None
    assert decoded.operation.publication == (output,)


def test_expected_version_comes_from_digest_verified_retained_archive(
    tmp_path: Path,
) -> None:
    project = tmp_path / "mutable-source"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='snapshot-fixture'\nversion='9.9.9'\n",
        encoding="utf-8",
    )
    retained_pyproject = (
        "[build-system]\nrequires=[]\nbuild-backend='setuptools.build_meta'\n"
        "[project]\nname='snapshot-fixture'\nversion='1.2.3'\n"
        "requires-python='>=3.12'\n"
        "[project.scripts]\nsnapshot-fixture='snapshot_fixture:main'\n"
    ).encode()
    lock = b"version = 1\n"
    archive = tmp_path / "retained.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("pyproject.toml", retained_pyproject)
        package.writestr("uv.lock", lock)
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            "a" * 40,
        ),
        RuntimeSelection("3.12"),
    )
    identity = InstallationIdentity(
        "snapshot-fixture",
        "snapshot-fixture",
        "snapshot_fixture",
        None,
        ("snapshot-fixture",),
    )

    assert _snapshot_metadata(archive, runtime, identity) == "1.2.3"

    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(InstallationError, match="archive was modified"):
        _snapshot_metadata(archive, runtime, identity)


@pytest.mark.skipif(
    sys.platform != "win32", reason="requires a Windows HKCU registry"
)
@pytest.mark.parametrize("existing_values", (-1, 0, 1, 3))
@pytest.mark.parametrize("fail_after", (1, 2, 3))
def test_windows_registration_rollback_after_each_partial_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_values: int,
    fail_after: int,
) -> None:
    import winreg

    app_id = f"apprc-test-{uuid4().hex}"
    identity = InstallationIdentity(app_id, app_id, "app", None, ("app",))
    command = tmp_path / "app.exe"
    intent = windows_registration_intent(tmp_path, identity, command)
    subkey = intent.path.removeprefix("HKCU\\")
    absent = capture_windows_registration(intent)
    assert absent is not None and absent.values is None
    original_set = winreg.SetValueEx
    writes = 0

    def interrupt_after_write(key, name, reserved, kind, value):
        nonlocal writes
        original_set(key, name, reserved, kind, value)
        writes += 1
        if writes == fail_after:
            raise OSError("registry write failed after mutation")

    try:
        if existing_values >= 0:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE
            ) as key:
                for name, value in intent.values[:existing_values]:
                    original_set(key, name, 0, winreg.REG_SZ, value)
        previous = capture_windows_registration(intent)
        assert previous is not None
        monkeypatch.setattr(winreg, "SetValueEx", interrupt_after_write)
        if len(intent.values) - max(existing_values, 0) >= fail_after:
            with pytest.raises(OSError, match="after mutation"):
                publish_windows_registration(
                    tmp_path, identity, command, previous=(intent,)
                )
        else:
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
        monkeypatch.setattr(winreg, "SetValueEx", original_set)

        restore_windows_registration(previous)

        restored = capture_windows_registration(intent)
        assert restored is not None
        assert restored.values == previous.values
    finally:
        monkeypatch.setattr(winreg, "SetValueEx", original_set)
        restore_windows_registration(absent)


@pytest.mark.skipif(
    sys.platform != "win32", reason="requires a Windows HKCU registry"
)
def test_windows_registration_resumes_recorded_partial_recipe_and_rejects_subkeys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import winreg

    app_id = f"apprc-test-{uuid4().hex}"
    identity = InstallationIdentity(app_id, app_id, "app", None, ("app",))
    command = tmp_path / "app.exe"
    intent = windows_registration_intent(tmp_path, identity, command)
    subkey = intent.path.removeprefix("HKCU\\")
    original_set = winreg.SetValueEx
    interrupted = False

    def interrupt_after_first_value(key, name, reserved, kind, value):
        nonlocal interrupted
        original_set(key, name, reserved, kind, value)
        if not interrupted:
            interrupted = True
            raise RuntimeError("simulated process interruption")

    try:
        monkeypatch.setattr(winreg, "SetValueEx", interrupt_after_first_value)
        with pytest.raises(RuntimeError, match="simulated"):
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
        monkeypatch.setattr(winreg, "SetValueEx", original_set)

        assert (
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
            == intent
        )

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            subkey + r"\unexpected",
            0,
            winreg.KEY_SET_VALUE,
        ):
            pass
        with pytest.raises(InstallationError, match="subkeys"):
            publish_windows_registration(
                tmp_path, identity, command, previous=(intent,)
            )
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey + r"\unexpected")
        assert remove_windows_registration(intent)
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey + r"\unexpected")
        except FileNotFoundError:
            pass
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
            ) as key:
                for index in reversed(range(winreg.QueryInfoKey(key)[1])):
                    name = winreg.EnumValue(key, index)[0]
                    winreg.DeleteValue(key, name)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass


def test_retained_publication_resumes_only_an_authenticated_prefix(
    tmp_path: Path,
) -> None:
    content = b"authenticated command bytes"
    image_name = ".publication-prefix"
    image = PublicationImage(hashlib.sha256(content).hexdigest(), image_name)
    path = tmp_path / image_name
    path.write_bytes(content[:10])

    _persist_publication_image(tmp_path, image, content)
    assert path.read_bytes() == content

    path.write_bytes(b"unrelated bytes")
    with pytest.raises(InstallationError, match="unknown bytes"):
        _persist_publication_image(tmp_path, image, content)
    assert path.read_bytes() == b"unrelated bytes"


@pytest.mark.parametrize("third_party_change", (False, True))
def test_durable_publication_rollback_restores_only_its_exact_output(
    tmp_path: Path,
    third_party_change: bool,
) -> None:
    destination = tmp_path / "commands" / "fixture"
    destination.parent.mkdir()
    destination.write_bytes(b"new command")
    previous_bytes = b"previous command"
    intended_bytes = b"new command"
    previous_name = ".publication-old"
    intended_name = ".publication-new"
    previous_image = PublicationImage(
        hashlib.sha256(previous_bytes).hexdigest(),
        previous_name,
        mode=0o755,
    )
    intended_image = PublicationImage(
        hashlib.sha256(intended_bytes).hexdigest(), intended_name
    )
    (tmp_path / previous_name).write_bytes(previous_bytes)
    (tmp_path / intended_name).write_bytes(intended_bytes)
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    placement = InstallationPlacement(Layout.native())
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.12"),
    )
    operation_id = uuid4()
    operation = InstallationOperation(
        operation_id,
        "replace",
        "failed",
        InstallationTarget(identity, placement, runtime),
        placement,
        publication=(
            PublicationOutput(destination, previous_image, intended_image),
        ),
    )
    record = InstallationRecord(
        3,
        identity,
        "fixture",
        uuid4(),
        "1",
        placement,
        "incomplete",
        active_runtime=RuntimeSlot(
            uuid4(),
            runtime.source,
            runtime.selection,
            version="1",
            python_version="3.12",
        ),
        operation=operation,
        owned_outputs=(
            OwnedOutput("command", str(destination), previous_image.digest),
        ),
    )
    manager = InstallationManager(
        AppRC(app_id="fixture", paths=Paths()).schema,
        environment={},
        directory=tmp_path,
    )
    with installation_lock(tmp_path):
        write_record(tmp_path, record, expected_revision=None)
    published = OwnedOutput(
        "command",
        str(destination),
        hashlib.sha256(intended_bytes).hexdigest(),
    )
    if third_party_change:
        destination.write_bytes(b"concurrent unknown command")

    restored = _restore_pending_publication(manager, destination, published)

    if third_party_change:
        assert not restored
        assert destination.read_bytes() == b"concurrent unknown command"
    else:
        assert restored
        assert destination.read_bytes() == previous_bytes
        assert stat.S_IMODE(destination.stat().st_mode) == 0o755


def test_zero_resource_capabilities_do_not_offer_configuration_setup(
    tmp_path: Path,
) -> None:
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    runtime = RuntimeSlot(
        uuid4(),
        ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
        RuntimeSelection("3.12"),
        version="1.0.0",
        python_version="3.12.0",
    )
    placement = InstallationPlacement(Layout.native())
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="fixture",
        generation_id=uuid4(),
        support_version="1",
        placement=placement,
        status="ready",
        active_runtime=runtime,
    )
    inspection = InstallationInspection(
        "ready", tmp_path / "installation", "revision", identity.app_id, record
    )
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        offered = offer_configuration_setup(
            inspection,
            skip=False,
            input_stream=io.StringIO(""),
        )

    assert not offered
    assert output.getvalue() == ""


@pytest.mark.parametrize("link", [False, True])
def test_command_ownership_accepts_prior_or_pending_image(
    tmp_path: Path,
    link: bool,
) -> None:
    """Pending publication can be current even when the prior digest comes first."""
    if link and sys.platform == "win32":
        pytest.skip("POSIX global command link semantics")
    from apprc.distribution.runtime.installation import _check_owned_command

    destination = tmp_path / "command"
    if link:
        destination.symlink_to(tmp_path / "target")
        digest = _os_integration._link_digest(str(tmp_path / "target"))
    else:
        destination.write_bytes(b"pending")
        digest = hashlib.sha256(b"pending").hexdigest()
    previous = (
        OwnedOutput("command", str(destination), "a" * 64),
        OwnedOutput("command", str(destination), digest),
    )
    assert _os_integration._authorized_existing(destination, previous)
    if link:
        with pytest.raises(InstallationError, match="unsafe stable command"):
            _check_owned_command(destination, previous)
    else:
        _check_owned_command(destination, previous)
    foreign = (OwnedOutput("command", str(destination), "b" * 64),)
    with pytest.raises(InstallationError, match="outside AppRC ownership"):
        _os_integration._authorized_existing(destination, foreign)


@pytest.mark.parametrize(
    "failure", [None, "changed-type", "foreign-subkey", "delete-then-fail"]
)
def test_uninstall_registry_capture_uses_exact_typed_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows_registry: _WindowsRegistry,
    failure: str | None,
) -> None:
    """Uninstall shares typed before-images without accepting changed keys."""
    from apprc.distribution.runtime import uninstall_handoff

    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    output = windows_registration_intent(
        tmp_path, identity, tmp_path / "fixture"
    )
    publish_windows_registration(
        tmp_path, identity, tmp_path / "fixture", previous=(output,)
    )
    key_path = output.path.removeprefix("HKCU\\")
    key = windows_registry.keys[key_path]
    if failure == "changed-type":
        value, _kind = key.values["DisplayName"]
        key.values["DisplayName"] = (value, 99)
    elif failure == "foreign-subkey":
        key.subkeys = 1
    record = InstallationRecord(
        3,
        identity,
        "fixture",
        uuid4(),
        "1",
        InstallationPlacement(Layout.native()),
        "ready",
        active_runtime=EditableCheckout(tmp_path, tmp_path / ".venv"),
        owned_outputs=(output,),
    )
    monkeypatch.setattr(uninstall_handoff, "os", SimpleNamespace(name="nt"))
    removed = []
    if failure == "delete-then-fail":
        before = dict(key.values)
        delete_key = windows_registry.DeleteKey

        def delete_then_fail(root: int, path: str) -> None:
            delete_key(root, path)
            raise OSError("registry deletion failed after mutation")

        monkeypatch.setattr(windows_registry, "DeleteKey", delete_then_fail)
        with pytest.raises(OSError, match="after mutation"):
            uninstall_handoff._remove_registry_outputs(
                record, tmp_path, removed
            )
        assert key_path not in windows_registry.keys
        assert len(removed) == 1
        restore_windows_registration(removed[0])
        assert windows_registry.keys[key_path].values == before
        return
    if failure is not None:
        with pytest.raises(InstallationError):
            uninstall_handoff._remove_registry_outputs(
                record, tmp_path, removed
            )
        assert not removed
        assert windows_registry.keys[key_path] is key
    else:
        before = dict(key.values)
        uninstall_handoff._remove_registry_outputs(record, tmp_path, removed)
        assert key_path not in windows_registry.keys
        assert len(removed) == 1
        restore_windows_registration(removed[0])
        assert windows_registry.keys[key_path].values == before


def test_windows_command_replacement_denial_explains_running_processes(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    import os

    source = tmp_path / "source.exe"
    source.write_bytes(b"command")
    destination = tmp_path / "app.exe"

    def deny(*args):
        error = PermissionError("access denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(
        _os_integration,
        "os",
        SimpleNamespace(
            name="nt", fdopen=os.fdopen, fsync=os.fsync, replace=deny
        ),
    )
    with pytest.raises(PermissionError) as captured:
        _os_integration.publish_global_command(destination, source)
    assert "running application processes" in " ".join(captured.value.__notes__)


@pytest.mark.parametrize("failure", [None, 1, 2, 4])
def test_optional_app_list_update_recovers_partial_writes(
    tmp_path, monkeypatch, windows_registry, failure, caplog
):
    from apprc.distribution.runtime import _windows_registration as metadata
    from apprc.user_files.installation.discovery import inspect_installation
    import os

    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    runtime = EditableCheckout(
        tmp_path / "checkout", tmp_path / "checkout" / ".venv"
    )
    record = InstallationRecord(
        3,
        identity,
        "fixture",
        uuid4(),
        "1",
        InstallationPlacement(Layout.native()),
        "ready",
        active_runtime=runtime,
    )
    write_record(tmp_path, record, expected_revision=None)
    monkeypatch.setattr(
        metadata,
        "os",
        SimpleNamespace(
            name="nt", fsync=os.fsync, fdopen=os.fdopen, replace=os.replace
        ),
    )
    before = inspect_installation(tmp_path, app_id="fixture")
    windows_registry.fail_after = failure
    result = metadata.publish_registration(
        before, "1.2.3", tmp_path / "fixture.exe", "app"
    )
    assert result.status == "ready"
    if failure:
        assert "installation succeeded" in caplog.text
        windows_registry.fail_after = None
        result = metadata.publish_registration(
            inspect_installation(tmp_path, app_id="fixture"),
            "1.2.4",
            tmp_path / "fixture.exe",
            "app",
        )
    assert result.record is not None
    output = next(
        item for item in result.record.owned_outputs if item.kind == "hkcu"
    )
    assert dict(output.values)["DisplayVersion"] == (
        "1.2.4" if failure else "1.2.3"
    )
    assert not any(
        item.path == ".windows-registration.json"
        for item in result.record.owned_outputs
    )


@pytest.mark.parametrize("written", [0, 1, 2])
def test_uninstall_removes_journal_owned_partial_entry(
    tmp_path, monkeypatch, windows_registry, written
):
    import os
    from apprc.distribution.runtime import (
        _windows_registration as metadata,
        uninstall_handoff,
    )
    from apprc.user_files.installation.discovery import inspect_installation

    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    record = InstallationRecord(
        3,
        identity,
        "fixture",
        uuid4(),
        "1",
        InstallationPlacement(Layout.native()),
        "ready",
        active_runtime=EditableCheckout(
            tmp_path / "checkout", tmp_path / "checkout" / ".venv"
        ),
    )
    write_record(tmp_path, record, expected_revision=None)
    monkeypatch.setattr(
        metadata,
        "os",
        SimpleNamespace(
            name="nt", fsync=os.fsync, fdopen=os.fdopen, replace=os.replace
        ),
    )
    if written:
        windows_registry.fail_after = written
    else:

        def fail(*args):
            raise OSError("failed before first value")

        monkeypatch.setattr(windows_registry, "SetValueEx", fail)
    result = metadata.publish_registration(
        inspect_installation(tmp_path, app_id="fixture"),
        "1.2.3",
        tmp_path / "fixture.exe",
        "settings",
    )
    assert result.record is not None
    monkeypatch.setattr(uninstall_handoff, "os", SimpleNamespace(name="nt"))
    snapshots = []
    uninstall_handoff._remove_registry_outputs(
        result.record, tmp_path, snapshots
    )
    assert not windows_registry.keys
    assert len(snapshots) == 1
