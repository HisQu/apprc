"""Open one disposable shell for manually exercising an AppRC example."""

from __future__ import annotations

# == Standard Library ===========================================
import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

# == Internal ===================================================
from _example_apps_utils.registry import (
    EXAMPLE_APPS,
    ExampleAppSpec,
    example_app,
)


def _clean_environment(spec: ExampleAppSpec, root: Path) -> dict[str, str]:
    """Return an environment isolated from existing example state."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("APPRC_EXAMPLE_")
    }
    env["APPRC_EXAMPLE_LAB_ROOT"] = str(root)
    env[spec.apprc_dir_env_key] = str(root / "apprc")
    return env


def _walkthrough(spec: ExampleAppSpec, root: Path) -> tuple[str, ...]:
    """Return copyable commands for one fresh lab session."""
    command = spec.command_name
    storage_root = root / "storage"
    if spec.name == "config-only":
        return (
            f"{command} config paths",
            f"{command} config setup --yes",
            f"{command} config set profile lab --scope user",
            f"{command} run",
            f"{command} config doctor",
        )
    if spec.name == "explicit-env-precedence":
        explicit_root = root / "explicit-storage"
        env_file = root / "explicit.env"
        return (
            f"{command} config setup --storage-root {storage_root} --yes",
            f"{command} config storage add explicit {explicit_root} --yes",
            (
                f"{command} --storage default config set label "
                "storage-default --scope storage"
            ),
            (
                f"{command} --storage explicit config set label "
                "storage-explicit --scope storage"
            ),
            (
                f"printf '%s\\n' 'APPRC_EXAMPLE_PRECEDENCE_STORAGE=explicit' "
                f"'APPRC_EXAMPLE_PRECEDENCE_LABEL=explicit-file' > {env_file}"
            ),
            "export APPRC_EXAMPLE_PRECEDENCE_STORAGE=default",
            "export APPRC_EXAMPLE_PRECEDENCE_LABEL=shell",
            f"{command} --env-file {env_file} run",
            (
                f"{command} --env-file {env_file} "
                "--env-file-overrides-os-environ run"
            ),
        )
    setup = f"{command} config setup --storage-root {storage_root} --yes"
    required_key = spec.required_storage_key or "api_token"
    commands = [
        setup,
        (
            f"{command} --storage default config set {required_key} "
            "lab-secret --scope storage"
        ),
    ]
    if spec.name == "cli-runtime":
        commands.extend(
            (
                f"{command} status",
                f"{command} --workspace {root / 'workspace'} "
                "--model demo --dry-run run",
            )
        )
    else:
        commands.extend((f"{command} run", f"{command} config storage list"))
    return tuple(commands)


def _shell_command(env: Mapping[str, str]) -> tuple[str, ...]:
    """Return the current user's shell command for this platform."""
    if sys.platform == "win32":
        return (env.get("COMSPEC", "cmd.exe"),)
    return (env.get("SHELL", "/bin/sh"),)


def _open_shell(command: Sequence[str], *, env: Mapping[str, str]) -> int:
    """Run the interactive child shell and return its exit code."""
    return subprocess.run(command, env=dict(env), check=False).returncode


def run_lab(name: str) -> int:
    """Open one clean shell and remove its temporary state on exit.

    :param name: Example selector from :data:`EXAMPLE_APPS`.
    :return: Child shell exit code.
    """
    spec = example_app(name)
    with tempfile.TemporaryDirectory(prefix=f"apprc-{name}-") as temp:
        root = Path(temp)
        env = _clean_environment(spec, root)
        print(f"AppRC example: {name}")
        print(f"Temporary root: {root}")
        print(f"AppRC directory: {root / 'apprc'} (not created yet)")
        print("\nTry these commands:\n")
        for command in _walkthrough(spec, root):
            print(f"  {command}")
        print(
            "\nThe temporary root is deleted when this shell exits. "
            "Paths you explicitly choose outside it are not deleted.\n"
        )
        return _open_shell(_shell_command(env), env=env)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the requested example selector."""
    parser = argparse.ArgumentParser(
        description="Open a disposable shell for one AppRC example.",
    )
    parser.add_argument("example", choices=[spec.name for spec in EXAMPLE_APPS])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the disposable example lab."""
    raise SystemExit(run_lab(parse_args(argv).example))


if __name__ == "__main__":
    main()
