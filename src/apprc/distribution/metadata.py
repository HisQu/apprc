"""Read project declarations without importing the application or its settings."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from apprc.definition.installation import InstallationIdentity
from apprc.distribution.models import (
    AppCapabilities,
    ProjectMetadata,
    relative_destination,
)

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC


def read_project_metadata(project_root: Path) -> ProjectMetadata:
    """Read PEP 621 identities and explicit ``tool.apprc.distribution`` routing.

    :param project_root: Application project containing pyproject.toml.
    :return: Author metadata; no application module is imported.
    """
    root = project_root.expanduser().absolute()
    with (root / "pyproject.toml").open("rb") as stream:
        metadata = tomllib.load(stream)
    project = metadata.get("project", {})
    name = project.get("name")
    version = project.get("version")
    scripts = project.get("scripts", {})
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError(
            "Distribution generation requires explicit project.name and project.version."
        )
    if (
        not isinstance(scripts, dict)
        or not scripts
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in scripts.items()
        )
    ):
        raise ValueError(
            "Declare project.scripts before generating application management support."
        )
    settings = metadata.get("tool", {}).get("apprc", {}).get("distribution", {})
    if not isinstance(settings, dict):
        raise ValueError("tool.apprc.distribution must be a table.")
    allowed = {
        "app-id",
        "import-package",
        "apprc-reference",
        "project-path",
        "distribution-path",
        "launcher-command",
    }
    if set(settings) - allowed or any(
        not isinstance(value, str) for value in settings.values()
    ):
        raise ValueError(
            "Unknown or non-string tool.apprc.distribution setting."
        )
    distribution = re.sub(r"[-_.]+", "-", name).lower()
    packages = {
        value.split(":", 1)[0].split(".", 1)[0] for value in scripts.values()
    }
    import_package = settings.get("import-package")
    if import_package is None:
        if len(packages) != 1:
            raise ValueError(
                "Multiple script packages require an explicit import-package setting."
            )
        import_package = packages.pop()
    app_id = settings.get("app-id", distribution)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", app_id) is None:
        raise ValueError("app-id must be one safe filename component.")
    if not all(part.isidentifier() for part in import_package.split(".")):
        raise ValueError("import-package must name a Python package.")
    reference = settings.get("apprc-reference")
    if reference is not None:
        module, separator, attribute = reference.partition(":")
        if (
            not separator
            or not all(part.isidentifier() for part in module.split("."))
            or not attribute.isidentifier()
        ):
            raise ValueError("apprc-reference must be module:object.")
    identity = InstallationIdentity(
        app_id,
        distribution,
        import_package,
        reference,
        tuple(sorted(scripts)),
    )
    project_path = PurePosixPath(settings.get("project-path", "."))
    if project_path != PurePosixPath("."):
        relative_destination(project_path)
    distribution_path = relative_destination(
        settings.get(
            "distribution-path", f"src/{import_package.split('.')[0]}_distr"
        )
    )
    python_requirement = project.get("requires-python", ">=3.12")
    if (
        not isinstance(python_requirement, str)
        or not python_requirement
        or "\n" in python_requirement
        or "\r" in python_requirement
    ):
        raise ValueError(
            "project.requires-python must be one explicit Python requirement."
        )
    return ProjectMetadata(
        root,
        identity,
        version,
        project_path,
        distribution_path,
        settings.get("launcher-command"),
        python_requirement,
    )


def inspect_capabilities(apprc: AppRC) -> AppCapabilities:
    """Read only registered capabilities, never author installation or values.

    :param apprc: Explicit author-supplied application declaration.
    :return: Capability flags used to generate management choices.
    """
    spec = apprc.schema
    return AppCapabilities(
        spec.paths,
        spec.user_dotenv is not None,
        spec.workspaces is not None,
        spec.workspaces.registry if spec.workspaces is not None else False,
    )
