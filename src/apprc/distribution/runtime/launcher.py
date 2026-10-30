"""Run one recorded application command without changing its environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from apprc.distribution.runtime.inspection import inspect_saved_directory


def run_saved_launcher(
    directory: Path, command: str, arguments: list[str]
) -> int:
    """Execute the exact recorded command; do not sync or recreate its venv.

    :param directory: Explicit adjacent installation authority.
    :param command: Declared console-script command identity.
    :param arguments: Arguments forwarded unchanged to that command.
    :return: Application command exit status.
    """
    result = inspect_saved_directory(directory, app_id=directory.parent.name)
    record = result["record"]
    status = result["status"]
    if not isinstance(record, dict) or status not in {
        "ready",
        "removed-retained",
    }:
        print(
            "Application is not installed; use the saved installer to repair it.",
            file=sys.stderr,
        )
        return 2
    current = record.get("current")
    identity = current.get("identity") if isinstance(current, dict) else None
    commands = identity.get("commands") if isinstance(identity, dict) else None
    executables = current.get("commands") if isinstance(current, dict) else None
    if (
        not isinstance(commands, list)
        or not isinstance(executables, list)
        or command not in commands
    ):
        print(
            f"Command is not declared by this installation: {command}",
            file=sys.stderr,
        )
        return 2
    executable = Path(executables[commands.index(command)])
    if not executable.is_absolute() or not executable.is_file():
        print(
            "Recorded application command is missing; repair the installation.",
            file=sys.stderr,
        )
        return 2
    return subprocess.run([str(executable), *arguments], check=False).returncode


def main() -> int:
    """Dispatch the saved launch entry without importing application settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    return run_saved_launcher(
        arguments.directory, arguments.command, arguments.arguments
    )


if __name__ == "__main__":
    raise SystemExit(main())
