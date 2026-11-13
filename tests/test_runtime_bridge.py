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
        lambda *_args, **_kwargs: pytest.fail("bridge must reject before spawn"),
    )
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", "fixture_app:APP_RC", ("fixture",)
    )
    with pytest.raises(InstallationError, match="Unknown application bridge action"):
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
        lambda *_args, **_kwargs: pytest.fail("bridge must reject before spawn"),
    )
    identity = InstallationIdentity("fixture", "fixture", "fixture", None, ("fixture",))
    with pytest.raises(InstallationError, match="does not match saved identity"):
        application_bridge(
            tmp_path / "installation",
            identity,
            EditableCheckout(tmp_path / "checkout", tmp_path / "environment"),
            command_name="foreign",
            action="probe",
            environment={},
        )
    assert not (tmp_path / "installation").exists()
