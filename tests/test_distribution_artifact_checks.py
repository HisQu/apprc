"""Native release checks preserve integrity across partial target builds."""

from __future__ import annotations

import hashlib
import io
import json
import struct
from dataclasses import replace
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from apprc.definition.installation import (
    InstallationIdentity,
    ProjectSnapshot,
    RuntimeSelection,
)
from apprc.definition.paths import Layout
from apprc.distribution.frontends import (
    MissingNativeArtifact,
    StaleNativeArtifact,
    _check_old_setup,
    _parse_previous_checksums,
    check_native_distribution,
)
from apprc.distribution.models import (
    AppCapabilities,
    NativeBinding,
    encode_native_binding,
)
from apprc.distribution.native import NativeTarget

LINUX: NativeTarget = "x86_64-unknown-linux-gnu"
WINDOWS: NativeTarget = "x86_64-pc-windows-msvc"
COMMIT = "a" * 40


def _setup(
    root: Path,
    target: NativeTarget,
    *,
    commit: str = COMMIT,
    bad_project: bool = False,
    legacy_binding: bool = False,
) -> Path:
    lock = b"version = 1\n"
    project = io.BytesIO()
    with ZipFile(project, "w", ZIP_STORED) as archive:
        archive.writestr(
            "pyproject.toml",
            '[project]\nname="fixture"\nversion="1.0.0"\n[project.scripts]\nfixture="fixture:main"\n',
        )
        archive.writestr("uv.lock", lock)
    payload = project.getvalue()
    binding = NativeBinding(
        InstallationIdentity(
            "fixture", "fixture", "fixture", None, ("fixture",)
        ),
        "fixture",
        "Fixture",
        "1.0.0",
        ProjectSnapshot(
            hashlib.sha256(payload).hexdigest(),
            hashlib.sha256(lock).hexdigest(),
            commit,
        ),
        RuntimeSelection("3.13"),
        AppCapabilities(),
        Layout(),
        "FIXTURE",
    )
    if bad_project:
        binding = replace(
            binding, source=replace(binding.source, digest="0" * 64)
        )
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    if target == LINUX:
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<HH", header, 16, 2, 62)
        name = "fixture-setup-linux-x86_64"
    else:
        header = bytearray(160)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        header[64:68] = b"PE\x00\x00"
        struct.pack_into("<H", header, 68, 0x8664)
        struct.pack_into("<HH", header, 84, 72, 2)
        struct.pack_into("<H", header, 88, 0x20B)
        struct.pack_into("<H", header, 156, 3)
        name = "fixture-setup-windows-x86_64.exe"
    path = dist / name
    path.write_bytes(header)
    encoded = encode_native_binding(binding)
    if legacy_binding:
        document = json.loads(encoded)
        del document["config_group_name"]
        encoded = json.dumps(document).encode()
    with ZipFile(path, "a", ZIP_STORED) as archive:
        archive.writestr("binding.json", encoded)
        archive.writestr("project.zip", payload)
    manifest = dist / "SHA256SUMS"
    previous = manifest.read_text() if manifest.exists() else ""
    manifest.write_text(
        previous + f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n"
    )
    return path


def test_current_target_allows_other_target_to_be_stale(tmp_path: Path) -> None:
    linux = _setup(tmp_path, LINUX)
    _setup(tmp_path, WINDOWS, commit="b" * 40)
    assert check_native_distribution(
        tmp_path, app_id="fixture", targets=(LINUX,), revision=COMMIT
    ) == (linux,)
    with pytest.raises(StaleNativeArtifact, match="windows"):
        check_native_distribution(
            tmp_path,
            app_id="fixture",
            targets=(LINUX, WINDOWS),
            revision=COMMIT,
        )


def test_current_target_allows_unpublished_other_target(tmp_path: Path) -> None:
    linux = _setup(tmp_path, LINUX)
    assert check_native_distribution(
        tmp_path, app_id="fixture", targets=(LINUX,), revision=COMMIT
    ) == (linux,)
    with pytest.raises(MissingNativeArtifact, match="windows"):
        check_native_distribution(
            tmp_path,
            app_id="fixture",
            targets=(LINUX, WINDOWS),
            revision=COMMIT,
        )


@pytest.mark.parametrize(
    "damage", ["missing", "checksum", "unlisted", "binding"]
)
def test_other_target_integrity_failure_precedes_stale_result(
    tmp_path: Path, damage: str
) -> None:
    _setup(tmp_path, LINUX, commit="b" * 40)
    windows = _setup(tmp_path, WINDOWS, bad_project=damage == "binding")
    if damage == "missing":
        windows.unlink()
    elif damage == "checksum":
        windows.write_bytes(b"corrupted")
    elif damage == "unlisted":
        manifest = tmp_path / "dist" / "SHA256SUMS"
        manifest.write_text(manifest.read_text().splitlines()[0] + "\n")
    with pytest.raises((ValueError, FileExistsError)) as error:
        check_native_distribution(
            tmp_path, app_id="fixture", targets=(LINUX,), revision=COMMIT
        )
    assert not isinstance(
        error.value, (MissingNativeArtifact, StaleNativeArtifact)
    )


def test_missing_output_set_can_be_built(tmp_path: Path) -> None:
    with pytest.raises(MissingNativeArtifact):
        check_native_distribution(
            tmp_path, app_id="fixture", targets=(LINUX,), revision=COMMIT
        )


def test_publisher_rejects_unlisted_other_target(tmp_path: Path) -> None:
    linux = _setup(tmp_path, LINUX)
    windows = linux.parent / "fixture-setup-windows-x86_64.exe"
    windows.write_bytes(b"unregistered")
    with pytest.raises(
        (ValueError, FileExistsError), match="no checksum manifest entry"
    ):
        _parse_previous_checksums(
            linux.parent / "SHA256SUMS", linux.parent, app_id="fixture"
        )


@pytest.mark.parametrize("legacy_binding", [False, True])
def test_old_download_allows_missing_other_platform(
    tmp_path: Path, legacy_binding: bool
) -> None:
    old = _setup(
        tmp_path, LINUX, commit="b" * 40, legacy_binding=legacy_binding
    )
    windows = _setup(tmp_path, WINDOWS)
    windows.unlink()
    binding = _check_old_setup(old, app_id="fixture", target=LINUX)
    assert binding.config_group_name == "config"
    assert binding.source.commit == "b" * 40
    with pytest.raises(ValueError, match="does not authenticate"):
        check_native_distribution(
            tmp_path, app_id="fixture", targets=(LINUX,), revision=COMMIT
        )


@pytest.mark.parametrize(
    "damage", ["checksum", "duplicate", "unknown", "no-manifest"]
)
def test_old_download_rejects_invalid_manifest(
    tmp_path: Path, damage: str
) -> None:
    old = _setup(tmp_path, LINUX)
    manifest = old.parent / "SHA256SUMS"
    if damage == "checksum":
        old.write_bytes(b"changed")
    elif damage == "duplicate":
        manifest.write_text(manifest.read_text() * 2)
    elif damage == "unknown":
        manifest.write_text(
            manifest.read_text() + "0" * 64 + "  unrelated.exe\n"
        )
    else:
        manifest.unlink()
    with pytest.raises(ValueError):
        _check_old_setup(old, app_id="fixture", target=LINUX)


def test_old_download_rejects_wrong_target(tmp_path: Path) -> None:
    old = _setup(tmp_path, LINUX)
    with pytest.raises(ValueError, match="canonical"):
        _check_old_setup(old, app_id="fixture", target=WINDOWS)
