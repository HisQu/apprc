"""Support publication remains authorized only by saved digest evidence."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath

import pytest

from apprc.definition.installation import (
    InstallPlan,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationSource,
    InstalledSnapshot,
    UvToolTarget,
)
from apprc.definition.paths import Layout
from apprc.distribution.runtime.acquisition import PreparedSource
from apprc.distribution.runtime import installation
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import plan_install, plan_repair


def _scenario(
    tmp_path: Path,
) -> tuple[Path, InstallPlan, InstalledSnapshot, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    source = InstallationSource("editable", str(project))
    identity = InstallationIdentity(
        "fixture", "fixture", "fixture", None, ("fixture-command",)
    )
    placement = InstallationPlacement(Layout.native())
    backend = UvToolTarget(
        tmp_path / "uv", tmp_path / "tools", tmp_path / "bin"
    )
    directory = tmp_path / "installation"
    plan = plan_install(
        identity,
        source,
        placement,
        backend,
        inspection=inspect_installation(directory, app_id=identity.app_id),
    )
    command = tmp_path / "fixture-command"
    command.write_text("#!/bin/sh\n")
    command.chmod(0o700)
    snapshot = InstalledSnapshot(
        identity,
        "1.0",
        source,
        placement,
        backend,
        tmp_path / "tools" / "fixture",
        tmp_path / "tools" / "fixture" / "python",
        (command,),
    )
    environment = {"PATH": os.environ.get("PATH", "")}
    return directory, plan, snapshot, environment


def _run(
    plan: InstallPlan,
    environment: dict[str, str],
    support: dict[PurePosixPath, bytes],
) -> InstallationInspection:
    prepared = PreparedSource(
        plan.target.source.requirement, None, plan.target.source
    )
    return installation.install_application(
        plan,
        environment=environment,
        probe_path=Path(__file__).absolute(),
        support_files=support,
        python_requirement=">=3.12",
        prepared_source=prepared,
    )


def _stub_backend(
    monkeypatch: pytest.MonkeyPatch, snapshot: InstalledSnapshot
) -> None:
    monkeypatch.setattr(
        installation,
        "inspect_uv_tools",
        lambda target, *, environment: frozenset(),
    )
    monkeypatch.setattr(
        installation,
        "install_uv_tool",
        lambda target, source, *, environment, python_requirement, constraints: (
            None
        ),
    )
    monkeypatch.setattr(
        installation,
        "probe_installed_tool",
        lambda target, identity, source, placement, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        installation,
        "external_base_python",
        lambda prefix, **kwargs: Path(sys.executable),
    )
    monkeypatch.setattr(
        installation,
        "_register_windows",
        lambda *args, **kwargs: None,
    )


@pytest.mark.parametrize("edit_after_interruption", (False, True))
def test_repair_handles_interrupted_address_bound_support_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit_after_interruption: bool,
) -> None:
    directory, plan, snapshot, environment = _scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    support = {
        PurePosixPath("launch-command.json"): b'{"command":"fixture-command"}',
        PurePosixPath("uninstall.py"): (
            b'BASE_PYTHON = "__APPRC_BASE_PYTHON__"\n'
        ),
    }
    original_write = installation.write_bytes_atomic

    def publish_then_interrupt(path: Path, content: bytes, *, private: bool):
        original_write(path, content, private=private)
        if path.name == "uninstall.py":
            raise RuntimeError(
                "interrupted after address-bound support publication"
            )

    monkeypatch.setattr(
        installation, "write_bytes_atomic", publish_then_interrupt
    )
    with pytest.raises(RuntimeError, match="address-bound support publication"):
        _run(plan, environment, support)

    pending = inspect_installation(directory, app_id="fixture")
    assert pending.record is not None and pending.record.operation is not None
    repair = plan_repair(
        plan.target.identity,
        plan.target.source,
        plan.target.placement,
        plan.target.backend,
        inspection=pending,
    )
    uninstall = directory / "uninstall.py"
    if edit_after_interruption:
        uninstall.write_bytes(b"edited uninstall helper")
        with pytest.raises(InstallationError, match="unowned support output"):
            _run(repair, environment, support)
        assert uninstall.read_bytes() == b"edited uninstall helper"
        return

    monkeypatch.setattr(installation, "write_bytes_atomic", original_write)
    result = _run(repair, environment, support)
    expected = (
        "BASE_PYTHON = "
        + json.dumps(str(Path(sys.executable)), ensure_ascii=True)
        + "\n"
    ).encode("ascii")
    assert result.status == "ready"
    assert uninstall.read_bytes() == expected


def test_existing_support_matching_desired_bytes_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, plan, snapshot, environment = _scenario(tmp_path)
    _stub_backend(monkeypatch, snapshot)
    destination = directory / "controller.py"
    create_private_directory_if_missing(destination.parent)
    destination.write_bytes(b"desired controller")

    with pytest.raises(InstallationError, match="unowned support output"):
        _run(
            plan,
            environment,
            {PurePosixPath("controller.py"): b"desired controller"},
        )

    assert destination.read_bytes() == b"desired controller"
