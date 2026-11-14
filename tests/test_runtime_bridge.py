"""Validate fixed bridge actions before invoking the recorded runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
)
from apprc.distribution.runtime.probe import application_bridge


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


def test_bridge_rejects_stale_authority_before_application_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        "action": "doctor",
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

    with pytest.raises(ValueError, match="authority revision changed"):
        installed_probe._serve_request(request)
