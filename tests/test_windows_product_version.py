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
