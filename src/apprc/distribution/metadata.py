"""Read project declarations without importing application code."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from apprc.definition.installation import InstallationIdentity, InstallationHooks
from apprc.distribution.models import (
    AppCapabilities,
    DistributionSpec,
    ProjectMetadata,
    relative_destination,
)
from apprc.definition.paths import Layout, Paths

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def read_project_metadata(project_root: Path) -> ProjectMetadata:
    """Read PEP 621 identity and portable AppRC routing declarations."""
    root = project_root.expanduser().absolute()
    with (root / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("Distribution generation requires a [project] table.")
    name, version, scripts = project.get("name"), project.get("version"), project.get("scripts")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("Distribution generation requires project.name and project.version.")
    if not isinstance(scripts, dict) or not scripts or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in scripts.items()
    ):
        raise ValueError("Declare project.scripts before generating native management support.")
    tool = document.get("tool", {})
    apprc = tool.get("apprc", {}) if isinstance(tool, dict) else {}
    settings = apprc.get("distribution", {}) if isinstance(apprc, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("tool.apprc.distribution must be a table.")
    allowed = {
        "app-id", "import-package", "apprc-reference", "project-path",
        "distribution-path", "command-name", "runtime-python", "display-name",
        "bootstrap-env-prefix", "maintenance-group-name", "launch-enabled",
        "hooks", "config", "appdata", "cache", "state", "user-dotenv",
        "workspaces", "workspace-registry",
    }
    if set(settings) - allowed:
        raise ValueError("Unknown tool.apprc.distribution setting.")
    string_keys = allowed - {
        "hooks", "launch-enabled", "config", "appdata", "cache", "state",
        "user-dotenv", "workspaces", "workspace-registry",
    }
    if any(not isinstance(value, str) for key, value in settings.items() if key in string_keys):
        raise ValueError("String distribution settings must be strings.")
    distribution = re.sub(r"[-_.]+", "-", name).lower()
    packages = {value.split(":", 1)[0].split(".", 1)[0] for value in scripts.values()}
    import_package = settings.get("import-package")
    if import_package is None:
        if len(packages) != 1:
            raise ValueError("Multiple script packages require import-package.")
        import_package = packages.pop()
    if not all(part.isidentifier() for part in import_package.split(".")):
        raise ValueError("import-package must name a Python package.")
    app_id = settings.get("app-id", distribution)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None:
        raise ValueError("app-id must be one safe filename component.")
    reference = settings.get("apprc-reference")
    if reference is not None:
        module, separator, attribute = reference.partition(":")
        if not separator or not all(part.isidentifier() for part in module.split(".")) or not attribute.isidentifier():
            raise ValueError("apprc-reference must be module:object.")
    identity = InstallationIdentity(app_id, distribution, import_package, reference, tuple(sorted(scripts)))
    project_path = PurePosixPath(settings.get("project-path", "."))
    if project_path != PurePosixPath("."):
        relative_destination(project_path)
    distribution_path = relative_destination(
        settings.get("distribution-path", f"src/{import_package.split('.')[0]}_distr")
    )
    python_requirement = project.get("requires-python", ">=3.12")
    if not isinstance(python_requirement, str) or not python_requirement or "\n" in python_requirement or "\r" in python_requirement:
        raise ValueError("project.requires-python must be one explicit Python requirement.")
    runtime_python = settings.get("runtime-python")
    if runtime_python is not None and re.fullmatch(r"3\.(?:0|[1-9][0-9]*)", runtime_python) is None:
        raise ValueError("runtime-python must be an exact CPython minor string.")
    return ProjectMetadata(
        root,
        identity,
        version,
        project_path,
        distribution_path,
        settings.get("command-name"),
        python_requirement,
        runtime_python,
    )


def read_distribution_spec(project_root: Path) -> DistributionSpec:
    """Read product capabilities and runtime hook references from the project."""
    metadata = read_project_metadata(project_root)
    with (metadata.project_root / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    tool = document.get("tool", {})
    apprc = tool.get("apprc", {}) if isinstance(tool, dict) else {}
    settings = apprc.get("distribution", {}) if isinstance(apprc, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("tool.apprc.distribution must be a table.")
    hook_values = settings.get("hooks", {})
    if (
        not isinstance(hook_values, dict)
        or set(hook_values) - {"initialize", "inventory", "cleanup", "migrate"}
        or any(not isinstance(value, str) for value in hook_values.values())
    ):
        raise ValueError("hooks must contain only string callback references.")
    hooks = InstallationHooks(**hook_values)
    boolean_keys = (
        "config", "appdata", "cache", "state", "user-dotenv",
        "workspaces", "workspace-registry", "launch-enabled",
    )
    if any(key in settings and type(settings[key]) is not bool for key in boolean_keys):
        raise ValueError("Distribution capabilities and launch-enabled must be booleans.")
    project = document["project"]
    capabilities = AppCapabilities(
        Paths(**{key: settings.get(key, False) for key in ("config", "appdata", "cache", "state")}),
        settings.get("user-dotenv", False),
        settings.get("workspaces", False),
        settings.get("workspace-registry", False),
    )
    return DistributionSpec(
        metadata,
        capabilities,
        settings.get("display-name", project["name"]),
        Layout.native(),
        settings.get("bootstrap-env-prefix", "APPRC"),
        settings.get("maintenance-group-name", "app"),
        hooks,
        settings.get("launch-enabled", False),
    )


def inspect_capabilities(apprc: AppRC) -> AppCapabilities:
    """Read registered capabilities, never application configuration values."""
    spec = apprc.schema
    return AppCapabilities(
        spec.paths,
        spec.user_dotenv is not None,
        spec.workspaces is not None,
        spec.workspaces.registry if spec.workspaces is not None else False,
    )

