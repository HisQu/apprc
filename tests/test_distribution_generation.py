"""Distribution declaration validation without importing application code."""

from __future__ import annotations

from pathlib import Path

import pytest

from apprc import AppRC, Paths
from apprc.definition.installation import InstallationHooks
from apprc.distribution.metadata import (
    inspect_capabilities,
    read_distribution_spec,
    read_project_metadata,
)
from apprc.distribution.models import relative_destination


def _write_project(
    root: Path,
    *,
    name: str = "Package.Name",
    scripts: str = 'fixture-command = "unimportable_package.cli:main"',
    requires_python: str = ">=3.12",
    settings: str = "",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f"[project]\nname = {name!r}\nversion = '2.0.0'\n"
        f"requires-python = {requires_python!r}\n"
        f"[project.scripts]\n{scripts}\n{settings}",
        encoding="utf-8",
    )


def test_project_metadata_keeps_app_distribution_and_import_identity_distinct(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path,
        settings=(
            "[tool.apprc.distribution]\n"
            "app-id = 'persistent-identity'\n"
            "import-package = 'unimportable_package'\n"
            "apprc-reference = 'unimportable_package.config:MyRC'\n"
            "command-name = 'fixture-command'\n"
            "runtime-python = '3.13'\n"
        ),
    )

    metadata = read_project_metadata(tmp_path)

    assert metadata.identity.app_id == "persistent-identity"
    assert metadata.identity.distribution == "package-name"
    assert metadata.identity.import_package == "unimportable_package"
    assert metadata.identity.commands == ("fixture-command",)
    assert metadata.identity.apprc_reference == "unimportable_package.config:MyRC"
    assert metadata.runtime_python_requirement == ">=3.12,==3.13.*"


def test_distribution_spec_captures_capabilities_hooks_and_launch_setting(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path,
        settings=(
            "[tool.apprc.distribution]\n"
            "config = true\n"
            "cache = true\n"
            "workspaces = true\n"
            "workspace-registry = true\n"
            "launch-enabled = true\n"
            "[tool.apprc.distribution.hooks]\n"
            "initialize = 'fixture_app:initialize'\n"
        ),
    )

    spec = read_distribution_spec(tmp_path)

    assert spec.capabilities.paths == Paths(config=True, cache=True)
    assert spec.capabilities.workspaces
    assert spec.capabilities.workspace_registry
    assert spec.hooks == InstallationHooks(initialize="fixture_app:initialize")
    assert spec.launch_enabled
    assert spec.layout.root is None


def test_multiple_console_commands_require_an_explicit_selection(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path,
        scripts=(
            'first-command = "fixture_app:first"\n'
            'second-command = "fixture_app:second"'
        ),
        settings=(
            "[tool.apprc.distribution]\n"
            "import-package = 'fixture_app'\n"
        ),
    )

    with pytest.raises(ValueError, match="Multiple console commands"):
        read_distribution_spec(tmp_path)


@pytest.mark.parametrize("value", ("3.13.*", ">=3.13", "python3.13", "3.13.1"))
def test_runtime_python_must_be_an_exact_minor(
    tmp_path: Path, value: str
) -> None:
    _write_project(
        tmp_path,
        settings=(
            "[tool.apprc.distribution]\n"
            f"runtime-python = {value!r}\n"
        ),
    )

    with pytest.raises(ValueError, match="runtime-python"):
        read_project_metadata(tmp_path)


def test_artifact_destination_rejects_escaping_and_platform_specific_paths() -> None:
    for destination in (
        "../outside",
        "/absolute",
        "C:/outside",
        "nested\\outside",
    ):
        with pytest.raises(ValueError):
            relative_destination(destination)


def test_capability_inspection_does_not_create_installation_state() -> None:
    app = AppRC(app_id="generation-fixture", paths=Paths(cache=True))

    capabilities = inspect_capabilities(app)

    assert capabilities.paths == Paths(cache=True)
    assert not capabilities.workspaces
    assert not app.installation().directory.exists()
