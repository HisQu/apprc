"""Authoring APIs for immutable AppRC native distributions."""

from apprc.definition.installation import (
    InstallationHooks,
    ProjectSnapshot,
    RuntimeSelection,
)
from apprc.distribution.frontends import (
    NativeDistribution,
    build_native_distribution,
)
from apprc.distribution.metadata import (
    inspect_capabilities,
    read_distribution_spec,
    read_project_metadata,
)
from apprc.distribution.models import (
    AppCapabilities,
    Artifact,
    DistributionSpec,
    NativeBinding,
    ProjectMetadata,
    decode_native_binding,
    encode_native_binding,
)
from apprc.distribution.native import (
    NativeArtifact,
    NativeFrontendBuilder,
    NativeTarget,
)
from apprc.distribution.project import (
    PreparedProject,
    build_project_snapshot,
)

__all__ = (
    "AppCapabilities",
    "Artifact",
    "DistributionSpec",
    "InstallationHooks",
    "NativeArtifact",
    "NativeBinding",
    "NativeDistribution",
    "NativeFrontendBuilder",
    "NativeTarget",
    "PreparedProject",
    "ProjectMetadata",
    "ProjectSnapshot",
    "RuntimeSelection",
    "build_native_distribution",
    "build_project_snapshot",
    "decode_native_binding",
    "encode_native_binding",
    "inspect_capabilities",
    "read_distribution_spec",
    "read_project_metadata",
)
