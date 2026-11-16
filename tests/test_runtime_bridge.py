"""Validate fixed bridge actions before invoking the recorded runtime."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
)
from apprc.distribution.runtime import probe

from apprc.distribution.runtime.probe import application_bridge


def test_bridge_request_uses_physical_temp_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    physical_parent = tmp_path / "physical-temp"
    physical_parent.mkdir()
    linked_parent = tmp_path / "linked-temp"
    linked_parent.symlink_to(physical_parent, target_is_directory=True)
    monkeypatch.setattr(
        probe.tempfile, "gettempdir", lambda: str(linked_parent)
    )
    request = probe._private_request_file(
        tmp_path / "installation", {"action": "probe"}, ()
    )
    try:
        assert request.parent.parent == physical_parent
        assert not request.is_symlink()
        assert json.loads(request.read_text(encoding="utf-8")) == {
            "action": "probe"
        }
    finally:
        shutil.rmtree(request.parent)


@pytest.mark.parametrize("acl_failure", [False, True, "native-error"])
def test_bridge_request_secures_windows_staging_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acl_failure: bool | str,
) -> None:
    staged: list[Path] = []
    set_private_acl = probe.set_windows_private_acl

    def private_acl(directory: Path) -> None:
        staged.append(directory)
        assert directory.parent == tmp_path
        assert tuple(directory.iterdir()) == ()
        if acl_failure == "native-error":
            raise RuntimeError("ACL update denied by native API")
        if acl_failure:
            raise PermissionError(13, "ACL update denied", str(directory))
        if os.name == "nt":
            set_private_acl(directory)

    monkeypatch.setattr(probe.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        probe, "os", SimpleNamespace(**{**vars(os), "name": "nt"})
    )
    monkeypatch.setattr(probe, "set_windows_private_acl", private_acl)
    if acl_failure:
        with pytest.raises(
            InstallationError, match="private bridge request directory"
        ) as failure:
            probe._private_request_file(
                tmp_path / "installation", {"action": "probe"}, ()
            )
        assert "ACL update denied" in str(failure.value)
        expected_error = (
            RuntimeError if acl_failure == "native-error" else PermissionError
        )
        assert isinstance(failure.value.__cause__, expected_error)
        assert len(staged) == 1
        assert not staged[0].exists()
        assert tuple(tmp_path.iterdir()) == ()
    else:
        request = probe._private_request_file(
            tmp_path / "installation", {"action": "probe"}, ()
        )
        try:
            assert staged == [request.parent]
            assert json.loads(request.read_text(encoding="utf-8")) == {
                "action": "probe"
            }
        finally:
            shutil.rmtree(request.parent)


def test_bridge_rejects_unknown_action_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "bridge must reject before spawn"
        ),
    )
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", "fixture_app:APP_RC", ("fixture",)
    )
    with pytest.raises(
        InstallationError, match="Unknown application bridge action"
    ):
        application_bridge(
            tmp_path / "installation",
            identity,
            EditableCheckout(tmp_path / "checkout", tmp_path / "environment"),
            command_name="fixture",
            action="shell",
            environment={},
        )
    assert not (tmp_path / "installation").exists()


def test_bridge_rejects_command_not_owned_by_identity_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "bridge must reject before spawn"
        ),
    )
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture",)
    )
    with pytest.raises(
        InstallationError, match="does not match saved identity"
    ):
        application_bridge(
            tmp_path / "installation",
            identity,
            EditableCheckout(tmp_path / "checkout", tmp_path / "environment"),
            command_name="foreign",
            action="probe",
            environment={},
        )
    assert not (tmp_path / "installation").exists()


@pytest.mark.parametrize(
    "action", ["initialize", "doctor", "inventory", "cleanup", "migrate"]
)
def test_bridge_rejects_stale_authority_before_application_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    import sys
    from types import ModuleType

    import apprc as rc
    from apprc.distribution.runtime import installed_probe

    module = ModuleType("runtime_bridge_fixture")
    module.__dict__["APP_RC"] = rc.AppRC(
        app_id="bridge-probe", paths=rc.Paths()
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)

    identity = {
        "app_id": "bridge-probe",
        "distribution": "bridge-probe",
        "import_package": "bridge_probe",
        "apprc_reference": "runtime_bridge_fixture:APP_RC",
        "commands": ["bridge-probe"],
    }
    request = {
        "action": action,
        "identity": identity,
        "command_name": "bridge-probe",
        "directory": str(tmp_path / "installation"),
        "expected_revision": "a" * 64,
        "runtime_options": {},
        "operation_context": None,
        "categories": [],
        "forget_retained": False,
        "migration_plan": None,
        "hooks": {
            "initialize": None,
            "inventory": None,
            "cleanup": None,
            "migrate": None,
        },
    }

    for handler in ("initialize", "doctor", "inventory", "cleanup", "migrate"):
        monkeypatch.setattr(
            installed_probe,
            f"_serve_{handler}",
            lambda *_args: pytest.fail(
                "Stale authority must not reach an action handler"
            ),
        )

    with pytest.raises(ValueError, match="authority revision changed"):
        installed_probe._serve_request(request)


def test_embedded_bridge_loads_without_registered_module() -> None:
    """The authenticated loader executes the bridge outside sys.modules."""
    from apprc.distribution.runtime import installed_probe

    source = Path(installed_probe.__file__).read_text(encoding="utf-8")
    namespace = {
        "__name__": "_apprc_embedded_probe_fixture",
        "__file__": installed_probe.__file__,
        "__package__": None,
        "__spec__": None,
    }
    exec(
        compile(source, installed_probe.__file__, "exec"), namespace, namespace
    )
    with pytest.raises(ValueError, match="request fields are invalid"):
        namespace["_serve_request"]({})
