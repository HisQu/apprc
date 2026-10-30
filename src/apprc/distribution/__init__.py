"""Ordinary-Python author composition and deterministic management artifacts."""

# ruff: noqa: F401
from apprc.distribution.metadata import (
    inspect_capabilities,
    read_project_metadata,
)
from apprc.distribution.models import (
    AppCapabilities,
    Artifact,
    DistributionSpec,
    PayloadTree,
    ProjectMetadata,
)
from apprc.distribution.rendering import (
    build_main_installer,
    generate_artifacts,
    install_support_files,
    render_bootstraps,
    render_launcher,
    render_saved_support,
    render_uninstaller,
)
from apprc.distribution.artifacts import write_artifacts
