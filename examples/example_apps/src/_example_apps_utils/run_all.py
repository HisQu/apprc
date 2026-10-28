"""Smoke-test every example through its installed CLI."""

from __future__ import annotations

# == Standard Library ===========================================
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# == Internal ===================================================
from _example_apps_utils.registry import EXAMPLE_APPS, ExampleAppSpec


def _example_environment(spec: ExampleAppSpec, root: Path) -> dict[str, str]:
    """Return a clean process environment for one smoke scenario."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("APPRC_EXAMPLE_")
    }
    env[spec.root_env_key] = str(root / "apprc")
    return env


def _run_cli(
    spec: ExampleAppSpec,
    args: Sequence[str],
    *,
    env: Mapping[str, str],
) -> str:
    """Run one installed example command or raise with useful output."""
    executable = shutil.which(spec.command_name)
    if executable is None:
        sibling = Path(sys.executable).parent / spec.command_name
        if sibling.is_file():
            executable = str(sibling)
    if executable is None:
        raise RuntimeError(
            f"{spec.command_name} is not installed. Install the local example "
            "package before running the smoke suite."
        )
    result = subprocess.run(
        [executable, *args],
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        output = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )
        raise RuntimeError(
            f"{spec.command_name} {' '.join(args)} failed with "
            f"exit code {result.returncode}:\n{output}"
        )
    return result.stdout


def _json_output(output: str) -> dict[str, Any]:
    """Parse the JSON emitted by one example command."""
    value = json.loads(output)
    if not isinstance(value, dict):
        raise RuntimeError("Example command returned non-object JSON.")
    return value


def _setup_workspace(
    spec: ExampleAppSpec,
    root: Path,
    env: Mapping[str, str],
) -> None:
    _run_cli(spec, ["config", "init"], env=env)
    _run_cli(
        spec, ["workspace", "add", "default", str(root / "workspace")], env=env
    )
    if spec.required_workspace_key is not None:
        _run_cli(
            spec,
            [
                "--workspace",
                "default",
                "config",
                "set",
                spec.required_workspace_key,
                "smoke-secret",
                "--scope",
                "workspace",
            ],
            env=env,
        )


def _clean_managed(
    spec: ExampleAppSpec,
    root: Path,
    env: Mapping[str, str],
) -> bool:
    """Purge managed resources while retaining unrelated external payloads."""
    if not spec.has_managed_paths:
        return True
    payload = root / "workspace" / "runner-payload.txt"
    if spec.uses_workspace:
        payload.write_text("keep", encoding="utf-8")
    preview = _json_output(
        _run_cli(spec, ["purge", "--all", "--dry-run", "--json"], env=env)
    )
    targets = [
        Path(target) for plan in preview["plans"] for target in plan["targets"]
    ]
    _run_cli(spec, ["purge", "--all", "--yes"], env=env)
    cleaned = all(not path.exists() for path in targets)
    if spec.uses_workspace:
        cleaned = cleaned and payload.read_text(encoding="utf-8") == "keep"
    if not cleaned:
        raise RuntimeError(
            "Purge did not remove its inventory or retained payloads changed."
        )
    return cleaned


def _smoke_standard(spec: ExampleAppSpec, root: Path) -> dict[str, object]:
    """Exercise declared command groups, application runtime, and scoped purge."""
    env = _example_environment(spec, root)
    _run_cli(spec, ["--help"], env=env)
    runtime_prefix: list[str] = []
    if spec.name == "cache-only":
        _run_cli(spec, ["cache", "--help"], env=env)
        _run_cli(spec, ["cache", "init"], env=env)
        cache = _json_output(
            _run_cli(spec, ["paths", "cache", "--json"], env=env)
        )
        if cache["exists"] is not True or cache["path"] != str(
            root / "apprc" / "cache"
        ):
            raise RuntimeError(
                "Cache-only initialization selected an unexpected path."
            )
        app_id = spec.app_id
    else:
        if spec.uses_workspace:
            _setup_workspace(spec, root, env)
            runtime_prefix = ["--workspace", "default"]
        elif spec.uses_user_dotenv:
            _run_cli(spec, ["config", "setup", "--yes"], env=env)
        run_args = [*runtime_prefix]
        if spec.name == "cli-runtime":
            _run_cli(spec, ["status"], env=env)
            run_args.extend(
                [
                    "--workdir",
                    str(root / "workdir"),
                    "--model",
                    "smoke",
                    "--dry-run",
                ]
            )
        app_id = _json_output(_run_cli(spec, [*run_args, "run"], env=env))[
            "app_id"
        ]
    doctor = _json_output(_run_cli(spec, ["doctor", "--json"], env=env))
    return {
        "example": spec.name,
        "doctor_status": doctor["status"],
        "app_id": app_id,
        "cleaned": _clean_managed(spec, root, env),
    }


def _smoke_precedence(spec: ExampleAppSpec, root: Path) -> dict[str, object]:
    """Prove shell and explicit-file precedence with distinct workspace roots."""
    env = _example_environment(spec, root)
    _setup_workspace(spec, root, env)
    _run_cli(
        spec,
        ["workspace", "add", "explicit", str(root / "explicit-workspace")],
        env=env,
    )
    for name, label in (
        ("default", "workspace-default"),
        ("explicit", "workspace-explicit"),
    ):
        _run_cli(
            spec,
            [
                "--workspace",
                name,
                "config",
                "set",
                "label",
                label,
                "--scope",
                "workspace",
            ],
            env=env,
        )
    explicit_env = root / "explicit.env"
    explicit_env.write_text(
        "APPRC_EXAMPLE_PRECEDENCE_WORKSPACE=explicit\n"
        "APPRC_EXAMPLE_PRECEDENCE_LABEL=explicit-file\n",
        encoding="utf-8",
    )
    shell_env = dict(env)
    shell_env["APPRC_EXAMPLE_PRECEDENCE_WORKSPACE"] = "default"
    shell_env["APPRC_EXAMPLE_PRECEDENCE_LABEL"] = "shell"
    base_args = ["--env-file", str(explicit_env)]
    shell_wins = _json_output(
        _run_cli(spec, [*base_args, "run"], env=shell_env)
    )
    file_wins = _json_output(
        _run_cli(
            spec,
            [*base_args, "--env-file-overrides-os-environ", "run"],
            env=shell_env,
        )
    )
    if shell_wins["label"] != "shell" or file_wins["label"] != "explicit-file":
        raise RuntimeError(
            "Explicit dotenv value precedence was not respected."
        )
    if shell_wins["workspace_root"] != str(root / "workspace") or file_wins[
        "workspace_root"
    ] != str(root / "explicit-workspace"):
        raise RuntimeError(
            "Explicit dotenv workspace precedence was not respected."
        )
    return {
        "example": spec.name,
        "shell_wins": {
            "workspace_root": shell_wins["workspace_root"],
            "label": shell_wins["label"],
        },
        "explicit_file_wins": {
            "workspace_root": file_wins["workspace_root"],
            "label": file_wins["label"],
        },
        "cleaned": _clean_managed(spec, root, env),
    }


def run_all() -> list[dict[str, object]]:
    """Run every installed example in a disposable directory."""
    with tempfile.TemporaryDirectory(prefix="apprc-example-smoke-") as temp:
        root = Path(temp)
        return [
            _smoke_precedence(spec, root / spec.name)
            if spec.name == "explicit-env-precedence"
            else _smoke_standard(spec, root / spec.name)
            for spec in EXAMPLE_APPS
        ]


def main() -> None:
    """Execute all CLI smoke scenarios and print their JSON summary."""
    print(json.dumps(run_all(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
