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
    env[spec.root_env_key] = str(root / "apprc")
    return env


def _walkthrough(spec: ExampleAppSpec, root: Path) -> tuple[str, ...]:
    """Return copyable grouped commands for one fresh lab session."""
    command = spec.command_name
    commands = [f"{command} --help", f"{command} paths --json"]
    if spec.name == "cache-only":
        commands.extend(
            (
                f"{command} cache --help",
                f"{command} cache init",
                f"{command} paths cache",
            )
        )
    elif spec.name == "explicit-env-precedence":
        env_file = root / "explicit.env"
        commands.extend(
            (
                f"{command} workspace add default {root / 'workspace'}",
                f"{command} workspace add explicit {root / 'explicit-workspace'}",
                f"{command} --workspace default config set label workspace-default --scope workspace",
                f"{command} --workspace explicit config set label workspace-explicit --scope workspace",
                f"printf '%s\\n' 'APPRC_EXAMPLE_PRECEDENCE_WORKSPACE=explicit' "
                f"'APPRC_EXAMPLE_PRECEDENCE_LABEL=explicit-file' > {env_file}",
                "export APPRC_EXAMPLE_PRECEDENCE_WORKSPACE=default",
                "export APPRC_EXAMPLE_PRECEDENCE_LABEL=shell",
                f"{command} --env-file {env_file} run",
                f"{command} --env-file {env_file} --env-file-overrides-os-environ run",
            )
        )
    elif spec.uses_workspace:
        commands.append(f"{command} workspace add default {root / 'workspace'}")
        if spec.required_workspace_key is not None:
            commands.append(
                f"{command} --workspace default config set "
                f"{spec.required_workspace_key} lab-secret --scope workspace"
            )
        if spec.name == "cli-runtime":
            commands.extend(
                (
                    f"{command} status",
                    f"{command} --workspace default --workdir {root / 'workdir'} "
                    "--model demo --dry-run run",
                )
            )
        else:
            commands.append(f"{command} --workspace default run")
        commands.append(f"{command} workspace list")
    elif spec.uses_user_dotenv:
        key, value = (
            ("request_timeout", "15")
            if spec.name == "library-client"
            else ("profile", "lab")
        )
        commands.extend(
            (
                f"{command} config setup --yes",
                f"{command} config set {key} {value} --scope user",
                f"{command} run",
            )
        )
        if spec.name == "library-client":
            commands.append(
                "python -c 'from library_client import LibraryClient; "
                "print(LibraryClient().request_timeout)'"
            )
    else:
        commands.append(f"{command} run")
    commands.extend(
        (
            f"{command} doctor",
            f"{command} purge --all --dry-run --json",
        )
    )
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
        if spec.has_managed_paths:
            print(f"AppRC layout root: {root / 'apprc'} (not created yet)")
        else:
            print("Managed AppRC paths: none")
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
