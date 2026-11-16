"""Shared installation authority fixtures and owned child-process lifetimes."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from apprc.definition.installation import (
    InstallationHooks,
    InstallationIdentity,
    InstallationPlacement,
    InstallationRecord,
    ProjectSnapshot,
    RetiredResource,
    RuntimeSelection,
    RuntimeSlot,
)
from apprc.definition.paths import Layout, ResourceKind
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)


def installation_record() -> InstallationRecord:
    identity = InstallationIdentity(
        "coordination-fixture",
        "coordination-fixture",
        "coordination_fixture",
        None,
        ("coordination-fixture",),
    )
    return InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name="coordination-fixture",
        generation_id=uuid4(),
        support_version="0.31.0",
        placement=InstallationPlacement(Layout.native()),
        status="removed-retained",
    )


def managed_installation(
    tmp_path: Path,
    *,
    cache_root: Path | None = None,
    config_root: Path | None = None,
    retired: tuple[RetiredResource, ...] = (),
    hooks: InstallationHooks = InstallationHooks(
        cleanup="handoff_test.hooks:cleanup"
    ),
) -> tuple[Path, RuntimeSlot]:
    directory = tmp_path / "installation"
    create_private_directory_if_missing(directory)
    identity = InstallationIdentity(
        "handoff-app",
        "handoff-test",
        "handoff_test",
        None,
        ("handoff-app",),
    )
    resources: tuple[tuple[ResourceKind, Path | None], ...] = (
        ("config", config_root),
        ("cache", cache_root),
    )
    placement = InstallationPlacement(
        Layout.native(),
        config_dir=config_root,
        cache_dir=cache_root,
        capabilities=frozenset(
            category for category, root in resources if root is not None
        ),
        retired=retired,
    )
    slot_id = uuid4()
    slot_directory = directory / "runtimes" / str(slot_id)
    slot_directory.mkdir(parents=True)
    (slot_directory / ".apprc-runtime-lease").touch()
    runtime = RuntimeSlot(
        slot_id,
        ProjectSnapshot("0" * 64, "1" * 64, "2" * 40),
        RuntimeSelection("3.12"),
        version="1.0",
        python_version="3.12.1",
        hooks=hooks,
    )
    record = InstallationRecord(
        schema_version=3,
        identity=identity,
        command_name=identity.commands[0],
        generation_id=uuid4(),
        support_version="0.31.0",
        placement=placement,
        status="ready",
        active_runtime=runtime,
    )
    with installation_lock(directory):
        write_record(directory, record, expected_revision=None)
    return directory, runtime


@contextmanager
def owned_child_process() -> Generator[subprocess.Popen[str], None, None]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.readline()"],
        stdin=subprocess.PIPE,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        if process.stdin is not None:
            process.stdin.close()
