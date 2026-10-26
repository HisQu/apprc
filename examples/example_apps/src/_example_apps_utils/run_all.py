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
    if spec.uses_user_dotenv or spec.uses_storage:
        env[spec.apprc_dir_env_key] = str(root / "apprc")
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


def _setup_storage(
    spec: ExampleAppSpec,
    root: Path,
    env: Mapping[str, str],
) -> None:
    """Create and populate the default storage for one example."""
    _run_cli(
        spec,
        [
            "config",
            "setup",
            "--storage-root",
            str(root / "storage"),
            "--yes",
        ],
        env=env,
    )
    if spec.required_storage_key is not None:
        _run_cli(
            spec,
            [
                "--storage",
                "default",
                "config",
                "set",
                spec.required_storage_key,
                "smoke-secret",
                "--scope",
                "storage",
            ],
            env=env,
        )


def _clean_appdata(
    spec: ExampleAppSpec,
    root: Path,
    env: Mapping[str, str],
) -> bool:
    """Clean the temporary registry and verify removal and retention.

    :param spec: Example whose installed CLI owns the managed files.
    :param root: Temporary scenario directory containing AppRC data.
    :param env: Isolated process environment for the example.
    :return: Whether cleanup respected its inventory and retained payloads.
    """
    appdata_directory = root / "apprc"
    paths = _json_output(
        _run_cli(
            spec,
            [
                "appdata",
                "paths",
                "--apprc-dir",
                str(appdata_directory),
                "--json",
            ],
            env=env,
        )
    )
    if paths["apprc_dir"] != str(appdata_directory):
        raise RuntimeError("appdata paths selected an unexpected AppRC directory.")
    managed_files = [Path(value) for value in paths["managed_files"]]
    internal_roots = [Path(value) for value in paths["internal_storage_roots"]]
    external_roots = [Path(value) for value in paths["external_storage_roots"]]
    unmanaged = appdata_directory / "runner-unmanaged.txt"
    unmanaged.parent.mkdir(parents=True, exist_ok=True)
    unmanaged.write_text("keep", encoding="utf-8")
    external_payloads = [root / "runner-payload.txt" for root in external_roots]
    for payload in external_payloads:
        payload.write_text("keep", encoding="utf-8")
    _run_cli(
        spec,
        [
            "appdata",
            "clean",
            "--apprc-dir",
            str(appdata_directory),
            "--yes",
        ],
        env=env,
    )
    cleaned = (
        all(not path.exists() for path in managed_files)
        and all(not path.exists() for path in internal_roots)
        and unmanaged.read_text(encoding="utf-8") == "keep"
        and all(
            path.read_text(encoding="utf-8") == "keep"
            for path in external_payloads
        )
    )
    if not cleaned:
        raise RuntimeError("appdata clean did not respect its cleanup inventory.")
    return cleaned


def _smoke_standard(spec: ExampleAppSpec, root: Path) -> dict[str, object]:
    """Run setup, diagnostics, runtime, and appdata cleanup for one example."""
    env = _example_environment(spec, root)
    if spec.uses_storage:
        _setup_storage(spec, root, env)
        runtime_prefix = ["--storage", "default"]
    elif spec.uses_user_dotenv:
        _run_cli(spec, ["config", "setup", "--yes"], env=env)
        runtime_prefix = []
    else:
        runtime_prefix = []
    doctor = _json_output(
        _run_cli(spec, [*runtime_prefix, "config", "doctor", "--json"], env=env)
    )
    run_args = [*runtime_prefix]
    if spec.name == "cli-runtime":
        run_args.extend(
            [
                "--workspace",
                str(root / "workspace"),
                "--model",
                "smoke",
                "--dry-run",
            ]
        )
    run_payload = _json_output(_run_cli(spec, [*run_args, "run"], env=env))
    cleaned = _clean_appdata(spec, root, env)
    return {
        "example": spec.name,
        "doctor_status": doctor["status"],
        "app_id": run_payload["app_id"],
        "cleaned": cleaned,
    }


def _smoke_precedence(spec: ExampleAppSpec, root: Path) -> dict[str, object]:
    """Prove both sides of explicit dotenv precedence with distinct values."""
    env = _example_environment(spec, root)
    _setup_storage(spec, root, env)
    explicit_root = root / "explicit-storage"
    _run_cli(
        spec,
        ["config", "storage", "add", "explicit", str(explicit_root), "--yes"],
        env=env,
    )
    for name, label in (
        ("default", "storage-default"),
        ("explicit", "storage-explicit"),
    ):
        _run_cli(
            spec,
            [
                "--storage",
                name,
                "config",
                "set",
                "label",
                label,
                "--scope",
                "storage",
            ],
            env=env,
        )
    explicit_env = root / "explicit.env"
    explicit_env.write_text(
        "APPRC_EXAMPLE_PRECEDENCE_STORAGE=explicit\n"
        "APPRC_EXAMPLE_PRECEDENCE_LABEL=explicit-file\n",
        encoding="utf-8",
    )
    shell_env = dict(env)
    shell_env["APPRC_EXAMPLE_PRECEDENCE_STORAGE"] = "default"
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
    cleaned = _clean_appdata(spec, root, env)
    return {
        "example": spec.name,
        "shell_wins": {
            "storage_root": shell_wins["storage_root"],
            "label": shell_wins["label"],
        },
        "explicit_file_wins": {
            "storage_root": file_wins["storage_root"],
            "label": file_wins["label"],
        },
        "cleaned": cleaned,
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
