"""Checks for the version stored in a Windows executable."""

import pytest

from apprc.distribution.runtime._windows_version import numeric_product_version


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.19.0", (0, 19, 0, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
        ("5", (5, 0, 0, 0)),
        ("1.0rc1", None),
        ("1.0+local", None),
        ("1.2.3.4.5", None),
        ("65536.0", None),
        ("", None),
    ],
)
def test_numeric_product_version(version, expected):
    assert numeric_product_version(version) == expected


def test_version_writer_retains_original_on_failure(monkeypatch, caplog):
    import os
    from types import SimpleNamespace
    import sys
    from apprc.distribution.runtime._windows_version import versioned_executable

    monkeypatch.setitem(sys.modules, "os", SimpleNamespace(name="nt"))
    original = b"not an executable"
    assert versioned_executable(original, "1.2.3") == original
    assert "installation continues" in caplog.text
    monkeypatch.setitem(sys.modules, "os", os)


@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="requires native Windows"
)
def test_native_windows_stamped_launcher_still_runs(tmp_path):
    import subprocess
    import sysconfig
    from pathlib import Path
    import win32api
    from apprc.distribution.runtime._windows_version import versioned_executable

    source = Path(sysconfig.get_path("scripts")) / "pytest.exe"
    if not source.is_file():
        pytest.skip("pytest console launcher is unavailable")
    content = source.read_bytes()
    target = tmp_path / "pytest-versioned.exe"
    target.write_bytes(versioned_executable(content, "1.2.3"))
    info = win32api.GetFileVersionInfo(str(target), "\\")
    assert info["ProductVersionMS"] == 65538
    assert info["ProductVersionLS"] == 196608
    result = subprocess.run(
        [str(target), "--version"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "pytest" in result.stdout
