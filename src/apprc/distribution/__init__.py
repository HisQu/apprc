"""Ordinary-Python author composition and deterministic management artifacts."""

from apprc.distribution.metadata import (
    inspect_capabilities as inspect_capabilities,
    read_project_metadata as read_project_metadata,
)
from apprc.distribution.models import (
    AppCapabilities as AppCapabilities,
    Artifact as Artifact,
    DistributionSpec as DistributionSpec,
    PayloadTree as PayloadTree,
    ProjectMetadata as ProjectMetadata,
)
from apprc.distribution.rendering import (
    build_main_installer as build_main_installer,
    generate_artifacts as generate_artifacts,
    install_support_files as install_support_files,
    render_bootstraps as render_bootstraps,
    render_launcher as render_launcher,
    render_saved_support as render_saved_support,
    render_uninstaller as render_uninstaller,
)
from apprc.distribution.artifacts import write_artifacts as write_artifacts
