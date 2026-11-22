"""Checks for the version stored in a Windows executable."""

import os
import struct
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

import pytest

from apprc.distribution.runtime._os_integration import publish_global_command
from apprc.distribution.runtime._windows_version import (
    _replace_version_resource,
    _version_resource,
    numeric_product_version,
    versioned_executable,
)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.23.1.dev1", (0, 23, 1, 1)),
        ("0.23.1a1", (0, 23, 1, 101)),
        ("0.23.1b1", (0, 23, 1, 201)),
        ("0.23.1b2", (0, 23, 1, 202)),
        ("0.23.1rc1", (0, 23, 1, 301)),
        ("0.23.1", (0, 23, 1, 400)),
        ("0.23.1.post1", (0, 23, 1, 501)),
        ("0.23.1.7", (0, 23, 1, 7)),
        ("5", (5, 0, 0, 400)),
        ("5.1b0", (5, 1, 0, 200)),
        ("5.1.dev0", (5, 1, 0, 0)),
        ("v5.1-BETA_99", (5, 1, 0, 299)),
        ("5.1-99", (5, 1, 0, 599)),
        ("65535.65535.65535.65535", (65535, 65535, 65535, 65535)),
        ("65535.65535.65535.post99", (65535, 65535, 65535, 599)),
        ("0.23.1b1.dev2", None),
        ("0.23.1a1.post2", None),
        ("0.23.1.post2.dev1", None),
        ("1.0.dev100", None),
        ("1.0a100", None),
        ("1.0b100", None),
        ("1.0rc100", None),
        ("1.0.post100", None),
        ("1!1.0", None),
        ("0!1.0", None),
        ("1.0+local", None),
        ("1.2.3.4.5", None),
        ("1.2.3.4b1", None),
        ("1.2.3.65536", None),
        ("1.2.65536", None),
        ("1.65536", None),
        ("65536.0", None),
        ("1.0b-1.dev2", None),
        ("-1.0", None),
        ("", None),
    ],
)
def test_numeric_product_version(version, expected):
    assert numeric_product_version(version) == expected


def test_projected_versions_sort_in_pep440_order() -> None:
    from packaging.version import Version

    versions = (
        "0.23.1.dev0",
        "0.23.1.dev99",
        "0.23.1a0",
        "0.23.1a99",
        "0.23.1b0",
        "0.23.1b99",
        "0.23.1rc0",
        "0.23.1rc99",
        "0.23.1",
        "0.23.1.post0",
        "0.23.1.post99",
        "0.23.2.dev0",
    )
    numeric = [numeric_product_version(version) for version in versions]
    assert all(value is not None for value in numeric)
    pairs = [value for value in numeric if value is not None]
    assert pairs == sorted(set(pairs))
    assert list(versions) == sorted(versions, key=Version)


def test_version_resource_has_fixed_and_text_versions() -> None:
    resource = _version_resource(23, (1 << 16) | 201, "0.23.1b1", 2)
    assert struct.unpack_from("<HHH", resource) == (len(resource), 52, 0)
    assert struct.unpack_from("<13I", resource, 40)[:8] == (
        0xFEEF04BD,
        0x10000,
        23,
        65737,
        23,
        65737,
        0x3F,
        2,
    )
    for text in ("040904b0", "FileVersion", "ProductVersion", "Translation"):
        assert (text + "\0").encode("utf-16le") in resource
    assert resource.count("0.23.1b1\0".encode("utf-16le")) == 2


@pytest.mark.parametrize("has_existing_version", [False, True])
def test_writes_launcher_version_without_resetting_other_resource_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_existing_version: bool
) -> None:
    class MissingVersionResource(OSError):
        winerror = 1813

    def resource_names(module: int, resource_type: int) -> list[int]:
        assert (module, resource_type) == (11, 16)
        if not has_existing_version:
            raise MissingVersionResource
        return [1, 102]

    calls: list[tuple[object, ...]] = []
    api = SimpleNamespace(
        LoadLibraryEx=lambda *_: 11,
        EnumResourceNames=resource_names,
        EnumResourceLanguages=lambda _module, _type, name: (
            [0, 0x0407] if name == 1 else [0]
        ),
        FreeLibrary=lambda module: calls.append(("free", module)),
        BeginUpdateResource=lambda path, reset: (
            calls.append(("begin", path, reset)) or 12
        ),
        UpdateResource=lambda *args: calls.append(("update", *args)),
        EndUpdateResource=lambda *args: calls.append(("end", *args)),
        error=MissingVersionResource,
    )
    monkeypatch.setitem(sys.modules, "win32api", api)
    path = tmp_path / "launcher.exe"
    _replace_version_resource(path, b"new version resource")
    assert calls == [
        ("free", 11),
        ("begin", str(path), False),
        *(
            [
                ("update", 12, 16, 1, None, 0x0407),
                ("update", 12, 16, 102, None, 0),
            ]
            if has_existing_version
            else []
        ),
        ("update", 12, 16, 1, b"new version resource", 0),
        ("end", 12, False),
    ]


def test_version_writer_retains_original_on_failure(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "os", SimpleNamespace(name="nt"))
    original = b"not an executable"
    assert versioned_executable(original, "0.23.1b1.dev2") == original
    assert "unsupported automatic Windows version projection" in caplog.text
    assert "0.23.1b1.dev2" in caplog.text
    assert versioned_executable(original, "1.2.3") == original
    assert "installation continues" in caplog.text
    monkeypatch.setitem(sys.modules, "os", os)


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows")
def test_native_windows_published_launcher_still_runs_after_replacement(
    tmp_path: Path,
) -> None:
    import win32api

    source = Path(sysconfig.get_path("scripts")) / "pytest.exe"
    if not source.is_file():
        pytest.skip("pytest console launcher is unavailable")
    content = source.read_bytes()
    prepared = tmp_path / "prepared.exe"
    command = tmp_path / "published.exe"
    previous = ()
    for version, revision in (("0.23.1b1", 201), ("0.23.1", 400)):
        prepared.write_bytes(versioned_executable(content, version))
        previous = (
            publish_global_command(command, prepared, previous=previous),
        )
        info = win32api.GetFileVersionInfo(str(command), "\\")
        assert info["FileVersionMS"] == info["ProductVersionMS"] == 23
        assert (
            info["FileVersionLS"]
            == info["ProductVersionLS"]
            == ((1 << 16) | revision)
        )
        for field in ("FileVersion", "ProductVersion"):
            assert (
                win32api.GetFileVersionInfo(
                    str(command), rf"\StringFileInfo\040904b0\{field}"
                )
                == version
            )
        assert bool(info["FileFlags"] & 2) is (revision < 400)
        observed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-Command -CommandType Application "
                "$env:APPRC_VERSION_TEST_COMMAND).Version.ToString()",
            ],
            env={**os.environ, "APPRC_VERSION_TEST_COMMAND": str(command)},
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert observed.stdout.strip() == f"0.23.1.{revision}"
        result = subprocess.run(
            [str(command), "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert "pytest" in result.stdout
