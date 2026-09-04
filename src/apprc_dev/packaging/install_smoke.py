"""Verify an installed AppRC distribution's base public surface."""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstallSnapshot:
    """Record the installed state needed by the distribution smoke test.

    :param app_rc_name: Runtime name of the public ``AppRC`` class.
    :param config_name: Runtime name of the public ``Config`` class.
    :param config_base_is_type: Whether ``ConfigBase`` is a class.
    :param field_is_callable: Whether the public field factory is callable.
    :param public_names: Names declared by the package facade.
    :param requirements: Installed distribution requirement declarations.
    :param extras: Extras declared by the installed distribution.
    :param textual_available: Whether the optional Textual package is installed.
    :param loaded_modules: Module names loaded before validation.
    """

    app_rc_name: str
    config_name: str
    config_base_is_type: bool
    field_is_callable: bool
    public_names: frozenset[str]
    requirements: tuple[str, ...]
    extras: frozenset[str]
    textual_available: bool
    loaded_modules: frozenset[str]


def capture_install_snapshot() -> InstallSnapshot:
    """Inspect the installed base package without importing optional Textual.

    :return: Installed facade, metadata, and optional-dependency state.
    """
    import apprc

    distribution_metadata = metadata.metadata("apprc")
    return InstallSnapshot(
        app_rc_name=apprc.AppRC.__name__,
        config_name=apprc.Config.__name__,
        config_base_is_type=isinstance(apprc.ConfigBase, type),
        field_is_callable=callable(apprc.field),
        public_names=frozenset(apprc.__all__),
        requirements=tuple(metadata.requires("apprc") or ()),
        extras=frozenset(distribution_metadata.get_all("Provides-Extra") or ()),
        textual_available=importlib.util.find_spec("textual") is not None,
        loaded_modules=frozenset(sys.modules),
    )


def validate_install_snapshot(snapshot: InstallSnapshot) -> None:
    """Reject an installed package that violates the clean base contract.

    :param snapshot: Installed state captured after importing the root facade.
    """
    assert snapshot.app_rc_name == "AppRC"
    assert snapshot.config_name == "Config"
    assert snapshot.config_base_is_type
    assert snapshot.field_is_callable
    assert {"AppRC", "Config", "ConfigBase", "field"}.issubset(
        snapshot.public_names
    )

    core_requirements = [
        requirement
        for requirement in snapshot.requirements
        if "extra ==" not in requirement
    ]
    assert not any(
        requirement.lower()
        .split(";", maxsplit=1)[0]
        .strip()
        .startswith("textual")
        for requirement in core_requirements
    )
    assert not any(
        requirement.lower()
        .split(";", maxsplit=1)[0]
        .strip()
        .startswith("platformdirs")
        for requirement in core_requirements
    )
    assert "tui" in snapshot.extras
    assert any(
        requirement.lower().startswith("textual") and "tui" in requirement
        for requirement in snapshot.requirements
    )
    assert not snapshot.textual_available
    assert not any(
        module_name == "textual" or module_name.startswith("textual.")
        for module_name in snapshot.loaded_modules
    )


def main() -> int:
    """Run the installed-distribution smoke test.

    :return: Process exit code.
    """
    validate_install_snapshot(capture_install_snapshot())
    print("apprc base install smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
