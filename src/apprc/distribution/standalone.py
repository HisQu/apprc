"""Serialize an explicit ordinary-file closure, never transformed Python source."""

from __future__ import annotations

import io
import json
from importlib.resources import files
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from apprc.distribution.models import DistributionSpec, PayloadTree
from apprc.user_files.app_home.locations import assert_no_links

STANDALONE_MODULES = (
    "definition/paths.py",
    "definition/installation.py",
    "user_files/app_home/locations.py",
    "user_files/app_home/permissions.py",
    "user_files/app_home/writes.py",
    "user_files/app_home/ownership.py",
    "user_files/env_files/secrets.py",
    "user_files/installation/codec.py",
    "user_files/installation/discovery.py",
    "user_files/installation/coordination.py",
    "user_files/installation/validation.py",
    "user_files/installation/planning.py",
    "user_files/installation/operations.py",
    "user_files/installation/migration.py",
    "distribution/models.py",
    "distribution/runtime/__init__.py",
    "distribution/runtime/installed_probe.py",
    "distribution/runtime/backend.py",
    "distribution/runtime/probe.py",
    "distribution/runtime/acquisition.py",
    "distribution/runtime/installation.py",
    "distribution/runtime/controllers.py",
    "distribution/runtime/inspection.py",
    "distribution/runtime/legacy.py",
    "distribution/runtime/removal.py",
)

MANAGEMENT_REQUIREMENTS = (
    "platformdirs==4.10.0",
    "filelock==3.32.7",
    "pywin32==312; sys_platform == 'win32'",
)


def bundle_config(spec: DistributionSpec) -> bytes:
    """Serialize portable author choices, excluding author roots and values.

    :param spec: Explicit author composition and source identity.
    :return: Deterministic JSON available to the bundled lifecycle payload.
    """
    identity = spec.metadata.identity
    capabilities = spec.capabilities
    value = {
        "app_id": identity.app_id,
        "distribution": identity.distribution,
        "import_package": identity.import_package,
        "apprc_reference": identity.apprc_reference,
        "commands": identity.commands,
        "version": spec.metadata.version,
        "python_requirement": spec.metadata.python_requirement,
        "project_path": str(spec.metadata.project_path),
        "distribution_path": str(spec.metadata.distribution_path),
        "launcher_command": spec.metadata.launcher_command,
        "paths": {
            "config": capabilities.paths.config,
            "appdata": capabilities.paths.appdata,
            "cache": capabilities.paths.cache,
            "state": capabilities.paths.state,
        },
        "user_dotenv": capabilities.user_dotenv,
        "workspaces": capabilities.workspaces,
        "workspace_registry": capabilities.workspace_registry,
        "source_mode": spec.source_mode,
        "repository_url": spec.repository_url,
        "release_version": spec.release_version,
        "release_commit": spec.release_commit,
        "release_asset": spec.release_asset,
        "release_digest": spec.release_digest,
        "runtime_requirements": spec.runtime_requirements,
        "runtime_overrides": spec.runtime_overrides,
    }
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def payload_archive(spec: DistributionSpec, payload: PayloadTree) -> bytes:
    """Build a deterministic ZIP of complete modules and explicitly owned resources.

    :param spec: Portable generation inputs.
    :param payload: Exact repository-owned composition tree.
    :return: Embedded archive; no imports from the author application are executed.
    """
    entries: dict[str, bytes] = {}
    package = files("apprc")
    for module in STANDALONE_MODULES:
        entries[f"apprc/{module}"] = package.joinpath(module).read_bytes()
    source_root = payload.root.resolve()
    for relative in (*payload.modules, *payload.resources):
        target = source_root.joinpath(*relative.parts)
        assert_no_links(target)
        if not target.is_file():
            raise ValueError(f"Payload file is missing: {relative}.")
        destination = str(relative)
        if destination in entries or destination.startswith("apprc/"):
            raise ValueError(
                f"Payload collides with shared runtime: {relative}."
            )
        entries[destination] = target.read_bytes()
    entries["apprc/distribution/runtime/bundle.json"] = bundle_config(spec)
    for address in tuple(entries):
        parent = PurePosixPath(address).parent
        while parent.parts:
            entries.setdefault(
                str(parent / "__init__.py"),
                b'"""Bundled lifecycle namespace."""\n',
            )
            parent = parent.parent
    buffer = io.BytesIO()
    with ZipFile(
        buffer, "w", compression=ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for address, content in sorted(entries.items()):
            info = ZipInfo(address, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def inspection_archive() -> bytes:
    """Bundle only stdlib-importable schema and read-only discovery modules."""
    entries: dict[str, bytes] = {}
    package = files("apprc")
    for module in (
        "definition/paths.py",
        "definition/installation.py",
        "user_files/installation/codec.py",
        "user_files/installation/discovery.py",
        "distribution/runtime/inspection.py",
    ):
        entries[f"apprc/{module}"] = package.joinpath(module).read_bytes()
    for address in tuple(entries):
        parent = PurePosixPath(address).parent
        while parent.parts:
            entries.setdefault(
                str(parent / "__init__.py"),
                b'"""Bundled read-only namespace."""\n',
            )
            parent = parent.parent
    buffer = io.BytesIO()
    with ZipFile(
        buffer, "w", compression=ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for address, content in sorted(entries.items()):
            info = ZipInfo(address, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()
