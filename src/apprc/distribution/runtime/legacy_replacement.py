"""Explicit verified-source replacement for provenance-incomplete legacy installs.

The historical probe below establishes only the installed package facts the
old receipt cannot prove: backend address, package/version, console inventory,
and RECORD bytes. It deliberately does not turn an arbitrary historical origin
into a normal ``InstalledSnapshot``. A fresh replacement is then installed and
validated by the ordinary strict probe before legacy controllers are retired.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, replace
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Mapping
from uuid import UUID, uuid4

from apprc.definition.installation import (
    CleanupInventory,
    InstallationDiagnostic,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationMigration,
    InstallationOperation,
    InstallationPlacement,
    InstallationRecord,
    InstallationSource,
    InstallationTarget,
    InstallPlan,
    InstalledSnapshot,
    InventoryEntry,
    LegacyMigrationEvidence,
    MigrationInventory,
    OperationContext,
    OperationStep,
    OwnedOutput,
    StagedSupportOutput,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    _assert_private_staging,
    _materialize_archive,
    prepare_source,
)
from apprc.distribution.runtime.backend import (
    backend_environment,
    external_base_python,
    inspect_uv_tools,
    install_uv_tool,
    tool_interpreter,
)
from apprc.distribution.runtime.installation import (
    _validate_prepared_source,
    bind_install_support,
)
from apprc.distribution.runtime.legacy import (
    LegacyReceiptInspection,
    inspect_legacy_receipt,
)
from apprc.distribution.runtime.probe import (
    _validate_command_ownership,
    probe_installed_tool,
)
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.installation.codec import encode_operation_context
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.migration import resume_migration
from apprc.user_files.installation.planning import validate_placement
from apprc.user_files.installation.operations import (
    SUPPORT_VERSION,
    _pending,
    fail_operation,
    record_step,
)


@dataclass(frozen=True, slots=True)
class LegacyReplacementPlan:
    """Revision-bound authority for replacing one validated legacy tool.

    :param install: Captured replacement target and installation namespace.
    :param legacy: Strict legacy receipt inspection, not source-origin proof.
    :param evidence: Immutable receipt and exact old runnable revisions.
    :param record_entry: Actual installed RECORD file and its observed revision.
    :param inventory: Explicit payload mapping; this capability permits only an
        empty mapping so user resources and workspaces remain untouched.
    :param expected_record_digest: Independently supplied historical RECORD hash.
    :param quiescent: Explicit confirmation that old consumers are stopped.
    """

    install: InstallPlan
    legacy: LegacyReceiptInspection
    evidence: LegacyMigrationEvidence
    record_entry: InventoryEntry
    inventory: MigrationInventory
    expected_record_digest: str
    quiescent: bool


def _normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _immutable_replacement_source(source: InstallationSource) -> bool:
    return source.kind in {"release-sdist", "wheel"} or (
        source.kind == "index"
        and re.fullmatch(
            r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
            source.requirement,
        )
        is not None
    )


def _python_requirement_matches(version: str, requirement: str) -> bool:
    """Check a complete interpreter version with standard PEP 440 semantics.

    :param version: Full reported interpreter version, including prerelease.
    :param requirement: Declared project Python requirement.
    :return: Whether the interpreter satisfies the requirement.
    """
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError as error:
        raise InstallationError(
            "Python compatibility checks require the optional distribution "
            "extra (packaging)."
        ) from error
    try:
        specifiers = SpecifierSet(requirement)
        interpreter = Version(version)
    except (TypeError, ValueError) as error:
        raise InstallationError(
            "Cannot verify the saved base Python against this requirement."
        ) from error
    return specifiers.contains(interpreter)


def is_pending_legacy_replacement(
    inspection: InstallationInspection,
) -> bool:
    """Identify the recorded pre-migration legacy replacement phase.

    :param inspection: Read-only durable installation observation.
    :return: Whether retained legacy proof routes this replacement to resume.
    """
    record = inspection.record
    if (
        record is None
        or record.status != "incomplete"
        or record.operation is None
        or record.operation.kind != "replace"
        or record.migration is not None
    ):
        return False
    retained_names = {
        item.path.name for item in record.operation.inventory.retained
    }
    return bool(
        retained_names
        & {
            "receipt.json",
            "lifecycle.py",
            "uninstall.sh",
            "uninstall.cmd",
            "uninstall.ps1",
            "prepare-powershell-windows.cmd",
        }
    )


def _recorded_base_python(
    plan: LegacyReplacementPlan, python_requirement: str
) -> Path:
    """Validate and return the receipt's exact external base interpreter."""
    backend = plan.install.target.backend
    base_python = external_base_python(
        backend.tool_dir / plan.install.target.identity.distribution,
        executable=plan.evidence.python,
    )
    result = subprocess.run(
        [
            str(base_python),
            "-I",
            "-c",
            "import json,sys; print(json.dumps([sys.version_info.major, "
            "sys.version_info.minor, sys.version_info.micro, "
            "sys.version_info.releaselevel, sys.version_info.serial]))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        version_data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstallationError(
            "Recorded base Python returned invalid version metadata."
        ) from error
    if (
        not isinstance(version_data, list)
        or len(version_data) != 5
        or any(type(item) is not int for item in version_data[:3])
        or version_data[3] not in {"alpha", "beta", "candidate", "final"}
        or type(version_data[4]) is not int
        or version_data[4] < 0
    ):
        raise InstallationError(
            "Recorded base Python version metadata is unsupported."
        )
    major, minor, micro, releaselevel, serial = version_data
    suffix = {
        "alpha": f"a{serial}",
        "beta": f"b{serial}",
        "candidate": f"rc{serial}",
        "final": "",
    }[releaselevel]
    version = f"{major}.{minor}.{micro}{suffix}"
    if not _python_requirement_matches(version, python_requirement):
        raise InstallationError(
            "Recorded base Python does not satisfy the declared requirement."
        )
    return base_python


def _validate_replacement_plan(
    plan: LegacyReplacementPlan, *, verify_record: bool
) -> None:
    install = plan.install
    evidence = plan.evidence
    identity = install.target.identity
    if (
        install.kind != "replace"
        or install.expected_generation not in {None, install.generation_id}
        or not _immutable_replacement_source(install.target.source)
        or (
            install.target.source.kind in {"release-sdist", "wheel"}
            and (
                not install.target.source.version
                or re.fullmatch(
                    r"[0-9a-f]{64}", install.target.source.digest or ""
                )
                is None
            )
        )
        or plan.inventory.entries
        or plan.inventory.destinations
        or plan.inventory.unknown
        or plan.inventory.source_root != install.directory
        or plan.inventory.destination_root != install.directory
        or evidence.distribution != identity.distribution
        or evidence.command not in identity.commands
        or evidence.backend != install.target.backend
        or plan.legacy.migration_evidence() != evidence
        or re.fullmatch(r"[0-9a-f]{64}", plan.expected_record_digest) is None
        or plan.record_entry.revision != plan.expected_record_digest
        or not plan.record_entry.path.is_absolute()
        or not plan.record_entry.path.is_relative_to(
            install.target.backend.tool_dir
        )
    ):
        raise InstallationError("Legacy replacement plan is invalid or unsafe.")
    validate_placement(install.target.placement, directory=install.directory)
    if verify_record:
        assert_no_links(plan.record_entry.path)
        if file_revision(plan.record_entry.path) != plan.expected_record_digest:
            raise InstallationError(
                "Historical installed RECORD changed after planning."
            )


def _observe_historical_installation(
    identity: InstallationIdentity,
    legacy: LegacyReceiptInspection,
    *,
    record_entry: InventoryEntry | None,
    expected_record_digest: str,
    environment: Mapping[str, str],
) -> Path:
    """Observe exact old metadata using the recorded backend and isolated Python.

    :param identity: Recorded application distribution and command identity.
    :param legacy: Validated old receipt observation.
    :param record_entry: Planned exact RECORD, or ``None`` while planning.
    :param expected_record_digest: Independent old RECORD fingerprint.
    :param environment: Captured invocation environment.
    :return: The exact RECORD path reported by the target interpreter.
    """
    backend = legacy.backend
    if backend is None:
        raise InstallationError("Legacy receipt has no validated backend.")
    interpreter = tool_interpreter(backend, identity.distribution)
    code = (
        "import importlib.metadata,json,pathlib,re,sys; "
        "norm=lambda s:re.sub(r'[-_.]+','-',s).lower(); "
        "dists=[d for d in importlib.metadata.distributions() "
        "if isinstance(d.metadata.get('Name'),str) and "
        "norm(d.metadata['Name'])==norm(sys.argv[1])]; "
        "matches=[{'name':d.metadata['Name'],'version':d.version,"
        "'commands':{e.name:e.value for e in d.entry_points "
        "if e.group=='console_scripts'},'records':[str(d.locate_file(f)) "
        "for f in (d.files or ()) if f.name=='RECORD' and "
        "f.parent.name.endswith('.dist-info')]} for d in dists "
        "if pathlib.Path(d.locate_file('')).is_relative_to("
        "pathlib.Path(sys.prefix))]; "
        "print(json.dumps({'prefix':sys.prefix,'interpreter':sys.executable,"
        "'matches':matches}))"
    )
    result = subprocess.run(
        [str(interpreter), "-I", "-c", code, identity.distribution],
        env=backend_environment(backend, environment),
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstallationError(
            "Historical installed metadata probe returned invalid JSON."
        ) from error
    expected_prefix = backend.tool_dir / identity.distribution

    matches = value.get("matches") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"prefix", "interpreter", "matches"}
        or value["prefix"] != str(expected_prefix)
        or value["interpreter"] != str(interpreter)
        or not isinstance(matches, list)
        or len(matches) != 1
    ):
        raise InstallationError(
            "Historical installed distribution metadata is missing or ambiguous."
        )
    metadata = matches[0]
    commands = metadata.get("commands") if isinstance(metadata, dict) else None
    records = metadata.get("records") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or set(metadata) != {"name", "version", "commands", "records"}
        or not isinstance(metadata["name"], str)
        or _normalized(metadata["name"]) != _normalized(identity.distribution)
        or metadata["version"] != legacy.version
        or not isinstance(commands, dict)
        or set(commands) != set(identity.commands)
        or legacy.command not in commands
        or any(
            not isinstance(command, str) or not command
            for command in commands.values()
        )
        or not isinstance(records, list)
        or len(records) != 1
        or not isinstance(records[0], str)
    ):
        raise InstallationError(
            "Historical installed package does not match its receipt and declared command inventory."
        )
    for command in identity.commands:
        suffix = ".exe" if os.name == "nt" else ""
        entry = backend.bin_dir / (command + suffix)
        owned = (
            expected_prefix
            / ("Scripts" if os.name == "nt" else "bin")
            / (command + suffix)
        )

        _validate_command_ownership(entry, owned)
    record_path = Path(records[0])
    assert_no_links(record_path)
    if (
        not record_path.is_absolute()
        or not record_path.is_relative_to(expected_prefix)
        or file_revision(record_path) != expected_record_digest
        or (
            record_entry is not None
            and (
                record_path != record_entry.path
                or record_entry.revision != expected_record_digest
            )
        )
    ):
        raise InstallationError(
            "Historical installed RECORD differs from explicit expected evidence."
        )
    return record_path


def _validate_legacy_namespace(
    evidence: LegacyMigrationEvidence, directory: Path
) -> None:
    """Reject links and unrecognized children before any backend mutation."""
    root = evidence.receipt.path.parent
    if not root.exists():
        raise InstallationError("Legacy receipt namespace is missing.")
    assert_no_links(root)
    expected = {
        evidence.receipt.path,
        *(item.path for item in evidence.runnables),
        *(item.inert_path for item in evidence.runnables),
    }
    if root == directory:
        expected.update({directory / "installation.json", directory / "locks"})
        locks = directory / "locks"
        if locks.exists() or locks.is_symlink():
            assert_no_links(locks)
            if not locks.is_dir():
                raise InstallationError(
                    "Installation lock address is not a directory."
                )
            expected.update(locks.iterdir())
    unknown = tuple(path for path in root.iterdir() if path not in expected)
    if unknown:
        raise InstallationError(
            "Unknown legacy installation files require project-owned migration."
        )


def _validate_empty_authority_namespace(directory: Path) -> None:
    """Reject pre-existing target files while permitting the operation lock."""
    if not directory.exists():
        return
    assert_no_links(directory)
    allowed = {directory / "locks"}
    locks = directory / "locks"
    if locks.exists() or locks.is_symlink():
        assert_no_links(locks)
        if not locks.is_dir():
            raise InstallationError(
                "Installation lock address is not a directory."
            )
        allowed.update(locks.iterdir())
    if any(path not in allowed for path in directory.iterdir()):
        raise InstallationError(
            "Unknown target installation files require manual inspection."
        )


def plan_legacy_replacement(
    inspection: InstallationInspection,
    identity: InstallationIdentity,
    source: InstallationSource,
    placement: InstallationPlacement,
    *,
    legacy: LegacyReceiptInspection,
    inventory: MigrationInventory,
    expected_record_digest: str,
    quiescent: bool,
) -> LegacyReplacementPlan:
    """Plan explicit source replacement without asserting historical provenance.

    :param inspection: Fresh, read-only authority discovery.
    :param identity: Full application, distribution and command declaration.
    :param source: Explicit verified replacement acquisition source.
    :param placement: Explicit new installation placement.
    :param legacy: Validated old receipt inspection.
    :param inventory: Payload inventory, required to be empty to preserve all data.
    :param expected_record_digest: Independently acquired historical RECORD SHA-256.
    :param quiescent: Confirmation that all old consumers are stopped.
    :return: Revision-bound replacement plan.
    """
    if not quiescent:
        raise InstallationError("Stop legacy consumers before replacement.")
    if re.fullmatch(r"[0-9a-f]{64}", expected_record_digest) is None:
        raise InstallationError(
            "Expected legacy RECORD digest must be SHA-256."
        )
    record = inspection.require_usable()
    if record is not None or inspection.status != "missing":
        raise InstallationError(
            "Legacy replacement requires an empty AppRC authority namespace."
        )
    evidence = legacy.migration_evidence()
    if (
        evidence.distribution != identity.distribution
        or evidence.command not in identity.commands
        or evidence.backend is None
        or identity.app_id != inspection.app_id
    ):
        raise InstallationError(
            "Legacy receipt identity differs from the requested application."
        )
    if (
        inventory.entries
        or inventory.destinations
        or inventory.unknown
        or inventory.source_root != inspection.directory
        or inventory.destination_root != inspection.directory
    ):
        raise InstallationError(
            "Legacy replacement preserves payload roots; resource moves require a separate migration."
        )
    if not _immutable_replacement_source(source):
        raise InstallationError(
            "Legacy replacement requires an immutable, content-addressed source."
        )
    _validate_legacy_namespace(evidence, inspection.directory)
    if evidence.receipt.path.parent != inspection.directory:
        _validate_empty_authority_namespace(inspection.directory)
    if source.kind in {"release-sdist", "wheel"} and (
        not source.version
        or re.fullmatch(r"[0-9a-f]{64}", source.digest or "") is None
    ):
        raise InstallationError(
            "Immutable replacement version and asset digest are required."
        )
    validate_placement(placement, directory=inspection.directory)
    install = InstallPlan(
        inspection.directory,
        inspection.revision,
        None,
        InstallationTarget(identity, source, placement, evidence.backend),
        uuid4(),
        uuid4(),
        "replace",
    )
    record_path = _observe_historical_installation(
        identity,
        legacy,
        record_entry=None,
        expected_record_digest=expected_record_digest,
        environment=os.environ,
    )
    return LegacyReplacementPlan(
        install,
        legacy,
        evidence,
        InventoryEntry(record_path, "file", expected_record_digest),
        inventory,
        expected_record_digest,
        quiescent,
    )


def _validate_prepared_identity_and_version(
    plan: LegacyReplacementPlan, prepared: PreparedSource
) -> None:
    """Reject immutable package metadata that names another distribution or version."""
    expected_version = plan.install.target.source.version
    expected_name = _normalized(plan.install.target.identity.distribution)
    project = prepared.project_directory
    if project is not None:
        import tomllib

        try:
            with (project / "pyproject.toml").open("rb") as stream:
                metadata = tomllib.load(stream).get("project", {})
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise InstallationError(
                "Prepared replacement source has invalid project metadata."
            ) from error
        name = metadata.get("name")
        version = metadata.get("version")
    elif plan.install.target.source.kind == "wheel":
        try:
            with zipfile.ZipFile(prepared.requirement) as wheel:
                metadata_paths = [
                    name
                    for name in wheel.namelist()
                    if name.endswith(".dist-info/METADATA")
                ]
                if len(metadata_paths) != 1:
                    raise InstallationError(
                        "Prepared wheel has no unique distribution metadata."
                    )
                metadata = Parser().parsestr(
                    wheel.read(metadata_paths[0]).decode("utf-8")
                )
        except (OSError, UnicodeError, zipfile.BadZipFile) as error:
            raise InstallationError(
                "Prepared immutable wheel metadata is unreadable."
            ) from error
        name = metadata.get("Name")
        version = metadata.get("Version")
    else:
        return
    if not isinstance(name, str) or _normalized(name) != expected_name:
        raise InstallationError(
            "Prepared replacement distribution differs from the selected target."
        )
    if not isinstance(version, str) or not version:
        raise InstallationError(
            "Prepared replacement distribution has no valid version."
        )
    if expected_version is not None and version != expected_version:
        raise InstallationError(
            "Prepared immutable replacement version differs from the selected source."
        )


def _stored_record_entry(record: InstallationRecord) -> InventoryEntry:
    """Recover the exact independently observed RECORD from pending evidence."""
    operation = record.operation
    if operation is None:
        raise InstallationError("No legacy replacement is pending.")
    entries = tuple(
        item
        for item in operation.inventory.retained
        if item.path.name == "RECORD"
    )
    if len(entries) != 1 or entries[0].revision is None:
        raise InstallationError(
            "Pending legacy replacement has no unique RECORD evidence."
        )
    return entries[0]


def _pending_plan(
    directory: Path,
    record: InstallationRecord,
    *,
    operation_id: UUID,
    expected_revision: str,
    quiescent: bool,
) -> LegacyReplacementPlan:
    """Reconstruct only the recorded replacement target and legacy authority."""
    operation = record.operation
    migration = record.migration
    if (
        operation is None
        or operation.kind != "replace"
        or operation.operation_id != operation_id
        or operation.intended is None
        or migration is not None
        or not quiescent
    ):
        raise InstallationError("No matching legacy replacement is pending.")
    entries = operation.inventory.retained
    receipts = tuple(
        item for item in entries if item.path.name == "receipt.json"
    )
    if len(receipts) != 1:
        raise InstallationError(
            "Pending replacement lost its legacy receipt proof."
        )
    assert_no_links(receipts[0].path)
    raw = json.loads(receipts[0].path.read_text(encoding="utf-8"))
    command = raw.get("command") if isinstance(raw, dict) else None
    if not isinstance(command, str):
        raise InstallationError("Pending legacy receipt identity is invalid.")
    legacy = inspect_legacy_receipt(
        receipts[0].path,
        distribution=operation.intended.identity.distribution,
        command=command,
    )
    if not legacy.compatible or legacy.receipt != receipts[0]:
        raise InstallationError(
            "Pending legacy receipt changed after planning."
        )
    evidence = legacy.migration_evidence()
    record_entry = _stored_record_entry(record)
    legacy_paths = {
        evidence.receipt.path,
        *(item.path for item in evidence.runnables),
    }
    actual_legacy_files = {
        (item.path, item.revision)
        for item in entries
        if item.path in legacy_paths
    }
    expected_legacy_files = {
        (evidence.receipt.path, evidence.receipt.revision),
        *((item.path, item.revision) for item in evidence.runnables),
    }
    input_root = directory / "migration-staged" / str(record.generation_id)
    assert_no_links(input_root)
    expected_input_paths = {
        item.path for item in entries if item.path.parent == input_root
    }
    if input_root.exists():
        actual_input_paths = (
            set(input_root.iterdir()) if input_root.is_dir() else set()
        )
        missing_final_paths = {
            item.path
            for item in entries
            if item.path.parent == input_root
            and item.path.name.startswith("final-")
            and not item.path.exists()
        }
        if actual_input_paths != expected_input_paths - missing_final_paths:
            raise InstallationError(
                "Unknown content occupies pending replacement staging."
            )
    elif expected_input_paths - {
        item.path for item in entries if item.path.name.startswith("final-")
    }:
        raise InstallationError("Pending replacement staging is missing.")
    for item in entries:
        if item.path in legacy_paths or item.path == record_entry.path:
            continue
        if item.path.name in {"repair-installer.py", "legacy-recovery.py"}:
            if item.path.parent != directory:
                raise InstallationError(
                    "Pending recovery entry escaped the installation namespace."
                )
        elif item.path.parent != input_root or not item.path.name.startswith(
            ("support-", "acquisition-", "final-")
        ):
            raise InstallationError(
                "Pending recovery input escaped its operation-owned staging."
            )
        assert_no_links(item.path)
        if item.kind != "file" or item.revision is None:
            raise InstallationError("Pending recovery input changed.")
        revision = file_revision(item.path)
        if item.path.name.startswith("final-") and revision is None:
            continue
        if revision != item.revision:
            raise InstallationError("Pending recovery input changed.")
    if actual_legacy_files != expected_legacy_files:
        raise InstallationError(
            "Legacy runnable inventory changed after planning."
        )
    inventory = MigrationInventory(directory, directory)
    inspection = inspect_installation(directory, app_id=record.app_id)
    if (
        inspection.revision != expected_revision
        or inspection.record is None
        or inspection.record.generation_id != record.generation_id
    ):
        raise InstallationError("Legacy replacement authority changed.")
    install = InstallPlan(
        directory,
        expected_revision,
        record.generation_id,
        operation.intended,
        operation_id,
        record.generation_id,
        "replace",
    )
    plan = LegacyReplacementPlan(
        install,
        legacy,
        legacy.migration_evidence(),
        record_entry,
        inventory,
        record_entry.revision or "",
        quiescent,
    )
    _validate_replacement_plan(plan, verify_record=False)
    return plan


def _support_evidence(
    directory: Path,
    support_files: Mapping[PurePosixPath, bytes],
) -> dict[Path, str]:
    """Bind authored support paths to exact digests for same-entry recovery."""
    result: dict[Path, str] = {}
    for relative, content in support_files.items():
        if (
            not isinstance(relative, PurePosixPath)
            or not isinstance(content, bytes)
            or relative.is_absolute()
            or not relative.parts
            or str(relative) != relative.as_posix()
            or "\\" in str(relative)
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise InstallationError("Replacement support inventory is invalid.")
        result[directory.joinpath(*relative.parts)] = hashlib.sha256(
            content
        ).hexdigest()
    if not result:
        raise InstallationError("Replacement requires nonempty support files.")
    return result


def _load_pending_inputs(
    directory: Path,
    record: InstallationRecord,
) -> tuple[dict[PurePosixPath, bytes], Path, str]:
    """Read only digest-verified operation-owned support and acquisition bytes."""
    operation = record.operation
    if operation is None:
        raise InstallationError("No pending legacy replacement inputs exist.")
    input_root = directory / "migration-staged" / str(record.generation_id)
    support_files: dict[PurePosixPath, bytes] = {}
    archives: list[InventoryEntry] = []
    for item in operation.inventory.retained:
        if item.path in {
            directory / "repair-installer.py",
            directory / "legacy-recovery.py",
        }:
            continue
        if item.path.parent != input_root:
            continue
        if item.path.name.startswith("support-"):
            try:
                relative = PurePosixPath(
                    bytes.fromhex(
                        item.path.name.removeprefix("support-")
                    ).decode()
                )
            except (ValueError, UnicodeDecodeError) as error:
                raise InstallationError(
                    "Saved recovery support path is invalid."
                ) from error
            assert_no_links(item.path)
            content = item.path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item.revision:
                raise InstallationError(
                    "Saved authored recovery support changed."
                )
            support_files[relative] = content
        elif item.path.name.startswith("acquisition-"):
            archives.append(item)
    if len(archives) != 1:
        raise InstallationError(
            "Pending replacement has no unique saved acquisition archive."
        )
    archive_entry = archives[0]
    assert_no_links(archive_entry.path)
    digest = archive_entry.revision
    if digest is None or file_revision(archive_entry.path) != digest:
        raise InstallationError("Saved replacement acquisition changed.")
    if not support_files:
        raise InstallationError(
            "Pending replacement has no saved recovery support."
        )
    return support_files, archive_entry.path, digest


def _prepare_saved_source(
    source: InstallationSource,
    archive: Path,
    digest: str,
    staging: Path,
) -> PreparedSource:
    """Materialize retained acquisition bytes without changing intended identity."""
    if not archive.name.startswith(f"acquisition-{digest}-"):
        raise InstallationError("Saved acquisition address is invalid.")
    archive_name = archive.name.removeprefix(f"acquisition-{digest}-")
    if not archive_name:
        raise InstallationError("Saved acquisition filename is missing.")
    _assert_private_staging(staging)
    local_archive = staging / archive_name
    assert_no_links(local_archive)
    if local_archive.exists():
        raise InstallationError(
            "Recovery acquisition staging is already occupied."
        )
    shutil.copyfile(archive, local_archive)
    local_archive.chmod(0o600)
    if source.kind in {"release-sdist", "wheel"}:
        local = replace(source, requirement=str(local_archive))
        return replace(
            prepare_source(local, staging),
            source=source,
        )
    return _materialize_archive(source, local_archive, staging, digest)


def _write_initial_pending(
    plan: LegacyReplacementPlan,
    support_files: Mapping[PurePosixPath, bytes],
    prepared: PreparedSource,
) -> InstallationInspection:
    """Claim authored recovery bytes and acquisition before publishing them."""
    install = plan.install
    support = _support_evidence(install.directory, support_files)
    input_root = (
        install.directory / "migration-staged" / str(install.generation_id)
    )
    assert_no_links(input_root)
    if input_root.exists() and (
        not input_root.is_dir() or any(input_root.iterdir())
    ):
        raise InstallationError(
            "Unknown content occupies replacement recovery staging."
        )
    input_files = {
        input_root
        / f"support-{relative.as_posix().encode('utf-8').hex()}": content
        for relative, content in support_files.items()
    }
    if (
        prepared.archive is None
        or prepared.digest is None
        or not prepared.archive.is_file()
        or file_revision(prepared.archive) != prepared.digest
    ):
        raise InstallationError(
            "Replacement has no retained, digest-verified acquisition archive."
        )
    acquisition_path = (
        input_root / f"acquisition-{prepared.digest}-{prepared.archive.name}"
    )
    input_files[acquisition_path] = prepared.archive.read_bytes()
    recovery_entries = tuple(
        install.directory / name
        for name in ("repair-installer.py", "legacy-recovery.py")
        if PurePosixPath(name) in support_files
    )
    for recovery_entry in recovery_entries:
        input_files[recovery_entry] = support_files[
            PurePosixPath(recovery_entry.name)
        ]
    retained_inputs = tuple(
        InventoryEntry(path, "file", hashlib.sha256(content).hexdigest())
        for path, content in sorted(
            input_files.items(), key=lambda pair: str(pair[0])
        )
    )
    entries = tuple(
        InventoryEntry(path, "file", digest)
        for path, digest in sorted(
            support.items(), key=lambda item: str(item[0])
        )
    )
    legacy_files = tuple(
        InventoryEntry(item.path, "file", item.revision)
        for item in plan.evidence.runnables
    )
    retained = (
        *legacy_files,
        plan.evidence.receipt,
        plan.record_entry,
        *retained_inputs,
    )
    operation = InstallationOperation(
        install.operation_id,
        "replace",
        "pending",
        install.target,
        install.target.placement,
        inventory=CleanupInventory(entries=entries, retained=retained),
    )
    record = InstallationRecord(
        1,
        install.target.identity.app_id,
        install.generation_id,
        SUPPORT_VERSION,
        install.target.placement,
        "incomplete",
        operation=operation,
    )
    write_record(
        install.directory, record, expected_revision=install.expected_revision
    )
    for path, content in input_files.items():
        assert_no_links(path)
        if file_revision(path) is not None:
            raise InstallationError(
                f"Replacement recovery claim is already occupied: {path}."
            )
        create_private_directory_if_missing(path.parent)
        write_bytes_atomic(path, content, private=True)
    return inspect_installation(
        install.directory, app_id=install.target.identity.app_id
    )


def _make_operation_context(
    plan: LegacyReplacementPlan, directory: Path
) -> Path:
    context = OperationContext(
        plan.install.directory,
        plan.install.operation_id,
        plan.install.generation_id,
        plan.install.target.placement,
    )
    path = directory / "operation-context.json"
    path.write_bytes(encode_operation_context(context))
    return path


def _final_support_source(stage_root: Path, relative: PurePosixPath) -> Path:
    """Name a final staging source independently from retained input files."""
    digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()
    return stage_root / f"final-{digest}"


def _claim_final_support(
    checkpoint: InstallationInspection,
    files: Mapping[PurePosixPath, bytes],
) -> tuple[InstallationInspection, dict[PurePosixPath, Path]]:
    """Claim final staged bytes by CAS before publishing any of them."""
    directory = checkpoint.directory
    record = checkpoint.record
    revision = checkpoint.revision
    if record is None or record.operation is None or revision is None:
        raise InstallationError(
            "Replacement checkpoint lost operation authority."
        )
    stage_root = directory / "migration-staged" / str(record.generation_id)
    retained = record.operation.inventory.retained
    by_path: dict[Path, InventoryEntry] = {}
    for item in retained:
        if item.path in by_path:
            raise InstallationError(
                "Replacement retained inventory is ambiguous."
            )
        by_path[item.path] = item
    sources: dict[PurePosixPath, Path] = {}
    additions: list[InventoryEntry] = []
    for relative, content in files.items():
        source = _final_support_source(stage_root, relative)
        digest = hashlib.sha256(content).hexdigest()
        existing = by_path.get(source)
        assert_no_links(source)
        current_digest = file_revision(source)
        if existing is None:
            if current_digest is not None:
                raise InstallationError(
                    "Unclaimed final support staging is occupied."
                )
            additions.append(InventoryEntry(source, "file", digest))
        elif (
            existing.kind != "file"
            or existing.revision != digest
            or current_digest not in {None, digest}
        ):
            raise InstallationError(
                "Claimed final support differs from prepared output."
            )
        sources[relative] = source
    if additions:
        operation = record.operation
        updated = replace(
            record,
            operation=replace(
                operation,
                inventory=replace(
                    operation.inventory,
                    retained=(*operation.inventory.retained, *additions),
                ),
            ),
        )
        new_revision = write_record(
            directory, updated, expected_revision=revision
        )
        checkpoint = inspect_installation(directory, app_id=record.app_id)
        if (
            checkpoint.revision != new_revision
            or checkpoint.record is None
            or checkpoint.record.operation is None
            or checkpoint.record.operation.operation_id
            != operation.operation_id
        ):
            raise InstallationError(
                "Final support claims lost their CAS authority."
            )
    return checkpoint, sources


def _stage_final_support(
    plan: LegacyReplacementPlan,
    files: Mapping[PurePosixPath, bytes],
    raw_inputs: Mapping[Path, bytes],
    final_sources: Mapping[PurePosixPath, Path],
    *,
    retained_claims: Mapping[Path, str],
) -> tuple[StagedSupportOutput, ...]:
    """Stage claimed bound support and its verified recovery inputs."""
    outputs: list[StagedSupportOutput] = []
    for relative, content in sorted(
        files.items(), key=lambda pair: str(pair[0])
    ):
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise InstallationError(f"Invalid support output path: {relative}.")
        source = final_sources[relative]
        destination = plan.install.directory.joinpath(*relative.parts)
        assert_no_links(source)
        assert_no_links(destination)
        digest = hashlib.sha256(content).hexdigest()
        if retained_claims.get(source) != digest:
            raise InstallationError(
                "Final support staging lacks its digest claim."
            )
        revision = file_revision(source)
        if revision is not None and revision != digest:
            raise InstallationError(f"Final support staging changed: {source}.")
        destination_revision = file_revision(destination)
        if destination_revision is not None:
            legacy_revision = next(
                (
                    item.revision
                    for item in plan.evidence.runnables
                    if item.path == destination
                ),
                None,
            )
            if destination_revision not in {
                retained_claims.get(destination),
                legacy_revision,
            }:
                raise InstallationError(
                    f"Replacement support destination is not claimed: {destination}."
                )
        if revision is None and not (
            destination_revision == digest
            and retained_claims.get(destination) == digest
            and not any(
                item.path == destination for item in plan.evidence.runnables
            )
        ):
            create_private_directory_if_missing(source.parent)
            write_bytes_atomic(source, content, private=True)
        if relative.name in {"launch.sh", "uninstall.sh"} and file_revision(
            source
        ):
            source.chmod(0o700)
        outputs.append(StagedSupportOutput(source, destination, digest))
    for source, content in raw_inputs.items():
        digest = hashlib.sha256(content).hexdigest()
        if (
            retained_claims.get(source) != digest
            or file_revision(source) != digest
        ):
            raise InstallationError("Retained recovery input changed.")
        relative = PurePosixPath(source.name)
        if relative in files:
            raise InstallationError(
                "Retained input collides with final support."
            )
        destination = plan.install.directory / source.name
        assert_no_links(destination)
        if file_revision(destination) is not None:
            raise InstallationError(
                f"Retained input output destination is occupied: {destination}."
            )
        outputs.append(StagedSupportOutput(source, destination, digest))
    if not outputs:
        raise InstallationError("Replacement requires runnable support files.")
    return tuple(outputs)


def _verify_staged_recovery(
    plan: LegacyReplacementPlan,
    prepared: PreparedSource,
    *,
    environment: Mapping[str, str],
    probe_path: Path,
    base_python: Path,
    support_files: Mapping[PurePosixPath, bytes],
) -> InstallationInspection:
    """Install, strictly probe, then hand the exact state to migration recovery."""
    install = plan.install
    directory = install.directory
    operation_id = install.operation_id
    with installation_lock(directory):
        current = inspect_installation(
            directory, app_id=install.target.identity.app_id
        )
        record = current.record
        if (
            record is None
            or record.operation is None
            or record.operation.operation_id != operation_id
            or record.operation.kind != "replace"
            or record.generation_id != install.generation_id
            or current.revision is None
        ):
            raise InstallationError(
                "Legacy replacement pending authority changed."
            )
        _validate_prepared_source(install, prepared)
        _validate_prepared_identity_and_version(plan, prepared)
        operation = record.operation
        if _support_evidence(directory, support_files) != {
            item.path: item.revision for item in operation.inventory.entries
        }:
            raise InstallationError(
                "Replacement support differs from the authored pending generation."
            )
        if OperationStep.PACKAGE_CHANGED not in operation.steps:
            _observe_historical_installation(
                install.target.identity,
                plan.legacy,
                record_entry=plan.record_entry,
                expected_record_digest=plan.expected_record_digest,
                environment=environment,
            )
            receipts = tuple(
                item
                for item in operation.inventory.retained
                if item.path.name == "receipt.json"
            )
            if len(receipts) != 1:
                raise InstallationError(
                    "Pending replacement has no unique old receipt authority."
                )
            current_legacy = inspect_legacy_receipt(
                receipts[0].path,
                distribution=plan.evidence.distribution,
                command=plan.evidence.command,
            )
            if current_legacy.migration_evidence() != plan.evidence:
                raise InstallationError(
                    "Legacy receipt changed before replacement."
                )
            tools = inspect_uv_tools(
                install.target.backend, environment=environment
            )
            if install.target.identity.distribution not in tools:
                raise InstallationError(
                    "Recorded legacy package disappeared before replacement."
                )
        context_directory = Path(
            tempfile.mkdtemp(prefix="apprc-legacy-replace-")
        )
        os.chmod(context_directory, 0o700)
        context_path = _make_operation_context(plan, context_directory)
        try:
            observed: InstalledSnapshot | None = None
            if (
                OperationStep.PACKAGE_CHANGED in operation.steps
                and record.current is not None
            ):
                saved = record.current
                if saved is None or saved.distribution_record_digest is None:
                    raise InstallationError(
                        "Observed replacement checkpoint has no saved RECORD proof."
                    )
                try:
                    observed = probe_installed_tool(
                        install.target.backend,
                        install.target.identity,
                        saved.source,
                        install.target.placement,
                        probe_path=probe_path,
                        environment=environment,
                        expected_record_digest=saved.distribution_record_digest,
                    )
                    observed = probe_installed_tool(
                        install.target.backend,
                        install.target.identity,
                        saved.source,
                        install.target.placement,
                        probe_path=probe_path,
                        environment=environment,
                        operation_context=context_path,
                        expected_record_digest=saved.distribution_record_digest,
                    )
                except (
                    InstallationError,
                    OSError,
                    ValueError,
                    subprocess.CalledProcessError,
                ) as error:
                    raise InstallationError(
                        "Saved replacement no longer matches its observed package proof."
                    ) from error
                if (
                    observed.distribution_record_digest
                    != saved.distribution_record_digest
                ):
                    raise InstallationError(
                        "Saved replacement RECORD changed after observation."
                    )
            if observed is None:
                if OperationStep.PACKAGE_CHANGED not in operation.steps:
                    checkpoint = record_step(
                        directory,
                        operation_id=operation_id,
                        expected_revision=current.revision,
                        step=OperationStep.PACKAGE_CHANGED,
                    )
                    if checkpoint.revision is None:
                        raise InstallationError(
                            "Replacement checkpoint lost its revision."
                        )
                    current = checkpoint
                acquisition = replace(
                    install.target.source, requirement=prepared.requirement
                )
                install_uv_tool(
                    install.target.backend,
                    acquisition,
                    environment=environment,
                    python_requirement=str(base_python),
                    constraints=prepared.constraints,
                )
                observed = probe_installed_tool(
                    install.target.backend,
                    install.target.identity,
                    install.target.source,
                    install.target.placement,
                    probe_path=probe_path,
                    environment=environment,
                    acquisition_requirement=prepared.requirement,
                    acquisition_digest=prepared.digest,
                )
                observed = probe_installed_tool(
                    install.target.backend,
                    install.target.identity,
                    install.target.source,
                    install.target.placement,
                    probe_path=probe_path,
                    environment=environment,
                    operation_context=context_path,
                    acquisition_requirement=prepared.requirement,
                    acquisition_digest=prepared.digest,
                )
            checkpoint = inspect_installation(
                directory, app_id=install.target.identity.app_id
            )
            if checkpoint.revision is None or checkpoint.record is None:
                raise InstallationError(
                    "Observed replacement has no authority revision."
                )
            checkpoint_record = checkpoint.record
            operation_now = checkpoint_record.operation
            if (
                operation_now is None
                or operation_now.operation_id != operation_id
            ):
                raise InstallationError(
                    "Replacement operation changed after probe."
                )
            if (
                OperationStep.PACKAGE_CHANGED not in operation_now.steps
                or checkpoint_record.current != observed
            ):
                checkpoint = record_step(
                    directory,
                    operation_id=operation_id,
                    expected_revision=checkpoint.revision,
                    step=OperationStep.PACKAGE_CHANGED,
                    observed=observed,
                )
            if checkpoint.revision is None or checkpoint.record is None:
                raise InstallationError(
                    "Observed package checkpoint has no revision."
                )
            assert checkpoint.record.operation is not None
            retained_claims = {
                item.path: item.revision
                for item in checkpoint.record.operation.inventory.retained
                if item.revision is not None
            }
            for name in ("repair-installer.py", "legacy-recovery.py"):
                entry_path = directory / name
                if PurePosixPath(name) not in support_files:
                    continue
                claim = retained_claims.get(entry_path)
                if claim is None:
                    continue
                digest = hashlib.sha256(
                    support_files[PurePosixPath(name)]
                ).hexdigest()
                assert_no_links(entry_path)
                if claim != digest or file_revision(entry_path) != claim:
                    raise InstallationError(
                        "Published recovery entry lacks its retained digest claim."
                    )
            prior_outputs = checkpoint.record.owned_outputs
            bound = bind_install_support(
                support_files,
                observed,
                directory,
                prior_outputs,
            )

            input_root = (
                directory / "migration-staged" / str(record.generation_id)
            )
            operation_checkpoint = checkpoint.record.operation
            assert operation_checkpoint is not None
            retained = operation_checkpoint.inventory.retained
            expected_input_paths = {
                item.path for item in retained if item.path.parent == input_root
            }
            missing_final_paths = {
                item.path
                for item in retained
                if item.path.parent == input_root
                and item.path.name.startswith("final-")
                and not item.path.exists()
            }
            assert_no_links(input_root)
            if {
                child for child in input_root.iterdir()
            } != expected_input_paths - missing_final_paths:
                raise InstallationError(
                    "Unknown content occupies replacement recovery staging."
                )
            raw_inputs: dict[Path, bytes] = {}
            for item in retained:
                if (
                    item.path
                    in {
                        directory / "repair-installer.py",
                        directory / "legacy-recovery.py",
                    }
                    or item.path.parent != input_root
                    or item.path.name.startswith("final-")
                ):
                    continue
                if not item.path.name.startswith(("support-", "acquisition-")):
                    raise InstallationError(
                        "Unknown retained replacement staging entry."
                    )
                assert_no_links(item.path)
                content = item.path.read_bytes()
                if hashlib.sha256(content).hexdigest() != item.revision:
                    raise InstallationError(
                        "Retained replacement input changed."
                    )
                relative = PurePosixPath(item.path.name)
                if relative in bound:
                    raise InstallationError(
                        "Retained recovery input collides with authored support."
                    )
                raw_inputs[item.path] = content
            checkpoint, final_sources = _claim_final_support(checkpoint, bound)
            assert checkpoint.record is not None
            assert checkpoint.record.operation is not None
            retained_claims = {
                item.path: item.revision
                for item in checkpoint.record.operation.inventory.retained
                if item.revision is not None
            }
            all_outputs = dict(bound)
            for source, content in raw_inputs.items():
                all_outputs[PurePosixPath(source.name)] = content
            owned = tuple(
                OwnedOutput(
                    "support", str(path), hashlib.sha256(content).hexdigest()
                )
                for path, content in sorted(
                    all_outputs.items(), key=lambda pair: str(pair[0])
                )
            )
            observed = replace(observed, owned_outputs=owned)
            staged_support = _stage_final_support(
                plan,
                bound,
                raw_inputs,
                final_sources,
                retained_claims=retained_claims,
            )
            record = checkpoint.record
            assert record is not None and record.operation is not None
            migration = InstallationMigration(
                plan.inventory.source_root,
                plan.inventory.destination_root,
                "staged",
                plan.inventory,
                legacy=plan.evidence,
                staged_support=staged_support,
                operation_id=operation_id,
            )
            migrating = replace(
                record,
                status="incomplete",
                current=observed,
                operation=replace(
                    record.operation,
                    kind="migrate",
                    phase="pending",
                    intended=None,
                    placement=install.target.placement,
                    diagnostic=None,
                ),
                owned_outputs=owned,
                migration=migration,
            )
            revision = write_record(
                directory, migrating, expected_revision=checkpoint.revision
            )
        finally:
            if context_directory.is_symlink():
                raise InstallationError(
                    "Replacement context path was replaced by a link."
                )
            for child in context_directory.iterdir():
                child.unlink()
            context_directory.rmdir()
    return resume_migration(
        directory,
        operation_id=operation_id,
        expected_revision=revision,
    )


def execute_legacy_replacement(
    plan: LegacyReplacementPlan,
    prepared: PreparedSource,
    *,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
) -> InstallationInspection:
    """Persist explicit authority, replace the package, and retire old support last.

    :param plan: Revision-bound legacy replacement decision.
    :param prepared: Source prepared through the standard content-addressed path.
    :param environment: Captured invocation environment; no backend is reselected.
    :param probe_path: Standard isolated installed-package probe.
    :param support_files: Exact generated support to bind to the fresh observation.
    :param python_requirement: Declared app Python compatibility.
    :return: Ready authority, or a truthful pending inspection after interruption.
    """
    if not plan.quiescent:
        raise InstallationError("Stop legacy consumers before replacement.")
    _validate_replacement_plan(plan, verify_record=True)
    install = plan.install
    if (
        prepared.source != install.target.source
        and not prepared.source.matches_observation(install.target.source)
    ):
        raise InstallationError(
            "Prepared source differs from the planned replacement."
        )
    _validate_prepared_source(install, prepared)
    _validate_prepared_identity_and_version(plan, prepared)
    base_python = _recorded_base_python(plan, python_requirement)
    tools = inspect_uv_tools(install.target.backend, environment=environment)
    if install.target.identity.distribution not in tools:
        raise InstallationError(
            "Legacy receipt backend does not contain the recorded distribution."
        )
    with installation_lock(install.directory):
        inspection = inspect_installation(
            install.directory, app_id=install.target.identity.app_id
        )
        if (
            inspection.revision != install.expected_revision
            or inspection.snapshot.generation_id != install.expected_generation
            or inspection.record is not None
        ):
            raise InstallationError(
                "Legacy replacement authority changed after planning."
            )
        _validate_legacy_namespace(plan.evidence, install.directory)
        _observe_historical_installation(
            install.target.identity,
            plan.legacy,
            record_entry=plan.record_entry,
            expected_record_digest=plan.expected_record_digest,
            environment=environment,
        )
        current_legacy = inspect_legacy_receipt(
            plan.evidence.receipt.path,
            distribution=plan.evidence.distribution,
            command=plan.evidence.command,
        )
        if current_legacy.migration_evidence() != plan.evidence:
            raise InstallationError("Legacy receipt changed after planning.")
        pending = _write_initial_pending(plan, support_files, prepared)
        if pending.revision is None:
            raise InstallationError("Replacement authority has no revision.")
    try:
        return _verify_staged_recovery(
            plan,
            prepared,
            environment=environment,
            probe_path=probe_path,
            base_python=base_python,
            support_files=support_files,
        )
    except Exception as error:
        latest = inspect_installation(
            install.directory, app_id=install.target.identity.app_id
        )
        if (
            latest.record is not None
            and latest.record.operation is not None
            and latest.record.operation.operation_id == install.operation_id
            and latest.revision is not None
        ):
            fail_operation(
                install.directory,
                operation_id=install.operation_id,
                expected_revision=latest.revision,
                diagnostic=InstallationDiagnostic(
                    "legacy-replacement-incomplete",
                    str(error),
                    "Resolve the reported conflict, then resume this recorded replacement with the same source and operation.",
                ),
            )
        raise


def resume_legacy_replacement(
    directory: Path,
    prepared: PreparedSource | None = None,
    *,
    operation_id: UUID,
    expected_revision: str,
    quiescent: bool,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes] | None = None,
    python_requirement: str,
) -> InstallationInspection:
    """Resume only the exact pending replacement or finish its recorded migration.

    :param directory: Captured authority namespace; never rediscovered.
    :param prepared: Optional fresh preparation. Verified retained archive bytes
        are used if omitted.
    :param operation_id: Exact pending operation identifier.
    :param expected_revision: Last observed authority revision.
    :param quiescent: Fresh confirmation that legacy consumers remain stopped.
    :param environment: Captured invocation environment.
    :param probe_path: Standard isolated installed-package probe.
    :param support_files: Optional authored support. Verified retained bytes are
        used if omitted.
    :return: Ready authority or a durable incomplete state.
    """
    if not quiescent:
        raise InstallationError(
            "Stop legacy consumers before replacement recovery."
        )
    record = _pending(directory, operation_id, expected_revision)
    operation = record.operation
    if operation is None:
        raise InstallationError("No pending legacy replacement operation.")
    if operation.kind == "migrate":
        if (
            record.migration is None
            or record.migration.operation_id != operation_id
        ):
            raise InstallationError(
                "Pending migration does not belong to replacement."
            )
        return resume_migration(
            directory,
            operation_id=operation_id,
            expected_revision=expected_revision,
        )
    plan = _pending_plan(
        directory,
        record,
        operation_id=operation_id,
        expected_revision=expected_revision,
        quiescent=quiescent,
    )
    saved_support, archive, archive_digest = _load_pending_inputs(
        directory, record
    )
    selected_support = saved_support if support_files is None else support_files
    if _support_evidence(directory, selected_support) != {
        item.path: item.revision for item in operation.inventory.entries
    }:
        raise InstallationError(
            "Replacement support differs from the authored pending generation."
        )
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if prepared is None:
            temporary = tempfile.TemporaryDirectory(
                prefix="apprc-legacy-recovery-"
            )
            prepared = _prepare_saved_source(
                plan.install.target.source,
                archive,
                archive_digest,
                Path(temporary.name),
            )
        if (
            prepared.source != plan.install.target.source
            and not prepared.source.matches_observation(
                plan.install.target.source
            )
        ):
            raise InstallationError(
                "Prepared source differs from pending replacement."
            )
        base_python = _recorded_base_python(plan, python_requirement)
        return _verify_staged_recovery(
            plan,
            prepared,
            environment=environment,
            probe_path=probe_path,
            base_python=base_python,
            support_files=selected_support,
        )
    except Exception as error:
        latest = inspect_installation(directory, app_id=record.app_id)
        if (
            latest.record is not None
            and latest.record.operation is not None
            and latest.record.operation.operation_id == operation_id
            and latest.revision is not None
        ):
            fail_operation(
                directory,
                operation_id=operation_id,
                expected_revision=latest.revision,
                diagnostic=InstallationDiagnostic(
                    "legacy-replacement-incomplete",
                    str(error),
                    "Resolve the reported conflict, then resume this recorded replacement with the same source and operation.",
                ),
            )
        raise
    finally:
        if temporary is not None:
            temporary.cleanup()
