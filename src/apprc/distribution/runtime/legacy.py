"""Strict inspection of the known Buildben v1 distribution receipt."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Mapping
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from apprc.definition.installation import (
        InstallationInspection,
        InstalledSnapshot,
        InstallationPlacement,
        LegacyMigrationEvidence,
        MigrationInventory,
    )
    from apprc.services.installation import InstallationManager

from apprc.definition.installation import (
    InstallationDiagnostic,
    InventoryEntry,
    LegacyRunnable,
    StagedSupportOutput,
    UvToolTarget,
)
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import file_revision

_LEGACY_SUPPORT = (
    "receipt.json",
    "lifecycle.py",
    "uninstall.sh",
    "uninstall.cmd",
    "uninstall.ps1",
    "prepare-powershell-windows.cmd",
)


@dataclass(frozen=True, slots=True)
class LegacyReceiptInspection:
    """Validated facts from a legacy receipt, never an alternate authority."""

    receipt: InventoryEntry | None
    distribution: str | None
    command: str | None
    version: str | None
    source_ref: str | None
    backend: UvToolTarget | None
    base_python: Path | None
    runnables: tuple[LegacyRunnable, ...]
    diagnostics: tuple[InstallationDiagnostic, ...]

    @property
    def compatible(self) -> bool:
        """Whether identity/backend fields are complete enough for review."""
        return (
            self.backend is not None
            and self.distribution is not None
            and not self.diagnostics
        )

    def migration_evidence(self) -> LegacyMigrationEvidence:
        """Return core-owned immutable migration evidence when validation passed."""
        if not self.compatible or self.receipt is None:
            raise ValueError(
                "An invalid or incomplete legacy receipt cannot be migrated."
            )
        from apprc.definition.installation import LegacyMigrationEvidence

        assert self.distribution is not None
        assert self.command is not None
        assert self.version is not None
        assert self.source_ref is not None
        assert self.backend is not None
        assert self.base_python is not None
        return LegacyMigrationEvidence(
            self.receipt,
            self.distribution,
            self.command,
            self.version,
            self.source_ref,
            self.backend,
            self.base_python,
            self.runnables,
        )


def stage_legacy_support(
    directory: Path,
    *,
    generation_id: UUID,
    support_files: Mapping[str, bytes],
) -> tuple[StagedSupportOutput, ...]:
    """Stage exact replacement support for Core's resumable legacy cutover."""
    if not support_files:
        raise ValueError(
            "Legacy migration requires the complete replacement support set."
        )
    staging_root = directory / "migration-staged" / str(generation_id)
    outputs: list[StagedSupportOutput] = []
    for name, content in sorted(support_files.items()):
        relative = PurePosixPath(name)
        if (
            not isinstance(name, str)
            or not isinstance(content, bytes)
            or relative.is_absolute()
            or not relative.parts
            or str(relative) != name
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError(
                f"Invalid relative migration support path: {name!r}."
            )
        source = staging_root.joinpath(*relative.parts)
        destination = directory.joinpath(*relative.parts)
        digest = hashlib.sha256(content).hexdigest()
        assert_no_links(source)
        assert_no_links(destination)
        existing = file_revision(source)
        destination_revision = file_revision(destination)
        if existing is not None and existing != digest:
            raise ValueError(
                f"Migration staging path contains different bytes: {source}."
            )
        if existing is None:
            if destination_revision not in {None, digest}:
                raise ValueError(
                    f"Migration destination contains different bytes: {destination}."
                )
            if destination_revision is None:
                create_private_directory_if_missing(directory)
                create_private_directory_if_missing(source.parent)
                write_bytes_atomic(source, content, private=True)
        if destination_revision is None and relative in {
            PurePosixPath("launch.sh"),
            PurePosixPath("uninstall.sh"),
        }:
            source.chmod(0o700)
        outputs.append(StagedSupportOutput(source, destination, digest))
    return tuple(outputs)


def migrate_legacy_receipt(
    manager: InstallationManager,
    inspection: LegacyReceiptInspection,
    placement: InstallationPlacement,
    *,
    inventory: MigrationInventory,
    observed: InstalledSnapshot,
    support_files: Mapping[str, bytes],
    quiescent: bool,
    generation_id: UUID | None = None,
) -> InstallationInspection:
    """Stage replacement support and run Core's exact legacy migration protocol."""
    generation = generation_id or uuid4()
    evidence = inspection.migration_evidence()
    staged = stage_legacy_support(
        manager.directory,
        generation_id=generation,
        support_files=support_files,
    )
    return manager.migrate_legacy(
        evidence,
        placement,
        inventory=inventory,
        observed=observed,
        quiescent=quiescent,
        staged_support=staged,
        generation_id=generation,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate legacy receipt key: {key}.")
        result[key] = value
    return result


def inspect_legacy_receipt(
    receipt_path: Path,
    *,
    distribution: str,
    command: str,
) -> LegacyReceiptInspection:
    """Validate the exact legacy schema and enumerate only known support files.

    :param receipt_path: Explicit receipt under the known legacy installation address.
    :param distribution: Expected normalized package identity.
    :param command: Expected application command identity.
    :return: Validated facts and exact revision-checked legacy support inventory.
    """
    distribution_value: str | None = None
    command_value: str | None = None
    version_value: str | None = None
    source_ref_value: str | None = None
    python_path: Path | None = None
    diagnostics: list[InstallationDiagnostic] = []
    values: dict[str, object] = {}
    try:
        decoded = json.loads(
            receipt_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
        required = {
            "schema_version",
            "distribution",
            "command",
            "version",
            "source_ref",
            "python",
            "uv",
            "tool_dir",
            "tool_bin_dir",
            "appdata_supported",
            "uv_bootstrapped",
            "package_removed",
            "uv_binaries",
        }
        if not isinstance(decoded, dict) or set(decoded) != required:
            raise ValueError("Legacy receipt has unknown or missing fields.")
        values = decoded
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"] != 1
        ):
            raise ValueError("Legacy receipt schema version is unsupported.")
        distribution_raw = values["distribution"]
        command_raw = values["command"]
        version_raw = values["version"]
        source_ref_raw = values["source_ref"]
        if (
            not isinstance(distribution_raw, str)
            or not distribution_raw
            or not isinstance(command_raw, str)
            or not command_raw
            or not isinstance(version_raw, str)
            or not version_raw
            or not isinstance(source_ref_raw, str)
            or not source_ref_raw
        ):
            raise ValueError("Legacy receipt identity fields are malformed.")
        distribution_value = distribution_raw
        command_value = command_raw
        version_value = version_raw
        source_ref_value = source_ref_raw
        if distribution_value != distribution or command_value != command:
            raise ValueError(
                "Legacy receipt identity does not match the expected application."
            )
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", distribution):
            raise ValueError(
                "Expected distribution identity is not normalized."
            )
        paths: dict[str, Path] = {}
        for name in ("python", "uv", "tool_dir", "tool_bin_dir"):
            value = values[name]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError(
                    f"Legacy receipt {name} must be an absolute path."
                )
            paths[name] = Path(value)
        python_path = paths["python"]
        for name in ("appdata_supported", "uv_bootstrapped", "package_removed"):
            if type(values[name]) is not bool:
                raise ValueError(f"Legacy receipt {name} must be a boolean.")
        binaries = values["uv_binaries"]
        if not isinstance(binaries, list):
            raise ValueError("Legacy uv_binaries must be a list.")
        for item in binaries:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "sha256"}
                or not isinstance(item["path"], str)
                or not Path(item["path"]).is_absolute()
                or not isinstance(item["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            ):
                raise ValueError(
                    "Legacy uv binary ownership entry is malformed."
                )
        backend = UvToolTarget(
            paths["uv"],
            paths["tool_dir"],
            paths["tool_bin_dir"],
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        diagnostics.append(
            InstallationDiagnostic(
                "legacy-receipt-invalid",
                str(error),
                "Inspect manually; do not adopt or remove unverified targets.",
            )
        )
        backend = None

    runnables: list[LegacyRunnable] = []
    receipt: InventoryEntry | None = None
    root = receipt_path.parent
    for name in _LEGACY_SUPPORT:
        path = root / name
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode):
            diagnostics.append(
                InstallationDiagnostic(
                    "legacy-support-unsafe",
                    f"Known legacy support path is not a regular file: {name}.",
                    "Resolve the link or special file manually before migration.",
                )
            )
            continue
        revision = file_revision(path)
        if revision is None and name != "receipt.json":
            diagnostics.append(
                InstallationDiagnostic(
                    "legacy-support-unsafe",
                    f"Known legacy support file changed during inspection: {name}.",
                    "Inspect manually before migration.",
                )
            )
            continue
        if name == "receipt.json":
            receipt = InventoryEntry(path, "file", revision)
        else:
            assert revision is not None
            runnables.append(
                LegacyRunnable(path, root / f".retired-{name}", revision)
            )
    if receipt is None:
        diagnostics.append(
            InstallationDiagnostic(
                "legacy-receipt-missing",
                "The known legacy receipt is absent.",
                "Do not infer previous installation identity from remaining files.",
            )
        )
    return LegacyReceiptInspection(
        receipt,
        distribution_value,
        command_value,
        version_value,
        source_ref_value,
        backend,
        python_path,
        tuple(runnables),
        tuple(diagnostics),
    )
