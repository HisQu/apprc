"""Final-path locked project synchronization and recorded executable lookup."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    RuntimeSlot,
)
from apprc.distribution.runtime._leases import (
    acquire_runtime_lease,
    authorized_runtime_quiescence,
)
from apprc.user_files.app_home.locations import assert_no_links


def runtime_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Remove interpreter, PyApp and target-environment injection."""
    excluded = {
        "PYAPP",
        "VIRTUAL_ENV",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONBREAKPOINT",
        "PYTHONWARNINGS",
        "PYTHONNOUSERSITE",
        "PYTHONPLATLIBDIR",
        "PYTHONCOERCECLOCALE",
        "PYTHONUTF8",
        "UV_ACTIVE",
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PROJECT",
        "UV_WORKING_DIRECTORY",
        "UV_PYTHON",
        "UV_PYTHON_ENVIRONMENT",
        "UV_NO_SYNC",
        "UV_FROZEN",
        "_APPRC_RUNTIME_LEASE_HANDLE",
        "_APPRC_NATIVE_MANAGER",
        "_APPRC_NATIVE_EXECUTABLE",
        "_APPRC_APPLICATION_DIAGNOSTICS",
    }
    return {
        key: value
        for key, value in environment.items()
        if key not in excluded and not key.startswith(("PYAPP_", "UV_TOOL_"))
    }


def runtime_prefix(
    directory: Path, runtime: RuntimeSlot | EditableCheckout
) -> Path:
    """Return the lexical environment address, never a resolved base interpreter."""
    if isinstance(runtime, EditableCheckout):
        return runtime.environment
    return directory / "runtimes" / str(runtime.slot_id) / ".venv"


def runtime_interpreter(
    directory: Path, slot: RuntimeSlot | EditableCheckout
) -> Path:
    """Locate the recorded environment interpreter without resolving symlinks."""
    return runtime_prefix(directory, slot) / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )


def runtime_command(
    directory: Path,
    runtime: RuntimeSlot | EditableCheckout,
    command: str,
) -> Path:
    """Locate a validated primary or auxiliary console entry point."""
    if (
        not command
        or command in {".", ".."}
        or any(c in command for c in "/\\\x00")
    ):
        raise InstallationError("Console command must be a single filename.")
    return (
        runtime_prefix(directory, runtime)
        / ("Scripts" if os.name == "nt" else "bin")
        / (command + (".exe" if os.name == "nt" else ""))
    )


def sync_runtime_slot(
    uv: Path,
    directory: Path,
    identity: InstallationIdentity,
    slot: RuntimeSlot,
    *,
    environment: Mapping[str, str],
) -> None:
    """Synchronize only the candidate's final environment using its exact lock."""
    if not uv.is_absolute() or not uv.is_file():
        raise InstallationError(
            "Managed installation requires an absolute manager uv."
        )
    root = directory / "runtimes" / str(slot.slot_id)
    project = root / "source" / slot.source.project_path
    assert_no_links(root)
    assert_no_links(project)
    if not (project / "pyproject.toml").is_file():
        raise InstallationError("Verified runtime project metadata is missing.")
    captured = runtime_environment(environment)
    captured["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
    argv = [
        str(uv),
        "sync",
        "--locked",
        "--no-default-groups",
        "--no-editable",
        "--python",
        slot.selection.python,
        "--package",
        identity.distribution,
    ]
    for extra in slot.selection.extras:
        argv.extend(("--extra", extra))
    lease = authorized_runtime_quiescence(root)
    owns_lease = lease is None
    if lease is None:
        lease = acquire_runtime_lease(root)
    try:
        subprocess.run(
            argv,
            cwd=project,
            env=captured,
            check=True,
            **lease.subprocess_options(),
        )
    finally:
        if owns_lease:
            lease.close()
