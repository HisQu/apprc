"""Tests for the installed-distribution smoke contract."""

from __future__ import annotations

from dataclasses import replace

import pytest

from apprc_dev.packaging.install_smoke import (
    InstallSnapshot,
    validate_install_snapshot,
)


def valid_snapshot() -> InstallSnapshot:
    """Return a clean base-install snapshot.

    :return: Snapshot satisfying the published package contract.
    """
    return InstallSnapshot(
        app_rc_name="AppRC",
        config_name="Config",
        config_base_is_type=True,
        field_is_callable=True,
        public_names=frozenset({"AppRC", "Config", "ConfigBase", "field"}),
        requirements=(
            "platformdirs",
            'textual; extra == "tui"',
        ),
        extras=frozenset({"tui"}),
        textual_available=False,
        loaded_modules=frozenset({"apprc"}),
    )


def test_validate_install_snapshot_accepts_clean_base_install() -> None:
    validate_install_snapshot(valid_snapshot())


@pytest.mark.parametrize(
    ("replacement", "value"),
    [
        ("app_rc_name", "LegacyAppRC"),
        ("requirements", ("platformdirs", "textual")),
        ("extras", frozenset()),
        ("textual_available", True),
        ("loaded_modules", frozenset({"apprc", "textual.app"})),
    ],
)
def test_validate_install_snapshot_rejects_broken_base_contract(
    replacement: str,
    value: object,
) -> None:
    snapshot = replace(valid_snapshot(), **{replacement: value})

    with pytest.raises(AssertionError):
        validate_install_snapshot(snapshot)
