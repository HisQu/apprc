"""Probe the target's real package with no bundled AppRC ahead of its imports.

This file is executed by absolute path using the target interpreter with -I.
The metadata-only branch is stdlib-only, including for Buildben itself.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _direct_url(distribution: importlib.metadata.Distribution) -> object:
    raw = distribution.read_text("direct_url.json")
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Installed direct_url.json is not an object.")
    url = value.get("url")
    if isinstance(url, str):
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None:
            hostname = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port is not None else ""
            value["url"] = urlunsplit(
                (parsed.scheme, hostname + port, parsed.path, "", "")
            )
    return value


def _record_digest(
    distribution: importlib.metadata.Distribution,
) -> str | None:
    """Hash the exact bytes of one installed dist-info RECORD file."""
    files = distribution.files
    if files is None:
        return None
    records = [
        file
        for file in files
        if file.name == "RECORD" and file.parent.name.endswith(".dist-info")
    ]
    if len(records) != 1:
        return None
    try:
        with Path(str(distribution.locate_file(records[0]))).open("rb") as stream:
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def main() -> int:
    """Emit observed metadata and optionally initialize explicitly pending paths.

    :return: Zero only after the package/declaration/operation checks succeed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--import-package", required=True)
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--apprc-reference")
    parser.add_argument("--operation-context", type=Path)
    args = parser.parse_args()
    distribution = importlib.metadata.distribution(args.distribution)
    record_digest = _record_digest(distribution)
    console = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    if any(command not in console for command in args.command):
        raise ValueError(
            "Installed distribution does not own every declared console command."
        )
    result: dict[str, object] = {
        "distribution": distribution.metadata["Name"],
        "version": distribution.version,
        "prefix": sys.prefix,
        "interpreter": sys.executable,
        "commands": {command: console[command] for command in args.command},
        "direct_url": _direct_url(distribution),
        "capabilities": {
            "config": False,
            "appdata": False,
            "cache": False,
            "state": False,
        },
        "initialized": [],
        "distribution_record_digest": record_digest,
    }
    if args.apprc_reference:
        module_name, separator, attribute = args.apprc_reference.partition(":")
        if (
            not separator
            or not all(part.isidentifier() for part in module_name.split("."))
            or not attribute.isidentifier()
        ):
            raise ValueError(
                "AppRC reference must be an explicit module:object."
            )
        with contextlib.redirect_stdout(sys.stderr):
            from apprc import AppRC
            from apprc.services.installation import InstallationManager
            from apprc.user_files.installation.codec import (
                decode_operation_context,
            )

            application = vars(importlib.import_module(module_name))[attribute]
            if (
                not isinstance(application, AppRC)
                or application.schema.app_id != args.app_id
            ):
                raise ValueError(
                    "Installed AppRC declaration does not match the host identity."
                )
            capabilities = application.schema.paths
            result["capabilities"] = {
                "config": capabilities.config,
                "appdata": capabilities.appdata,
                "cache": capabilities.cache,
                "state": capabilities.state,
            }
            if args.operation_context is not None:
                context = decode_operation_context(
                    args.operation_context.read_bytes()
                )
                manager = InstallationManager(
                    application.schema,
                    environment=dict(os.environ),
                    directory=context.directory,
                )
                initialized = manager.initialize(context=context)
                result["initialized"] = [
                    str(path) for path in initialized.paths
                ]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
