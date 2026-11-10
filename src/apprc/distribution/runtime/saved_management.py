#!/usr/bin/env python3
"""Launch or uninstall from explicitly owned saved code and binding data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys before any binding can be trusted."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ManagementBinding:
    """Portable identity and an optional, independently validated host binding."""

    app_id: str
    command: str
    base_python: str | None = None

    def encode(self) -> bytes:
        """Serialize the exact portable or host-bound support-data schema."""
        return (json.dumps(asdict(self), sort_keys=True) + "\n").encode("utf-8")


def decode_management_binding(content: bytes) -> ManagementBinding:
    """Decode strict binding data shared by SDK publication and saved execution.

    :param content: Portable or host-bound management.json bytes.
    :return: Validated identity and optional absolute interpreter path.
    """
    value = json.loads(content, object_pairs_hook=_object)
    if not isinstance(value, dict) or set(value) != {
        "app_id",
        "command",
        "base_python",
    }:
        raise ValueError(
            "Management data requires app_id, command and base_python only."
        )
    app_id, command, python = (
        value["app_id"],
        value["command"],
        value["base_python"],
    )
    if (
        not isinstance(app_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None
    ):
        raise ValueError("Invalid management application identity.")
    if (
        not isinstance(command, str)
        or not command
        or any(character in command for character in ("/", "\\", "\x00"))
    ):
        raise ValueError("Invalid management command identity.")
    if python is not None and (
        not isinstance(python, str) or not Path(python).is_absolute()
    ):
        raise ValueError(
            "Management base_python must be null or an absolute path."
        )
    return ManagementBinding(app_id, command, python)


def _regular_bytes(path: Path) -> bytes:
    """Read only regular files reached without links or Windows reparse points."""
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0):
            raise ValueError(f"Saved support path contains a link: {parent}.")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Saved support is not a regular file: {path}.")
    return path.read_bytes()


def _installation_directory(app_id: str) -> Path:
    """Locate native authority from portable identity without creating state."""
    home = Path(
        os.environ.get("USERPROFILE" if os.name == "nt" else "HOME")
        or Path.home()
    )
    if not home.is_absolute():
        raise ValueError("Native home path must be absolute.")
    if os.name == "nt":
        data = Path(
            os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"
        )
    elif sys.platform == "darwin":
        data = home / "Library" / "Application Support"
    else:
        data = Path(
            os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"
        )
        if not data.is_absolute():
            data = home / ".local" / "share"
    if not data.is_absolute():
        raise ValueError("Native data path must be absolute.")
    return data / app_id / "installation"


def _owned_bytes(directory: Path, target: dict[str, Any], name: str) -> bytes:
    """Require the exact support path and digest from installation authority."""
    outputs = target.get("owned_outputs")
    matches = (
        [
            item.get("digest")
            for item in outputs
            if isinstance(item, dict)
            and item.get("kind") == "support"
            and item.get("path") == name
        ]
        if isinstance(outputs, list)
        else []
    )
    content = _regular_bytes(directory / name)
    if (
        len(matches) != 1
        or not isinstance(matches[0], str)
        or (hashlib.sha256(content).hexdigest() != matches[0])
    ):
        raise ValueError(f"Saved {name} differs from recorded support.")
    return content


def _authority(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, Any], ManagementBinding]:
    """Authorize canonical code and metadata before reading host bindings."""
    record = json.loads(
        _regular_bytes(directory / "installation.json"),
        object_pairs_hook=_object,
    )
    if (
        not isinstance(record, dict)
        or type(record.get("schema_version")) is not int
        or record["schema_version"] != 2
    ):
        raise ValueError("Saved installation authority requires schema 2.")
    target = record.get("current") or record.get("last_successful")
    if not isinstance(target, dict):
        raise ValueError("Saved installation snapshot is unavailable.")
    _owned_bytes(directory, target, "management.py")
    binding = decode_management_binding(
        _owned_bytes(directory, target, "management.json")
    )
    identity = target.get("identity")
    if not isinstance(identity, dict) or (
        record.get("app_id") != binding.app_id
        or identity.get("app_id") != binding.app_id
        or not isinstance(identity.get("commands"), list)
        or binding.command not in identity["commands"]
        or binding.base_python is None
    ):
        raise ValueError(
            "Saved management data does not match installation authority."
        )
    return record, target, binding


def _base_python(binding: ManagementBinding, target: dict[str, Any]) -> Path:
    """Live-validate the authorized interpreter independently of the app target."""
    if binding.base_python is None:
        raise ValueError("Saved base Python is unavailable.")
    executable = Path(binding.base_python)
    prefix_value = target.get("prefix")
    if (
        not isinstance(prefix_value, str)
        or not Path(prefix_value).is_absolute()
    ):
        raise ValueError("Saved application prefix is unavailable.")
    lexical_target = Path(os.path.normpath(prefix_value))
    roots = (lexical_target, lexical_target.resolve())
    if not executable.is_file() or any(
        path.is_relative_to(root)
        for path in (executable, executable.resolve())
        for root in roots
    ):
        raise ValueError("An external base Python interpreter is required.")
    result = subprocess.run(
        [
            str(executable),
            "-I",
            "-c",
            "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    prefix, base = json.loads(result.stdout)
    if not isinstance(prefix, str) or not isinstance(base, str):
        raise ValueError("Saved Python returned invalid interpreter identity.")
    live = Path(prefix).resolve()
    if (
        not Path(prefix).is_absolute()
        or live != Path(base).resolve()
        or any(live.is_relative_to(root) for root in roots)
    ):
        raise ValueError("Saved Python is not an independent base interpreter.")
    return executable


def _inspection(
    directory: Path, target: dict[str, Any], app_id: str
) -> dict[str, Any]:
    """Use the existing minimal saved inspector, never uv or provisioning."""
    _owned_bytes(directory, target, "inspection.py")
    result = subprocess.run(
        [
            sys.executable,
            str(directory / "inspection.py"),
            "--directory",
            str(directory),
            "--app-id",
            app_id,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    inspection = json.loads(result.stdout)
    if (
        not isinstance(inspection, dict)
        or not isinstance(inspection.get("record"), dict)
        or inspection.get("status") == "invalid"
    ):
        raise ValueError(
            "Saved installation inspection rejected its authority."
        )
    return inspection


def main() -> int:
    """Dispatch an explicit action; saved metadata never replaces authority."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launch", "uninstall"))
    action, remaining = parser.parse_known_args()
    options = argparse.ArgumentParser()
    options.add_argument("--directory", type=Path)
    if action.action == "uninstall":
        options.add_argument("--dry-run", action="store_true")
    args, forwarded = options.parse_known_args(remaining)
    try:
        local = Path(__file__).absolute()
        portable = decode_management_binding(
            _regular_bytes(local.with_name("management.json"))
        )
        directory = args.directory or _installation_directory(portable.app_id)
        if not directory.is_absolute():
            raise ValueError("Saved installation directory must be absolute.")
        record, target, binding = _authority(directory)
        if (
            portable.app_id != binding.app_id
            or portable.command != binding.command
        ):
            raise ValueError(
                "Checkout management identity differs from saved authority."
            )
        if local != directory / "management.py":
            dispatch = [
                sys.executable,
                str(directory / "management.py"),
                action.action,
                "--directory",
                str(directory),
            ]
            if action.action == "uninstall" and args.dry_run:
                dispatch.append("--dry-run")
            return subprocess.run(
                [*dispatch, *forwarded], check=False
            ).returncode
        inspection = _inspection(directory, target, binding.app_id)
        if action.action == "launch":
            if (
                record.get("status") != "ready"
                or record.get("operation") is not None
            ):
                raise ValueError(
                    "Application is not installed; repair the installation."
                )
            commands = target.get("commands")
            identities = target["identity"]["commands"]
            if not isinstance(commands, list) or len(commands) != len(
                identities
            ):
                raise ValueError("Recorded application command is unavailable.")
            executable_value = commands[identities.index(binding.command)]
            if not isinstance(executable_value, str):
                raise ValueError("Recorded application command is invalid.")
            executable = Path(executable_value)
            if not executable.is_absolute() or not executable.is_file():
                raise ValueError(
                    "Recorded application command is missing; repair the installation."
                )
            return subprocess.run(
                [str(executable), *forwarded], check=False
            ).returncode
        if args.dry_run:
            print(json.dumps(inspection, ensure_ascii=False, sort_keys=True))
            return 0
        operation = record.get("operation")
        if record.get("status") not in {"ready", "removed-retained"} and not (
            record.get("status") == "incomplete"
            and isinstance(operation, dict)
            and operation.get("kind") == "uninstall"
        ):
            raise ValueError(
                "Saved installation requires repair before uninstall."
            )
        backend = target.get("backend")
        if not isinstance(backend, dict):
            raise ValueError("Saved uv backend identity is unavailable.")
        paths = [
            backend.get(key) for key in ("executable", "tool_dir", "bin_dir")
        ]
        if any(
            not isinstance(value, str) or not Path(value).is_absolute()
            for value in paths
        ):
            raise ValueError("Saved uv backend paths must be absolute.")
        uv = Path(backend["executable"])
        if not uv.is_file():
            raise ValueError("Recorded uv executable is unavailable.")
        _owned_bytes(directory, target, "app-uninstall.py")
        python = _base_python(binding, target)
        environment = dict(os.environ)
        environment["UV_TOOL_DIR"] = backend["tool_dir"]
        environment["UV_TOOL_BIN_DIR"] = backend["bin_dir"]
        return subprocess.run(
            [
                str(uv),
                "run",
                "--no-config",
                "--no-project",
                "--python",
                str(python),
                "--script",
                str(directory / "app-uninstall.py"),
                "--directory",
                str(directory),
                *forwarded,
            ],
            env=environment,
            check=False,
        ).returncode
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Saved management failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
