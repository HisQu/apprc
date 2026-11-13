"""Authoring APIs for immutable AppRC native distributions."""

from apprc.distribution.frontends import (
    NativeDistribution as NativeDistribution,
    build_native_distribution as build_native_distribution,
)
from apprc.distribution.metadata import (
    inspect_capabilities as inspect_capabilities,
    read_distribution_spec as read_distribution_spec,
    read_project_metadata as read_project_metadata,
)
from apprc.definition.installation import (
    InstallationHooks as InstallationHooks,
    ProjectSnapshot as ProjectSnapshot,
    RuntimeSelection as RuntimeSelection,
)
from apprc.distribution.models import (
    AppCapabilities as AppCapabilities,
    Artifact as Artifact,
    DistributionSpec as DistributionSpec,
    NativeBinding as NativeBinding,
    ProjectMetadata as ProjectMetadata,
    decode_native_binding as decode_native_binding,
    encode_native_binding as encode_native_binding,
)
from apprc.distribution.native import (
    NativeArtifact as NativeArtifact,
    NativeFrontendBuilder as NativeFrontendBuilder,
    NativeTarget as NativeTarget,
)
from apprc.distribution.project import (
    PreparedProject as PreparedProject,
    build_project_snapshot as build_project_snapshot,
)
